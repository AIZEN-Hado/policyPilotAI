"""Independently worded synthetic material for supervised and self-training runs."""

from random import Random

from .contracts import SPAN_LABELS
from .data import _case_fields, _render_document


# Each split has its own field wording. Layouts, field subsets, value formats,
# nearby duplicates and context order are varied independently of that wording.
FIELD_WORDING = {
    "train": (
        ("insurer contract", "policy identifier", "cover number", "certificate code", "payer reference", "binding certificate"),
        ("member code", "covered person number", "enrolled person", "beneficiary record", "insured party code", "membership token"),
        ("inpatient entry", "admitted on", "intake date", "start of stay", "arrival date", "checked into care"),
        ("release date", "ward release", "return home", "actual release", "hospital exit", "last inpatient day"),
        ("room reimbursement limit", "eligible lodging allowance", "standard ward maximum each night", "daily room ceiling", "ward allowance payable per day", "bed allowance for an occupied night"),
        ("aggregate insured benefit", "annual ceiling of insured cover", "sum insured for all claims", "overall policy limit", "total insured cover", "maximum for all losses in the term"),
    ),
    "validation": (
        ("insurance instrument", "governing agreement number", "policy certificate reference"),
        ("beneficiary identifier", "individual registration", "enrollee number"),
        ("hospital entry", "care commencement", "first admitted"),
        ("end of stay", "went home", "left inpatient care"),
        ("ordinary accommodation limit", "room benefit maximum per night", "eligible occupancy reimbursement"),
        ("aggregate cover maximum", "total liability over the full term", "total protection available"),
    ),
    "pool": (
        ("operative certificate", "plan identifier", "payer contract"),
        ("covered individual", "patient registration credential", "enrollment key"),
        ("entered inpatient care", "taken into care", "accepted into care"),
        ("home transfer", "cleared for departure", "inpatient episode ended"),
        ("lodging cap per eligible day", "payable accommodation each night", "overnight limit for standard ward care"),
        ("amount assured for the year", "insured total for the entire period", "maximum liability for combined claims"),
    ),
    "test": (
        ("coverage authority", "coverage identifier", "enforceable contract"),
        ("personal token", "roster entry for the named insured", "eligible registrant"),
        ("first occupied an inpatient bed", "first treatment under admitted care", "initial date of admission"),
        ("completion of inpatient care", "final release to home", "ward departure date"),
        ("hospital room contribution per occupied day", "eligible ward reimbursement for each night", "lodging ceiling for standard accommodation"),
        ("starting benefit balance for the full term", "total insured amount under the plan", "aggregate limit across eligible claims"),
    ),
}

ACTIVE = {"train": ("Active record", "Confirmed for this stay", "Issued schedule", "Applicable entry"),
          "validation": ("Effective schedule", "Approved plan"),
          "pool": ("Accepted wording", "Approved benefit"),
          "test": ("In the signed schedule", "Binding wording")}
INACTIVE = {"train": ("Former", "Draft", "Previous", "Withdrawn"),
            "validation": ("Prior", "Unapproved"), "pool": ("Replaced", "Unsigned"),
            "test": ("Lapsed", "Excluded")}


def _field_values(rng, index):
    style = ("iso", "dmy", "dotted", "written", "month-first")[index % 5]
    fields = _case_fields(rng, style)
    prefix = rng.choice(("REG/", "PX-", "MEM-", "CAL/", "COV-"))
    identifiers = rng.sample(range(100000, 1000000), 4)
    fields.update({key: prefix + str(value) for key, value in
                   zip(("POLICY_ID", "MEMBER_ID", "other_policy", "other_member"), identifiers, strict=True)})
    currency = rng.choice(("INR ", "₹ ", "Rs. "))
    room, old_room = rng.sample(range(2500, 48001, 250), 2)
    total, old_total = rng.sample(range(35000, 1500001, 5000), 2)
    fields.update({k: f"{currency}{v:,}" for k, v in zip(("ROOM_LIMIT", "old_room", "SUM_INSURED", "old_total"),
                  (room, old_room, total, old_total), strict=True)})
    return fields


