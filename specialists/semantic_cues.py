"""Domain cues used as optional inputs to the specialist neural networks."""

import re


SPAN_CUES = {
    "arrival": ("arrival date", "hospital entry", "intake date", "care commencement", "first occupied", "first treatment", "start of stay", "admitted on", "accepted into care", "entered inpatient care", "first admitted", "checked into care", "took a ward bed", "admitted treatment"),
    "departure": ("release date", "ward release", "hospital exit", "return home", "returned home", "end of stay", "last inpatient day", "went home", "actual release", "left inpatient care", "home transfer", "cleared for departure", "final release", "completion of inpatient care"),
    "policy": ("policy identifier", "insurance instrument", "contract identifier", "plan identifier", "contract reference", "agreement number", "payer reference", "governing agreement", "coverage identifier", "enforceable contract", "operative certificate", "insurance record", "coverage record", "certificate code", "coverage authority"),
    "member": ("covered person number", "covered individual", "person roster", "roster entry", "named insured", "insured party", "insured party code", "individual registration", "enrollment key", "enrollee number", "beneficiary identifier", "membership token", "personal token", "patient registration credential", "eligible registrant"),
    "room": ("room reimbursement", "room charge", "room contribution", "room benefit", "ward allowance", "bed allowance", "bed night", "lodging cap", "lodging ceiling", "eligible lodging", "eligible occupancy", "standard ward", "shared ward", "ordinary accommodation", "payable accommodation", "overnight limit", "hospital room", "ward reimbursement", "wards overnight"),
    "sum": ("amount assured", "aggregate cover", "aggregate limit", "aggregate insured benefit", "total insured cover", "full policy cover", "total liability", "maximum liability", "entire term", "full term", "overall policy limit", "annual ceiling", "combined claims", "all claims", "all losses", "starting benefit balance", "total protection"),
    "excluded": ("for reference only", "for comparison only", "unapproved", "unsigned", "rejected", "lapsed", "archived copy", "no legal effect", "expired term", "withdrawn after review", "unused quote", "did not take effect", "subject to approval", "historical only", "not incorporated", "not operative"),
    "administrative": ("cash tariff", "cash price", "posted price", "facility fee", "registration fee", "private price", "booking deposit", "advance payment", "invoice total", "reader copy", "supplier quote", "clerical date", "generated on"),
    "reference": ("booking token", "quote reference", "clerk reference", "tracking code", "print reference", "facility record", "billing index", "hospital file", "office reference", "temporary file number"),
    "current": ("in the signed schedule", "approved benefit", "binding wording", "effective schedule", "executed certificate", "in force today", "confirmed for this stay", "applicable agreement", "accepted wording", "currently covered", "approved plan"),
}

AUTHORITY = {
    "current": r"agreed|active|applicable|approved|authori[sz]ed|binding|current(?:ly)?|effective|enforceable|executed|in force|issued|operative|signed|today|this (?:period|term|year)",
    "superseded": r"archived|before (?:the |this )?(?:amendment|change|replacement)|earlier|expired|former|historical|lapsed|obsolete|old|outgoing|prior|previous|replaced|retired|superseded|withdrawn",
    "proposal": r"draft|estimate|illustrati(?:on|ve)|pending|propos(?:al|ed)|provisional|quoted|quotation|subject to (?:approval|signature)|unsigned|would (?:add|cover|pay)",
    "facility_price": r"bill(?:ed|ing)?|booking deposit|cash (?:price|rate|tariff)|cashier|facility fee|hospital s own|invoice total|posted (?:charge|price|tariff)|provider price|rate card|registration fee|retail|supplier|tariff",
}
PURPOSE = {
    "room": r"accommodation|bed (?:allowance|charge|limit|night|rate)|daily lodging|lodging|overnight|room|ward stay",
    "total": r"aggregate|all claims|all (?:covered )?losses|annual|combined reimbursements|entire term|full term|insured (?:amount|balance|limit|total)|over the policy period|plan wide|sum insured|total (?:benefit|cover|coverage|insured|liability|protection)",
    "initial": r"first (?:claim|filing|packet|request|submission)|initial|original (?:application|claim|packet|request)|start(?:s|ing)? (?:after|from|on)|time from discharge",
    "amendment": r"already (?:filed|received|submitted)|amend(?:ed|ing|ment)?|correct(?:ed|ion)|replacement (?:bill|invoice)|supplemental filing",
    "appeal": r"appeal|contest|disput(?:e|ing)|request review|seek review|review of the decision|reconsideration",
    "required": r"accompany|compulsory|enclos(?:e|ure)|mandatory|must (?:attach|include|submit)|require(?:d|ment)|with every",
    "optional": r"if requested|on request|optional|provided separately|requested separately|supporting copy|upon request",
    "recipient": r"dependent|enrollee|enrolled|insured (?:person|party|patient)|member|named (?:person|patient)|subscriber",
    "patient_share": r"co ?pay(?:ment)?|cost share|deduct(?:ible|ion)|excess|insured s share|patient (?:contribution|share)|out of pocket",
}

_AUTHORITY = {name: re.compile(rf"\b(?:{expr})\b") for name, expr in AUTHORITY.items()}
_PURPOSE = {name: re.compile(rf"\b(?:{expr})\b") for name, expr in PURPOSE.items()}
RANK_SEMANTIC_NAMES = (tuple(f"authority_{name}_{side}" for name in AUTHORITY for side in ("q", "d", "match"))
                       + tuple(f"purpose_{name}_{side}" for name in PURPOSE for side in ("q", "d", "match"))
                       + ("authority_overlap", "different_authority", "purpose_overlap", "different_purpose"))


def rank_semantics(query, text):
    values = []
    summaries = []
    for patterns in (_AUTHORITY, _PURPOSE):
        requested = {name for name, expression in patterns.items() if expression.search(query)}
        observed = {name for name, expression in patterns.items() if expression.search(text)}
        for name in patterns:
            values.extend((float(name in requested), float(name in observed), float(name in requested & observed)))
        summaries.extend((len(requested & observed) / max(1, len(requested)),
                          float(bool(requested and observed and not requested & observed))))
    return values + summaries
