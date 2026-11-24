"""Fictional room-cap and nearby evidence examples with exact source labels."""

from random import Random

from .data import _case_fields, _render_document


TRAIN = (
    ("standard-charge", "Facility base tariff {old_room}. The eligible standard inpatient room amount payable under this contract is limited to {ROOM_LIMIT} for each midnight."),
    ("authorized-cot", "The final authorization assigns {ROOM_LIMIT} as the daily maximum for the covered bed. A submitted request listed {other_amount}."),
    ("published-tariff", "Published billed bed rate {old_room} per night. Amount insurer accepts per qualifying ward night: {ROOM_LIMIT}."),
    ("benefit-matrix", "Standard occupancy | covered amount each day | {ROOM_LIMIT}\nAttendant boarding | excluded price | {other_amount}."),
    ("retired-limit", "The expired policy allowed {old_room} daily for a shared room. Under the in-force revision we reimburse up to {ROOM_LIMIT} for each standard ward night."),
    ("admission-excerpt", "If admission qualifies, the lodging component for the covered inpatient is capped at {ROOM_LIMIT} per 24-hour stay. Deposits may be {other_amount}."),
    ("room-invoice", "This statement contains a provider room collection of {old_room} a day. The contractual reimbursement ceiling shown on the attached active endorsement is {ROOM_LIMIT} per night."),
    ("reverse-matrix", "{other_amount} | service deposit reference only.\n{ROOM_LIMIT} | binding reimbursement upper bound per qualifying day in a shared room."),
    ("room-grade", "For ordinary inpatient accommodation, expenses are covered only up to {ROOM_LIMIT} per day. The premium suite tariff on the same sheet is {old_room}."),
    ("endorsement-net", "Under the executed addendum, apply the room-rent limit of {ROOM_LIMIT} per covered day. Ignore the nonbinding illustration of {other_amount}."),
    ("per-person", "Each insured patient receives at most {ROOM_LIMIT} a night for shared ward lodging; meals for accompanying guests can cost {other_amount}."),
    ("financial-summary", "Reimbursable charges for overnight ward accommodation under the accepted certificate may not exceed {ROOM_LIMIT} per night. Provider tariff {old_room}."),
    ("policy-annotation", "Example A uses {other_amount} for the room, for illustration only. The operative maximum for the insured's room is {ROOM_LIMIT} for each eligible night."),
    ("first-draft", "A draft requests {old_room} as the per-day room allowance. No per-day amount has been adopted."),
    ("provider-only", "Nightly room tariff {other_amount} per patient. Deposit {old_room}. This pricing schedule does not state an insurer benefit limit."),
    ("nonmonetary-room", "Only the shared ward category is permitted. The policy defines no fixed rupee cap for occupancy. An administration fee of {other_amount} applies."),
)

DEVELOPMENT = (
    ("certified-daily-bed", "Approved shared bed cost payable per qualifying inpatient day {ROOM_LIMIT}. The counter quoted {old_room} as the cash charge."),
    ("printed-day-rate", "The clinically eligible ward's daily insurance reimbursement is no greater than {ROOM_LIMIT}. Printed old day rate {old_room}."),
    ("ward-tier-no-cap", "The policy permits a shared bed, with no numeric room benefit in this section. Cash deposit {other_amount}."),
)

HOLDOUT = (
    ("occupant-allowance", "Actual facility charge for a private suite {old_room}. The accepted reimbursement amount for keeping the insured overnight in the common ward may not exceed {ROOM_LIMIT} a night.",
     "Locate the binding amount payable for one overnight stay in the common ward."),
    ("hospital-payment-grid", "Amount | Basis\n{other_amount} | facility registration only\n{ROOM_LIMIT} | maximum payable toward each ordinary inpatient day of room occupancy.",
     "Which entry sets the insurance reimbursement maximum for daily ordinary-room occupancy?"),
    ("regulator-example", "The example tariff assumed {old_room}. For the signed cover, base reimbursement attributable to the patient's lodging is capped at {ROOM_LIMIT} for each admitted day.",
     "Where is the actual patient lodging cap in the signed cover?"),
    ("care-day-limit", "An older bill used {old_room}. In the binding benefit schedule the eligible shared accommodation payable for the treatment day has an upper charge of {ROOM_LIMIT}.",
     "What section gives the active per-treatment-day ceiling on eligible accommodation reimbursement?"),
    ("authorization-message", "A request for {other_amount} was logged before enrolment. For a night of eligible hospital residence the decision confirms a maximum of {ROOM_LIMIT} for the room.",
     "What passage confirms the insurer's maximum for an eligible hospital room night?"),
    ("head-office-policy", "Participant meal fees: {other_amount}. The insurer will contribute no more than {ROOM_LIMIT} for occupancy of a standard room on each approved date.",
     "Find the charge limit for an approved date of standard-room occupancy."),
)