def _clause(split, layout, lead, hint, field, status):
    if layout == 0:
        return f"{lead} for {hint}: {{{field}}}"
    if layout == 1:
        return f"{{{field}}} | {hint} | {lead}"
    if layout == 2:
        return f"{lead} shows {hint} as {{{field}}}"
    if layout == 3:
        return f"{hint} = {{{field}}} ({lead.lower()})"
    if layout == 4:
        return f"{lead} / {{{field}}} / {hint}"
    return f"{hint} {{{field}}} is {status} in the {lead.lower()}"


def _span_rows(split, count, rng, *, wording=None, active=None, inactive_status=None,
               layouts=None, family_prefix=None):
    inactive_values = ("other_policy", "other_member", "notice_date", "notice_date", "old_room", "old_total")
    wording = FIELD_WORDING[split] if wording is None else wording
    active = ACTIVE[split] if active is None else active
    inactive_status = INACTIVE[split] if inactive_status is None else inactive_status
    layouts = layouts or ((0, 1, 2, 3), (1, 2, 4), (0, 3, 4, 5), (1, 3, 4, 5))[
        ("train", "validation", "pool", "test").index(split)]
    family_prefix = family_prefix or f"composed-{split}"
    rows = []
    for index in range(count):
        selected = rng.sample(range(6), rng.choice((0, 1, 2, 3, 4, 5, 6)))
        fields = _field_values(rng, index)
        layout = rng.choice(layouts)
        clauses = []
        for label_index, (label, inactive) in enumerate(zip(SPAN_LABELS, inactive_values, strict=True)):
            hint = rng.choice(wording[label_index])
            if label_index in selected:
                clauses.append(_clause(split, layout, rng.choice(active), hint, label, "confirmed"))
            if rng.random() < 0.55 or not selected and label_index == index % 6:
                clauses.append(_clause(split, layout, rng.choice(inactive_status), hint, inactive, "withdrawn"))
        rng.shuffle(clauses)
        if rng.random() < 0.6:
            clauses.insert(rng.randrange(len(clauses) + 1), "Clerk reference {ref}")
        sep = "\n" if layout in (1, 4) else rng.choice((". ", "; ", "\n"))
        rendered, spans = _render_document(sep.join(clauses), fields)
        family = f"{family_prefix}-span-{layout}"
        case = f"{family}-{index:05d}"
        rows.append({"case_id": case, "family": family, "id": case, "task": "span", "synthetic": True,
                     "kind": rng.choice(("schedule", "policy", "claim_form", "discharge", "bill")),
                     "text": rendered, "spans": spans})
    return rows


RANK_TOPICS = {
    "train": ("room benefit", "aggregate cover", "initial claim", "corrected invoice", "appeal", "required attachments", "optional supporting copy", "insured person's deductible"),
    "validation": ("lodging ceiling", "annual insured amount", "original request", "supplemental filing", "reconsideration", "mandatory enclosures", "requested separately", "insured's cost share"),
    "pool": ("ward reimbursement", "full term total protection", "first reimbursement packet", "claim amendment", "contest the decision", "compulsory attachments", "optional enclosures", "patient share"),
    "test": ("payable hospital room charge", "combined benefit liability", "first submission", "already filed claim correction", "seek review of the decision", "document required with every claim", "supporting copy on request", "applicable excess"),
}
RANK_AUTHORITY = {
    "train": (("currently in force", "active", "issued"), ("expired", "previous", "retired"), ("draft", "pending", "unsigned")),
    "validation": (("operative", "effective", "binding"), ("prior", "former", "replaced"), ("provisional", "proposed", "subject to approval")),
    "pool": (("applicable", "approved", "current"), ("historical", "withdrawn", "superseded"), ("estimate", "proposal", "subject to signature")),
    "test": (("signed", "enforceable", "executed"), ("outgoing", "obsolete", "lapsed"), ("illustrative", "quoted", "awaiting signature")),
}
QUESTION_STEMS = {"train": ("Locate the {} {} rule.", "Which passage establishes the {} {}?", "Find the {} condition for {}."),
                  "validation": ("Where does the {} wording specify {}?", "Identify the {} provision on {}."),
                  "pool": ("Which entry describes the {} terms for {}?", "Provide the {} clause on {}."),
                  "test": ("What passage should I cite for the {} position on {}?", "Which excerpt speaks to {} terms about {}?")}
