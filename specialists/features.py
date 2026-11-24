"""Deterministic lexical encodings and source offsets for the specialists."""

import hashlib
from collections import Counter
import re

from .contracts import DOCUMENT_KINDS, SPAN_LABELS, TOKEN_PATTERN


BIO_TAGS = ("O",) + tuple(
    f"{prefix}-{label}" for label in SPAN_LABELS for prefix in ("B", "I")
)
BIO_IDS = {tag: index for index, tag in enumerate(BIO_TAGS)}
PAD_ID = 0
WORD_HASH = b"pp-word-v1"
CHAR_HASH = b"pp-char-v1"
RANK_HASH = b"pp-rank-v1"

RANK_CUE_GROUPS = {
    "active": {"active", "applicable", "current", "effective", "operative"},
    "admission": {"admission", "admissions", "hospital", "inpatient", "overnight", "ward"},
    "cap": {"cap", "ceiling", "limit", "maximum", "threshold"},
    "excluded": {"archived", "expired", "historical", "optional", "superseded", "unrelated"},
    "paperwork": {
        "checklist", "document", "documents", "evidence", "form", "forms", "paperwork",
        "records", "submit",
    },
    "reimbursement": {"claim", "claims", "payment", "reimburse", "reimbursement"},
    "required": {"mandatory", "must", "prerequisite", "required", "requires"},
    "room": {"accommodation", "bed", "board", "room", "ward"},
}

