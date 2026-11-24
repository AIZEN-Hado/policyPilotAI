"""Versioned field-context features for the structured span model."""

from functools import lru_cache
import re

from .features import CHAR_HASH, WORD_HASH, _embedding_id, encode_span
from .structured import value_candidates


CONTEXT_VERSION = 1
CONTEXT_WINDOW = 12
_DIGIT_RUN = re.compile(r"\d+")
_AMOUNT_SHAPE = re.compile(r"^(?:inr\b|rs\.?\s|₹)|\d[,\.]\d|\b(?:inr|rupees)$", re.I)
_CUES = {
    "arrival": (
        "admit", "admitted", "admission", "arrival", "arrived", "checked in", "checked into",
        "entry", "entered", "inpatient entry", "intake", "taken into care", "received on the ward",
        "episode opened", "bed assignment", "opened", "began", "begin", "start", "starting",
        "commenced", "accepted to inpatient service", "from",
    ),
    "departure": (
        "discharge", "discharged", "disposition home", "departure", "departed", "exit", "exited",
        "release", "released", "left", "leaving", "went home", "allowed to leave", "checked out",
        "sent home", "closed", "ended", "ending", "until", "through", "discharge from",
    ),
    "policy": (
        "insurer contract", "policy", "policy code", "policy number", "policy id", "contract",
        "certificate", "coverage ledger", "covered certificate", "cover number", "insurance instrument",
        "payer contract", "plan number", "paying plan", "binding certificate",
    ),
    "member": (
        "member", "member code", "member number", "member id", "beneficiary", "beneficiary record",
        "membership", "person covered", "enrolment code", "enrolled person",
        "patient card", "patient register", "covered person", "individual card",
    ),
    "sum": (
        "sum insured", "insured balance", "insured amount", "insured total", "amount insured",
        "total cover", "maximum allocation", "annual insured amount", "insured reserve", "benefit reserve",
        "annual benefits pool", "benefit pool", "declared cover", "insured benefit balance",
    ),
    "room": (
        "room allowance", "room expense ceiling", "payment maximum", "ward room", "daily maximum",
        "occupancy", "room costs", "room limit", "reimbursable daily maximum", "per patient day",
        "daily room", "room and board", "payment stops", "bed fees", "shared accommodation",
        "accommodation component", "overnight accommodation",
    ),
    "per_day": (
        "daily", "per day", "each day", "per night", "each night", "one night", "a night",
        "per occupied day", "per patient day", "overnight",
    ),
    "current": (
        "current", "actual", "operative", "accepted", "qualifying", "in force", "binding", "eligible",
        "under review", "selected for review", "covers", "used", "final", "completed",
    ),
    "excluded": (
        "historical", "earlier", "prior", "former", "previous", "archived", "obsolete", "superseded",
        "replaced", "cancelled", "withdrawn", "pending", "planned", "provisional", "estimate",
        "illustration", "proposal", "preliminary", "draft", "excluded", "no current",
    ),
    "administrative": (
        "printed", "filed", "issued", "revision date", "registered", "posted", "generated", "exported",
        "processed", "recorded", "form received", "stamp", "ledger created", "tendered", "transaction",
        "payment", "posting", "received on", "signed", "reconciled", "copy request", "deposit",
    ),
    "reference": (
        "reference", "ref", "account number", "correspondence", "tracker", "locator",
        "quote", "illustration", "search key", "proposal", "voucher", "tracking",
    ),
}

def _phrase_index(cues):
    index = {}
    for role, entries in cues.items():
        for entry in entries:
            words = tuple(entry.split())
            index.setdefault(words[0], []).append((words, role))
    for options in index.values():
        options.sort(key=lambda entry: (-len(entry[0]), entry[1]))
    return index


_PHRASES = _phrase_index(_CUES)


@lru_cache(maxsize=1)
def _expanded_phrases():
    from .semantic_cues import SPAN_CUES

    return _phrase_index({role: tuple(dict.fromkeys(entries + SPAN_CUES.get(role, ())))
                          for role, entries in _CUES.items()})


def _cue_occurrences(words, phrases):
    occurrences = []
    for index, word in enumerate(words):
        for phrase, role in phrases.get(word, ()):
            stop = index + len(phrase)
            if tuple(words[index:stop]) == phrase:
                occurrences.append((index, stop - 1, role))
    return occurrences