RANK_CLAUSE_STEMS = {"train": ("The {} {} is specified as {}.", "Under the {} wording, {} is set to {}."),
                    "validation": ("Recorded in the {} text for {} is {}.",),
                    "pool": ("For {} terms, the entry governing {} provides {}.",),
                    "test": ("Application of the {} instrument puts {} at {}.", "The {} instrument records {} with a value of {}.")}


def _rank_rows(split, count, rng, *, topics=None, authority=None, question_stems=None,
               clause_stems=None, family_prefix=None):
    scenes = {
        0: lambda field, days: field["ROOM_LIMIT"] + " per ward night",
        1: lambda field, days: field["SUM_INSURED"] + " for the period",
        2: lambda field, days: f"{days} days after discharge",
        3: lambda field, days: f"{days} days from original receipt",
        4: lambda field, days: f"{days} days from the determination",
        5: lambda field, days: "the final statement of charges and the inpatient release summary",
        6: lambda field, days: "the treatment receipt after an insurer request",
        7: lambda field, days: field["old_room"] + " per qualifying admission",
    }
    topics = RANK_TOPICS[split] if topics is None else topics
    authority = RANK_AUTHORITY[split] if authority is None else authority
    question_stems = QUESTION_STEMS[split] if question_stems is None else question_stems
    clause_stems = RANK_CLAUSE_STEMS[split] if clause_stems is None else clause_stems
    family_prefix = family_prefix or f"composed-{split}"
    rows = []
    for index in range(count):
        fields = _field_values(rng, index)
        topic = index % len(topics)
        other = rng.choice([i for i in range(len(topics)) if i != topic])
        target = (index // len(topics)) % len(authority)
        family = f"{family_prefix}-rank-{topic}"
        case = f"{family}-{index:05d}"
        term = rng.choice(authority[target])
        query = rng.choice(question_stems).format(term, topics[topic])
        candidates = [(when, topic) for when in range(3)] + [(target, other)]
        rng.shuffle(candidates)
        for position, (when, subject) in enumerate(candidates):
            requested_fields = fields if when == target else _field_values(rng, index)
            # One of the plausible answers belongs to the same authority but a nearby topic.
            # A different adjective for the same authority prevents plain word matching alone.
            clause_term = rng.choice(authority[when])
            statement = rng.choice(clause_stems).format(
                clause_term, topics[subject], scenes[subject](requested_fields, rng.randrange(5, 80)))
            rows.append({"case_id": case, "family": family, "id": f"{case}-{position}", "task": "rank",
                         "synthetic": True, "kind": "policy" if topic in (0, 1, 7) else "claim_form",
                         "query": query, "text": f"Entry {fields['ref']}\n{statement}",
                         "relevant": when == target and subject == topic})
    return rows


def composed_rows():
    output = {}
    for split, seed, spans, groups in (("train", 20261211, 2600, 800), ("validation", 20261212, 460, 240),
                                       ("pool", 20261213, 1300, 600), ("test", 20261214, 520, 312)):
        rng = Random(seed)
        output[split] = {"span": _span_rows(split, spans, rng), "rank": _rank_rows(split, groups, rng)}
    return output