RANK_SCALAR_NAMES = (
    "query_overlap", "document_overlap", "jaccard", "bigram_overlap",
    "all_query_terms_present", "query_length", "document_length", "document_has_digit",
) + tuple(f"kind_{kind}" for kind in DOCUMENT_KINDS) + tuple(
    f"{side}_{cue}" for cue in RANK_CUE_GROUPS for side in ("query", "document", "both")
)
RANK_MIN_FEATURES = len(RANK_SCALAR_NAMES) + 1
RANK_CONCEPTS = {
    "ward_room": r"accommodation|bed(?:ding)?|board|occupan(?:cy|t)|room|ward",
    "inpatient": r"admiss(?:ion|ions)|admitted|hospitali[sz]ation|inpatient|overnight|ward",
    "limit": r"at most|cap(?:ped|s)?|ceiling|limit(?:ed|s)?|max(?:imum|ima)?|no more than|up to",
    "payment": r"allowance|amounts?|cash|charg(?:e|es)|credit(?:ed)?|fees?|pa(?:id|y|yable|yment)|reimburs(?:e|able|ed|ement)|repay(?:ment)?",
    "insurer": r"benefit table|certificate|contract|cover(?:age|ed)?|insur(?:ance|ed|er)|plan|policy|schedule",
    "time": r"after|by when|calendar days?|clock|deadline|due|how long|period|time limit|within",
    "per_day": r"daily|each (?:day|night)|nightly|per (?:day|night)|service day",
    "first": r"first|fresh|initial|new claim|origin(?:al|ally)|start(?:s|ing)?",
    "claim": r"application|claim(?:ant|s)?|expense request|file(?:d|s)?|filing|lodge|reimbursement|repayment|submi(?:ssion|t)",
    "requirements": r"accompany|attach(?:ment|ments)?|checklist|compulsory|enclos(?:e|ures?)|mandatory|must|necessary|only with|prerequisit(?:e|es)|proof|records?|requir(?:e|ed|ement|ements|es)",
    "itemized_invoice": r"bill with separate charges|broken down by service|charge statement|detail(?:ed|s) (?:account|bill|charges|invoice)|invoice|itemi[sz]ed|line by line|line item",
    "discharge_note": r"(?:departure|discharge|exit|release) (?:abstract|letter|note|record|report|statement|summary)|note from the ward|ward record|when you left",
    "discharge_event": r"discharg(?:e|ed)|exit|leav(?:e|ing)|left|patient s departure|releas(?:e|ed)|ward departure",
    "cash_addon": r"add on|addition(?:al)?|cash (?:allowance|benefit|payment)|endorsement|rider|supplement",
    "named_patient": r"beneficiary|certificate holder|insured(?: person| patient)?|member(?:ship)?|patient|person listed|subscriber",
    "annual_cover": r"aggregate|annual|benefit (?:balance|pool|reserve)|insured (?:amount|balance|limit)|sum insured|term",
    "effective_date": r"attach(?:es|ment)?|effective|enter(?:s)? into force|in forc(?:e|ed)|start(?:s|ing)?",
    "deduction": r"co pay(?:ment)?|deduct(?:ible|ion)?|excess|patient share|retention",
}
RANK_CONTEXT = {
    "governing": r"accepted instrument|approv(?:al|ed)|binding|effective|eligible|in force|operative|under (?:this|the) (?:certificate|cover|contract|policy|schedule)",
    "outdated": r"archiv(?:e|ed)|earlier|ended|expir(?:ed|y)|former|historic(?:al)?|lapsed|obsolete|old|prior|previous|replac(?:ed|ement in preparation)|retir(?:ed|ement)|revok(?:ed|e)|superseded|void|withdrawn",
    "provisional": r"await(?:ing|s)?|draft|estimat(?:e|ed)|illustration|pending|planned|propos(?:al|ed)|provis(?:ional|ionally)|quot(?:ation|e|ed)|subject to signature",
    "illustrative": r"demonstration|example|for illustration|illustrative|sample|training|worked (?:example|out)|workshop",
    "different_payer": r"asset register|cash(?:ier)? (?:desk|price|tariff)|catering|cost cent(?:er|re)|equipment depreciation|facility s (?:cash|own|price)|hospital s (?:own|supplier)|price (?:list|sheet)|pricing circular|procurement|supplier|travel arrangement|ward maintenance",
    "different_recipient": r"accompanying visitor|attendant|caregiver|companion|different (?:insured|member|membership|person)|employee|family waiting room|guest|primary subscriber|separately insured|staff|visitor",
    "different_claim": r"appeal(?:s)?|already (?:filed|arrived|processed|received|submitted)|amend(?:ment|ed)|correct(?:ed|ion|ions)|disput(?:e|ing)|duplicate|replacement copy",
    "optional": r"can (?:include|submit)|keep for (?:reference|your records)|on request|optional|own records|only on review|requested separately",
    "restriction": r"cannot|exclud(?:e|ed|es|ing)|ineligible|insufficient|no (?:benefit|cover|payment)|not (?:covered|included|payable|required)",
    "filing_clock": r"calendar days?|deadline|days (?:after|from)|no later than|on or before|within",
    "filing_rule": r"arrive|file|lodge|must (?:reach|receive)|recei(?:pt|ve)|send|submi(?:ssion|t)",
    "amount_rule": r"at most|capp?ed|ceiling|limit(?:ed)?|max(?:imum)?|no more than|restricted to|up to",
}
RANK_V2_STOP = frozenset(
    "a an and are as at be by can could did does during for from has have how i in is it may of on or "
    "our s shall should so that the their them then these this to under was we were what when where "
    "which who will with would you your".split()
)
RANK_V2_CHANNELS = ("query", "document", "shared", "query_bigram", "document_bigram")
RANK_V2_CHANNEL_WEIGHTS = (0.4, 0.25, 0.6, 0.3, 0.2)
RANK_V2_HASH = b"pp-rank-v2"
RANK_V2_SCALAR_NAMES = RANK_SCALAR_NAMES + tuple(
    f"{side}_meaning_{cue}" for cue in RANK_CONCEPTS for side in ("query", "document", "both")
) + tuple(
    f"{side}_context_{cue}" for cue in RANK_CONTEXT for side in ("query", "document", "mismatch")
) + (
    "matched_concepts_fraction", "content_overlap", "content_jaccard", "contains_money",
    "contains_number", "request_both_bill_and_discharge_note", "initial_claim_clock",
    "covered_daily_room_cap", "governing_cash_addon",
)
RANK_V2_MIN_FEATURES = len(RANK_V2_SCALAR_NAMES) + 1
_CONCEPT_PATTERNS = {name: re.compile(rf"\b(?:{value})\b") for name, value in RANK_CONCEPTS.items()}
_CONTEXT_PATTERNS = {name: re.compile(rf"\b(?:{value})\b") for name, value in RANK_CONTEXT.items()}


def _digest(value, domain):
    return int.from_bytes(
        hashlib.blake2b(value.encode("utf-8"), digest_size=8, person=domain).digest(),
        "big",
    )


def _embedding_id(value, buckets, domain):
    return 1 + _digest(value, domain) % (buckets - 1)


def tokenize_with_offsets(text):
    return [(match.group(), match.start(), match.end()) for match in TOKEN_PATTERN.finditer(text)]


