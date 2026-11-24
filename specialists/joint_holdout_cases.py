"""New synthetic wording families for the paired decoder holdout."""

from random import Random

from .data import _case_fields, _render_document


# Each family pairs a stay description, a benefit excerpt, and an endorsement
# with a ranking question that has two near-miss passages.
FAMILIES = (
    ("ward-reconciliation", "iso",
     "Unit ran this reconciliation on {notice_date}.\nCarrier reference assigned to the episode {POLICY_ID}; "
     "patient registration credential {MEMBER_ID}. First occupied a bed on {ADMISSION_DATE}. "
     "Cleared for departure on {DISCHARGE_DATE}.",
     "Hostel price for visitors: {old_room}. For payable inpatient occupancy the covered room ceiling is {ROOM_LIMIT} per night.",
     "This accepted certificate opens the annual benefit balance at {SUM_INSURED}; joining contribution {other_amount}.",
     "policy", "Under the issued wording, what governs the overnight amount the insurer pays for the covered patient?",
     "Each occupied night in an eligible ward is reimbursable up to {ROOM_LIMIT} under the effective wording.",
     ("The posted overnight tariff for all ward patients starts at {old_room}.",
      "The committee's unsigned draft suggests an overnight allowance of {other_amount}.")),
    ("clinical-handoff", "dotted",
     "Arrived at this hospital as an inpatient {ADMISSION_DATE}. The stay concluded at home transfer {DISCHARGE_DATE}. "
     "Accepted cover record {POLICY_ID} for the person identified by {MEMBER_ID}. Clerk checked the note on {notice_date}.",
     "Nightly standard accommodation reimbursement is limited to {ROOM_LIMIT}. An outpatient treatment bay is listed separately at {other_amount}.",
     "Confirmed insured amount on the start date: {SUM_INSURED}. Quote {quote} is superseded.",
     "claim_form", "What must reach claims intake before it will consider repayment for the stay?",
     "Submit the final itemised facility account together with the inpatient discharge record for repayment.",
     ("The intake officer recorded receipt of the account and discharge record in a previous example.",
      "For correction of hospital records, a registration receipt and photocopy of the member card are mandatory.")),
    ("retroactive-posting", "month-first",
     "ACCOUNTING HANDOFF {ref}\n{DISCHARGE_DATE} / occupant released\n{ADMISSION_DATE} / inpatient stay commenced\n"
     "{POLICY_ID} / payer authority verified\n{MEMBER_ID} / covered party verified\n{notice_date} / accounting post only.",
     "Available per eligible ward day: {ROOM_LIMIT} toward room charges. Listed provisional cash cost: {other_amount}.",
     "Under issued schedule {ref}, the insured reserve was established at {SUM_INSURED}.",
     "policy", "Which daily bed allowance was applicable before the later amendment took effect?",
     "For the dates immediately preceding the amendment, the then-binding daily bed allowance was {old_room}.",
     ("After signing the amendment, the binding daily bed allowance changed to {ROOM_LIMIT}.",
      "An even older illustration lists a daily allowance of {other_amount} without setting a binding amount.")),
    ("supersession-letter", "written",
     "Inquiry from {notice_date}: ignore cancelled proposal {quote}. Active instrument {POLICY_ID} belongs to "
     "enrolled key {MEMBER_ID}. Inpatient admission was confirmed for {ADMISSION_DATE}; release is recorded as {DISCHARGE_DATE}.",
     "The room portion of each inpatient day has a payable maximum of {ROOM_LIMIT}. The preliminary estimate showed {old_room}.",
     "The executed addendum states coverage for the current period at an aggregate of {SUM_INSURED}. "
     "A cancelled illustration states {other_amount}.",
     "schedule", "Does the effective inpatient cash rider apply to the enrolled dependent?",
     "The signed rider applies to the named dependent and pays a fixed amount per qualifying hospital day.",
     ("The signed rider applies to the primary subscriber; its inpatient cash does not extend to this dependent.",
      "A proposal would apply inpatient cash to this dependent after the insurer issues acceptance.")),
    ("paper-copy-correction", "dmy",
     "COPIED {notice_date}; original folio {ref}. Recorded patient card {MEMBER_ID}; applicable contract {POLICY_ID}. "
     "Entry onto the ward: {ADMISSION_DATE}. Final exit from inpatient care: {DISCHARGE_DATE}.",
     "For the occupied room under the policy, daily payment cannot exceed {ROOM_LIMIT}, "
     "while the facility's cashier lists {old_room}.",
     "Benefit amount in force at commencement {SUM_INSURED}. Contribution acknowledged {other_amount}.",
     "claim_form", "After receiving a request to correct the invoice, when must the replacement be supplied?",
     "After the request for a corrected invoice, supply the replacement within ten working days of receipt.",
     ("The claim must be filed within ten working days after inpatient release.",
      "An initial form shows a corrected invoice supplied after ten working days in an example.")),
    ("occupancy-diary", "month-first",
     "From {ADMISSION_DATE} through {DISCHARGE_DATE}, occupancy was inpatient and authorised. "
     "Desk reference {ref}. Verified insured person {MEMBER_ID} was registered against plan serial {POLICY_ID}.",
     "The ceiling for eligible standard ward lodging is {ROOM_LIMIT} for an occupied night. Staff lodging has its own {old_room} price.",
     "Rollover complete. This term's full insured protection is {SUM_INSURED}. File {quote} records the earlier proposal.",
     "schedule", "Which sum is the opening protection under the executed rollover?",
     "The executed rollover opens the term with insured protection of {SUM_INSURED}.",
     ("The rollover projection shows opening protection of {other_amount} if the proposal is accepted.",
      "The rollover office records a payment of {old_room} toward the premium rather than establishing protection.")),
    ("attachment-audit", "dotted",
     "Superseded quote {quote} appears on the scan. Apply verified payer key {POLICY_ID}, member credential {MEMBER_ID}.\n"
     "Current entry for hospital care {ADMISSION_DATE} | current completion of stay {DISCHARGE_DATE}.\n"
     "The audit signature was added on {notice_date}.",
     "Payable covered charge for the room may reach {ROOM_LIMIT} a day. A display price of {old_room} applies to an excluded room class.",
     "{SUM_INSURED} | Amount insured in the binding schedule. {other_amount} | Fee stated on the acknowledgement.",
     "policy", "Who can claim the current daily room allowance under this attachment?",
     "The accepted attachment authorises the daily room allowance for the covered inpatient named here.",
     ("The attachment illustration gives a daily room allowance to carers for reference only.",
      "The cancelled attachment offered a daily room allowance to a different person under another policy.")),
    ("dispatch-ledger", "written",
     "Dispatch entry on {notice_date}. For this episode use accepted policy code {POLICY_ID} and patient membership token {MEMBER_ID}. "
     "Admitted overnight on {ADMISSION_DATE}; subsequently went home on {DISCHARGE_DATE}.",
     "{ROOM_LIMIT} is the cap applicable to payable ward room expenses for each day. Staff board costs {other_amount}.",
     "At activation the member's annual maximum under the insured guarantee was {SUM_INSURED}. Receipt entry {other_amount}.",
     "claim_form", "What filing window applies to the original claim after leaving the hospital?",
     "The first reimbursement request must arrive within twenty calendar days of hospital departure.",
     ("The first request in a training example arrived twenty calendar days after the hospital stay.",
      "After the claim decision, the member has twenty calendar days to request review.")),
)