def _candidate_tokens(text, offsets):
    groups = value_candidates(text, offsets)
    positions = {}
    # Prefer dates, then complete monetary expressions over identifier fragments.
    # Bare numbers carry no implied field role.
    for label, kind in (("ADMISSION_DATE", "date"), ("SUM_INSURED", "number"), ("POLICY_ID", "identifier")):
        for start, end in groups[label]:
            if any(index in positions for index in range(start, end + 1)):
                continue
            value = text[offsets[start][0]:offsets[end][1]]
            value_kind = "amount" if kind == "number" and _AMOUNT_SHAPE.search(value) else kind
            for index in range(start, end + 1):
                positions[index] = (value_kind, start, end)
    return positions


def _context_symbols(start, end, occurrences, lines, positions):
    nearest = {}
    for left, right, role in occurrences:
        if right < start:
            index, side, distance = right, "before", start - right
        elif left > end:
            index, side, distance = left, "after", left - end
        else:
            continue
        if distance > CONTEXT_WINDOW:
            continue
        near_value = any(i in positions for i in range(min(index, start), max(index, end) + 1)
                         if i < start or i > end)
        line = "line" if lines[index] == lines[start] else "other_line"
        boundary = "across_value" if near_value else "adjacent_value"
        record = (distance, line, boundary)
        key = (role, side)
        if key not in nearest or record < nearest[key]:
            nearest[key] = record
    symbols = []
    for (role, side), (distance, line, boundary) in sorted(nearest.items(), key=lambda item: (item[1], item[0])):
        symbols.extend((f"cue:{role}:{side}", f"cue:{role}:{side}:{line}:{boundary}"))
        if distance <= 2:
            symbols.append(f"cue:{role}:{side}:close")
    return symbols


def _clause_roles(start, end, occurrences, words, lines, positions, kind):
    roles = {"date": {"arrival", "departure"}, "identifier": {"policy", "member"},
             "amount": {"room", "sum"}, "number": {"room", "sum"}}[kind]
    nearest = []
    for left, right, role in occurrences:
        if role not in roles | {"excluded", "administrative", "reference", "current", "per_day"}:
            continue
        if right < start:
            between, distance, side = range(right + 1, start), start - right, "before"
        elif left > end:
            between, distance, side = range(end + 1, left), left - end, "after"
        else:
            continue
        if distance > CONTEXT_WINDOW or lines[left] != lines[start]:
            continue
        if any((i in positions or words[i] in {";", ".", "!", "?"}) for i in between):
            continue
        nearest.append((distance, role, side))
    symbols = []
    for _, role, side in sorted(nearest):
        token = f"clause:{role}:{side}"
        if token not in symbols:
            symbols.append(token)
    return symbols[:6]


def encode_contextual_span(row, config):
    """Keep original source coordinates and encode cues independent of the annotation."""
    encoded = encode_span(row, config)
    text = row["text"]
    offsets = encoded["offsets"]
    words = [text[start:end].casefold() for start, end in offsets]
    version = config.get("context_feature_version", CONTEXT_VERSION)
    if type(version) is not int or version not in (CONTEXT_VERSION, 2):
        raise ValueError("Invalid span context feature version")
    occurrences = _cue_occurrences(words, _expanded_phrases() if version == 2 else _PHRASES)
    positions = _candidate_tokens(text, offsets)
    lines, line, previous = [], 0, 0
    for start, end in offsets:
        line += text.count("\n", previous, start)
        lines.append(line)
        previous = end
    markers = {}
    for start, end, role in sorted(occurrences, key=lambda item: (item[0], -item[1], item[2])):
        markers.setdefault(start, f"cue:{role}")
        for index in range(start + 1, end + 1):
            markers.setdefault(index, f"cue_part:{role}")

    word_ids, char_ids, context = [], [], {}
    for index, word in enumerate(words):
        status = "line_start" if index == 0 or lines[index - 1] != lines[index] else "line_content"
        default = _DIGIT_RUN.sub("0", word)
        symbols = [f"kind:{row.get('kind', 'unknown')}", status]
        if index in positions:
            kind, first, last = positions[index]
            part = "start" if index == first else "part"
            lexical = f"value:{kind}:{part}"
            symbols.extend((lexical, f"shape:{default}"))
            if first not in context:
                context[first] = _context_symbols(first, last, occurrences, lines, positions)
                if version == 2:
                    context[first] = _clause_roles(first, last, occurrences, words, lines, positions, kind) + context[first]
            symbols.extend(context[first])
        else:
            lexical = markers.get(index, default)
            symbols.extend((lexical, *default))
        word_ids.append(_embedding_id(lexical, config["word_hash_buckets"], WORD_HASH))
        char_ids.append([_embedding_id(symbol, config["char_vocab_size"], CHAR_HASH)
                         for symbol in symbols[:config["max_chars_per_token"]]])
    return {**encoded, "word_ids": word_ids, "char_ids": char_ids}