def encode_span(row, config):
    """Align BIO targets to complete tokens without changing source coordinates."""
    tokens = tokenize_with_offsets(row["text"])
    if not tokens:
        raise ValueError("Span input has no tokens")
    if len(tokens) > config["max_tokens"]:
        raise ValueError(f"Span input exceeds {config['max_tokens']} tokens")
    if any(len(token) > config["max_chars_per_token"] for token, _, _ in tokens):
        raise ValueError(f"Span input has a token exceeding {config['max_chars_per_token']} characters")

    starts = {start: index for index, (_, start, _) in enumerate(tokens)}
    ends = {end: index for index, (_, _, end) in enumerate(tokens)}
    tags = [BIO_IDS["O"]] * len(tokens)
    for span in row["spans"]:
        start = starts.get(span["start"])
        end = ends.get(span["end"])
        label = span["label"]
        if start is None or end is None or start > end or label not in SPAN_LABELS:
            raise ValueError("Invalid token boundaries or label for span target")
        if any(tags[index] != BIO_IDS["O"] for index in range(start, end + 1)):
            raise ValueError("Span targets overlap")
        tags[start] = BIO_IDS[f"B-{label}"]
        for index in range(start + 1, end + 1):
            tags[index] = BIO_IDS[f"I-{label}"]

    return {
        "word_ids": [
            _embedding_id(token.casefold(), config["word_hash_buckets"], WORD_HASH)
            for token, _, _ in tokens
        ],
        "char_ids": [
            [_embedding_id(char, config["char_vocab_size"], CHAR_HASH) for char in token]
            for token, _, _ in tokens
        ],
        "tags": tags,
        "offsets": [(start, end) for _, start, end in tokens],
    }


def decode_spans(text, offsets, tag_ids):
    """Emit spans begun by B tags and discard spans with mismatched continuations."""
    if len(offsets) != len(tag_ids):
        raise ValueError("Token offsets and BIO predictions have different lengths")

    spans = []
    active = None
    previous_end = 0
    for (start, end), tag_id in zip(offsets, tag_ids):
        if not previous_end <= start < end <= len(text):
            raise ValueError("Token offsets are out of source order or bounds")
        previous_end = end
        if not 0 <= tag_id < len(BIO_TAGS):
            raise ValueError("Unknown BIO tag ID")
        prefix, _, label = BIO_TAGS[tag_id].partition("-")
        if prefix == "I":
            if active is not None and active["label"] == label:
                active["end"] = end
            else:
                active = None
            continue
        if active is not None:
            spans.append(active)
            active = None
        if prefix == "B":
            active = {"label": label, "start": start, "end": end}
    if active is not None:
        spans.append(active)
    for span in spans:
        span["value"] = text[span["start"]:span["end"]]
    return spans


def lexical_terms(text):
    return [token.casefold() for token, _, _ in tokenize_with_offsets(text) if token.isalnum()]


def _content_terms(terms):
    return ["__number__" if term.isdecimal() else "__identifier__" if any(char.isdigit() for char in term) else term
            for term in terms if term not in RANK_V2_STOP]


def _rank_v2_features(text, query_terms, doc_terms, size, values, *, semantic=False):
    query_text, doc_text = " ".join(query_terms), " ".join(doc_terms)
    query_concepts = {name for name, cue in _CONCEPT_PATTERNS.items() if cue.search(query_text)}
    doc_concepts = {name for name, cue in _CONCEPT_PATTERNS.items() if cue.search(doc_text)}
    query_context = {name for name, cue in _CONTEXT_PATTERNS.items() if cue.search(query_text)}
    doc_context = {name for name, cue in _CONTEXT_PATTERNS.items() if cue.search(doc_text)}
    for cue in RANK_CONCEPTS:
        values.extend((float(cue in query_concepts), float(cue in doc_concepts),
                       float(cue in query_concepts and cue in doc_concepts)))
    for cue in RANK_CONTEXT:
        values.extend((float(cue in query_context), float(cue in doc_context),
                       float(cue not in query_context and cue in doc_context)))

    query, doc = _content_terms(query_terms), _content_terms(doc_terms)
    query_set, doc_set = set(query), set(doc)
    shared = query_set & doc_set
    values.extend((
        len(query_concepts & doc_concepts) / max(1, len(query_concepts)),
        len(shared) / max(1, len(query_set)),
        len(shared) / max(1, len(query_set | doc_set)),
        float("₹" in text or bool({"inr", "rs", "rupees"} & set(doc_terms))),
        float("__number__" in doc_set),
        float({"itemized_invoice", "discharge_note"} <= doc_concepts and "requirements" in doc_concepts),
        float({"filing_clock", "filing_rule"} <= doc_context and "different_claim" not in doc_context),
        float({"ward_room", "inpatient", "per_day"} <= doc_concepts and "amount_rule" in doc_context),
        float("cash_addon" in doc_concepts and "governing" in doc_context),
    ))
    if semantic:
        from .semantic_cues import rank_semantics

        values.extend(rank_semantics(query_text, doc_text))
    tail = [0.0] * (size - len(values))
    channels = (query, doc, sorted(shared), [" ".join(pair) for pair in zip(query, query[1:])],
                [" ".join(pair) for pair in zip(doc, doc[1:])])
    for channel, terms, weight in zip(RANK_V2_CHANNELS, channels, RANK_V2_CHANNEL_WEIGHTS, strict=True):
        for term, count in Counter(terms).items():
            hashed = _digest(f"{channel}:{term}", RANK_V2_HASH)
            sign = 1 if hashed >> 63 else -1
            tail[hashed % len(tail)] += sign * weight * count / len(terms)
    return values + tail