def holdout_rows():
    rng = Random(20261124)
    rows = {"span": [], "rank": []}
    seen_groups = set()
    for key, style, claim, policy, schedule, kind, query, relevant, negatives in FAMILIES:
        for number in range(1, 17):
            fields = _case_fields(rng, style)
            if number % 4 == 0:
                for label in ("POLICY_ID", "MEMBER_ID"):
                    fields[label] = "PAYER/" + fields[label].partition("-")[2]
            if number % 4 == 1:
                for label in ("SUM_INSURED", "ROOM_LIMIT", "other_amount", "old_room"):
                    fields[label] = fields[label].replace("INR ", "Rs. ")
            case = f"joint-holdout-{key}-{number:02d}"
            shared = {"case_id": case, "family": f"joint-release-{key}", "synthetic": True}
            receipt = "Cash entry {ref}, posted {notice_date}. Advance collected {other_amount}."
            documents = {"claim_form": claim, "policy": policy, "schedule": schedule, "receipt": receipt}
            for doc_kind, template in documents.items():
                text, spans = _render_document(template, fields)
                rows["span"].append({**shared, "id": f"{case}-span-{doc_kind}", "kind": doc_kind,
                                     "task": "span", "text": text, "spans": spans})
            choices = [(relevant.format_map(fields), True),
                       *((text.format_map(fields), False) for text in negatives)]
            signature = (query, tuple(sorted(choices)))
            if signature in seen_groups:
                continue
            seen_groups.add(signature)
            rng.shuffle(choices)
            for index, (text, label) in enumerate(choices):
                rows["rank"].append({**shared, "id": f"{case}-rank-{index}", "kind": kind, "task": "rank",
                                     "text": text, "query": query, "relevant": label})
    return rows
