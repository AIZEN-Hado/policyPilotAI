"""Synthetic extraction development data with balanced field supervision."""

from random import Random

from .data import _case_fields, _render_document


TRAIN = (
    ("policy", "Active policy number {POLICY_ID}. Member number {MEMBER_ID}. Prior quote reference {quote}. "
     "Admitted {ADMISSION_DATE}; discharged {DISCHARGE_DATE}. Update filed {notice_date}. "
     "Total insured cover {SUM_INSURED}. Standard room reimbursement limit {ROOM_LIMIT} per night."),
    ("schedule", "{ROOM_LIMIT} | payable for each ward day\n{SUM_INSURED} | benefit maximum for the policy term\n"
     "{other_amount} | registration fee\n{MEMBER_ID} | covered member\n{POLICY_ID} | valid contract\n"
     "{DISCHARGE_DATE} | inpatient episode ended\n{ADMISSION_DATE} | patient entered the facility"),
    ("claim_form", "Hospitalized from {ADMISSION_DATE} through {DISCHARGE_DATE}. Claim filed {notice_date}. "
     "Policy identifier {POLICY_ID}; insured person's identifier {MEMBER_ID}; internal case token {ref}. "
     "Maximum total plan liability {SUM_INSURED}. Room ceiling for one covered day {ROOM_LIMIT}."),
    ("policy", "Under agreement {POLICY_ID}, coverage of individual {MEMBER_ID} is confirmed. The stay's "
     "exit date was {DISCHARGE_DATE}, after entry on {ADMISSION_DATE}. Maximum for all covered losses is "
     "{SUM_INSURED}. The lesser per-night ward maximum is {ROOM_LIMIT}; former ward cap {old_room} is withdrawn."),
    ("schedule", "Annual aggregate protection for this certificate equals {SUM_INSURED}. For ordinary inpatient "
     "accommodation the insurer allows a daily maximum of {ROOM_LIMIT}. Provider charges {old_room} per day."),
    ("claim_form", "{ref} is the hospital's tracking code. Use {MEMBER_ID} as the claimant's enrollment key and "
     "{POLICY_ID} as the operative contract number. Patient left {DISCHARGE_DATE} after arriving {ADMISSION_DATE}."),
    ("policy", "Cancellation record for proposal {quote} and former enrolment {ref}. A deposit of {other_amount} "
     "appeared on the quote. This record asserts no operative policy, active member, or benefit limit."),
    ("policy", "Effective contract {POLICY_ID}; total insured benefit {SUM_INSURED}. A ward tariff of "
     "{old_room} is shown solely for comparison. This revision sets no room allowance."),
)

DEVELOPMENT = (
    ("schedule", "Protection record {POLICY_ID} applies to beneficiary {MEMBER_ID}. Receipt {ref}. "
     "Date care commenced {ADMISSION_DATE}; date inpatient care closed {DISCHARGE_DATE}. "
     "Full policy cover available {SUM_INSURED}. Reimbursement cap for a single standard ward night {ROOM_LIMIT}."),
    ("claim_form", "Date of release: {DISCHARGE_DATE}. Date accepted into care: {ADMISSION_DATE}. "
     "The governing agreement is numbered {POLICY_ID}. Person listed on the active roster {MEMBER_ID}. "
     "The aggregate insured amount stands at {SUM_INSURED}; daily lodging payout cannot exceed {ROOM_LIMIT}."),
    ("policy", "Plan coverage ceiling across all eligible claims {SUM_INSURED}. Maximum for each eligible "
     "bed night {ROOM_LIMIT}. Registrar brochure quote {other_amount} and publisher identifier {quote}. "
     "The registrar's figures do not set any benefit."),
    ("claim_form", "{MEMBER_ID} is the enrolled claimant for certificate {POLICY_ID}. {ref} is the hospital file. "
     "Hospitalization opened on {ADMISSION_DATE} and release occurred on {DISCHARGE_DATE}. A bed deposit of "
     "{other_amount} was collected."),
    ("policy", "Illustrative cover {other_amount} for proposal {quote}. A separate facility collection of "
     "{old_room} is due. No active benefit wording is stated in this illustration."),
)


def balanced_rows():
    result = {}
    styles = ("iso", "dmy", "dotted", "written", "month-first")
    for split, layouts, count, seed in (("train", TRAIN, 48, 20261127),
                                        ("validation", DEVELOPMENT, 24, 20261128)):
        rng = Random(seed)
        rows = []
        for layout, (kind, template) in enumerate(layouts):
            family = f"balanced-fields-{split}-{layout:02d}"
            for index in range(count):
                fields = _case_fields(rng, styles[index % len(styles)])
                for label in ("SUM_INSURED", "ROOM_LIMIT", "other_amount", "old_room"):
                    currency = ("INR ", "₹ ", "Rs. ")[index % 3]
                    fields[label] = fields[label].replace("INR ", currency, 1)
                case_id = f"{family}-{index:02d}"
                text, spans = _render_document(template, fields)
                rows.append({"id": f"{case_id}-span", "case_id": case_id, "family": family,
                             "kind": kind, "task": "span", "text": text, "spans": spans,
                             "synthetic": True})
        result[split] = rows
    return result