def ranking_features(query, text, kind, config):
    """Build scalar overlap/cue features and signed hashed lexical features."""
    size = config["features"]
    version = config.get("feature_version", 1)
    if type(version) is not int or version not in (1, 2, 3):
        raise ValueError("Invalid ranking feature version")
    minimum = RANK_V2_MIN_FEATURES if version >= 2 else RANK_MIN_FEATURES
    if version == 3:
        from .semantic_cues import RANK_SEMANTIC_NAMES

        minimum += len(RANK_SEMANTIC_NAMES)
    if size < minimum or kind not in DOCUMENT_KINDS:
        raise ValueError("Invalid ranking feature size or document kind")

    query_terms = lexical_terms(query)
    doc_terms = lexical_terms(text)
    query_set = set(query_terms)
    doc_set = set(doc_terms)
    shared = query_set & doc_set
    query_bigrams = set(zip(query_terms, query_terms[1:]))
    doc_bigrams = set(zip(doc_terms, doc_terms[1:]))
    values = [
        len(shared) / max(1, len(query_set)),
        len(shared) / max(1, len(doc_set)),
        len(shared) / max(1, len(query_set | doc_set)),
        len(query_bigrams & doc_bigrams) / max(1, len(query_bigrams)),
        float(bool(query_terms) and all(token in doc_set for token in query_terms)),
        min(len(query_terms) / 64, 1.0),
        min(len(doc_terms) / 256, 1.0),
        float(any(char.isdigit() for char in text)),
    ]
    values.extend(float(kind == known_kind) for known_kind in DOCUMENT_KINDS)
    for cue in RANK_CUE_GROUPS.values():
        query_match = bool(query_set & cue)
        doc_match = bool(doc_set & cue)
        values.extend((float(query_match), float(doc_match), float(query_match and doc_match)))

    if version >= 2:
        return _rank_v2_features(text, query_terms, doc_terms, size, values, semantic=version == 3)

    tail = [0.0] * (size - len(values))
    channels = ("query", query_terms), ("document", doc_terms), ("shared", sorted(shared))
    for channel, terms in channels:
        for token, count in Counter(terms).items():
            hashed = _digest(f"{channel}:{token}", RANK_HASH)
            sign = 1 if hashed >> 63 else -1
            tail[hashed % len(tail)] += sign * count / len(terms)
    return values + tail


def feature_spec(rank_config=None):
    spec = {
        "token_pattern": TOKEN_PATTERN.pattern,
        "offset_unit": "python_unicode_codepoint",
        "pad_id": PAD_ID,
        "bio_tags": list(BIO_TAGS),
        "document_kinds": list(DOCUMENT_KINDS),
        "hash": {
            "algorithm": "blake2b-64",
            "encoding": "utf-8",
            "byte_order": "big",
            "word_domain": WORD_HASH.decode(),
            "char_domain": CHAR_HASH.decode(),
            "rank_domain": RANK_HASH.decode(),
            "word_casefold": True,
            "char_casefold": False,
            "embedding_id_rule": "1 + hash % (buckets - 1)",
            "rank_channels": ["query", "document", "shared"],
            "rank_key_format": "channel:term",
            "rank_signed_by_high_bit": True,
        },
        "rank_scalar_features": list(RANK_SCALAR_NAMES),
        "rank_cue_groups": {name: sorted(cues) for name, cues in RANK_CUE_GROUPS.items()},
    }
    version = 1 if rank_config is None else rank_config.get("feature_version", 1)
    if type(version) is not int or version not in (1, 2, 3):
        raise ValueError("Invalid ranking feature version")
    if version >= 2:
        spec["rank_feature_version"] = version
        spec["rank_scalar_features"] = list(RANK_V2_SCALAR_NAMES)
        spec["rank_meaning_patterns"] = RANK_CONCEPTS.copy()
        spec["rank_context_patterns"] = RANK_CONTEXT.copy()
        spec["rank_hashed_terms"] = {"casefold": True, "stop_words": sorted(RANK_V2_STOP),
                                    "decimal": "__number__", "token_with_digit": "__identifier__"}
        spec["hash"].update(rank_domain=RANK_V2_HASH.decode(),
                            rank_channels=list(RANK_V2_CHANNELS),
                            rank_channel_weights=list(RANK_V2_CHANNEL_WEIGHTS))
    if version == 3:
        from .semantic_cues import AUTHORITY, PURPOSE, RANK_SEMANTIC_NAMES

        spec["rank_scalar_features"].extend(RANK_SEMANTIC_NAMES)
        spec["rank_authority_patterns"] = AUTHORITY.copy()
        spec["rank_purpose_patterns"] = PURPOSE.copy()
    return spec