CLAIMS = (
    "Utilisation note {ref}. Entered the inpatient service on {ADMISSION_DATE}. Inpatient care ended on {DISCHARGE_DATE}. "
    "Coverage instruction {POLICY_ID}; verified occupant key {MEMBER_ID}. Copied on {notice_date}.",
    "Reviewed case {ref}\n{DISCHARGE_DATE} / release to home\n{ADMISSION_DATE} / start of admitted care\n"
    "{MEMBER_ID} / entitled person\n{POLICY_ID} / applicable policy agreement.",
    "The enrolled claimant {MEMBER_ID} was admitted on {ADMISSION_DATE} and returned home on {DISCHARGE_DATE}. "
    "Applicable contract reference {POLICY_ID}. Secondary clerical reference {ref}.",
)

HOLDOUT_NEGATIVES = (
    ("The front desk sets an overnight hospital bed tariff of {old_room}. This schedule records private payment only.",
     "The uninsured cash price for an overnight stay is {other_amount}. Current policy charges appear separately."),
    ("An unsigned annex suggests the ordinary inpatient benefit should increase to {old_room}.",
     "The room billing grid lists {other_amount} as the registration balance for cashier reconciliation."),
    ("An illustrative bill uses {old_room} as the lodging expense per admitted day.",
     "A prior expired annex listed the lodging ceiling at {other_amount}; this is retained for comparison."),
    ("The outpatient day clinic reimburses facility chair charges up to {old_room} per treatment day.",
     "Shared accommodations for visitors have a hospital price of {other_amount} for the treatment day."),
    ("The hospital estimate for a room night is {old_room}, as included in the pre-enrolment inquiry.",
     "For eligible admissions a deposit of {other_amount} will be collected before any room authorization."),
    ("The draft contribution schedule showed {old_room} for a standard room on an approved date.",
     "On each approved date, an attendant lodging price of {other_amount} appears in the facility rate card."),
)


def _span(shared, text, kind, fields):
    rendered, spans = _render_document(text, fields)
    return {**shared, "id": f"{shared['case_id']}-span-{kind}", "task": "span",
            "kind": kind, "text": rendered, "spans": spans}


def room_rows():
    rng = Random(20261125)
    output = {split: {"span": [], "rank": []} for split in ("train", "validation", "test")}
    for split, layouts, count in (("train", TRAIN, 40), ("validation", DEVELOPMENT, 20), ("test", HOLDOUT, 24)):
        for layout_index, (name, paragraph, *probe) in enumerate(layouts):
            for index in range(count):
                style = ("iso", "dmy", "dotted", "written", "month-first")[index % 5]
                fields = _case_fields(rng, style)
                if index % 3 == 0:
                    for label in ("ROOM_LIMIT", "SUM_INSURED", "old_room", "other_amount"):
                        fields[label] = fields[label].replace("INR ", ("₹ " if index % 2 else "Rs. "))
                case = f"room-context-{split}-{name}-{index:02d}"
                shared = {"case_id": case, "family": f"room-context-{split}-{name}", "synthetic": True}
                output[split]["span"].append(_span(shared, paragraph, "policy", fields))
                if split == "test":
                    output[split]["span"].append(_span(shared, CLAIMS[layout_index % len(CLAIMS)], "claim_form", fields))
                    output[split]["span"].append(_span(shared,
                        "Benefit reserve on current instrument {SUM_INSURED}. Earlier illustration {other_amount}.",
                        "schedule", fields))
                if "{ROOM_LIMIT}" not in paragraph:
                    continue
                query = probe[0] if probe else f"In this {name.replace('-', ' ')} record, what is the binding room allowance?"
                alternatives = HOLDOUT_NEGATIVES[layout_index] if split == "test" else (
                    "Provider's overnight room rate for this case is {old_room}. This is a cash tariff.",
                    "An earlier draft proposed a reimbursement allowance of {other_amount} per room day.",
                )
                texts = ((paragraph, True), *((text, False) for text in alternatives))
                output[split]["rank"].extend({**shared, "id": f"{case}-rank-{i}", "task": "rank", "kind": "policy",
                                              "query": query, "text": f"Record {fields['ref']}\n{text.format_map(fields)}",
                                              "relevant": yes}
                                             for i, (text, yes) in enumerate(texts))
    return output
