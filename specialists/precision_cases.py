"""Fresh synthetic wording families kept out of the training runtime."""

import random

from .data import Family, RankPair, _case_rows


FAMILIES = (
    Family(
        "precision-night-transfer", "month-first",
        {
            "claim_form": (
                "Beds office handoff. Log {ref}, printed {notice_date}.\n"
                "Accepted to inpatient service at the close of business on {ADMISSION_DATE}. "
                "Disposition home was entered for {DISCHARGE_DATE}.\n"
                "The payer contract charged for this encounter was {POLICY_ID}. "
                "The reconciled person record was {MEMBER_ID}. Proposal {quote} was cancelled."
            ),
            "schedule": "Opening annual benefits pool for this enrolment: {SUM_INSURED}. Installment received: {other_amount}.",
            "policy": "Each approved day in a shared inpatient room draws at most {ROOM_LIMIT}. The cashier deposit is {other_amount}.",
            "receipt": "Payment ledger dated {notice_date}: {ref} tendered {other_amount} toward the deposit.",
        },
        (
            RankPair("policy", "Which amount can a shared room draw from the insurer in one approved day?",
                     "Approved inpatient shared accommodation may draw up to {ROOM_LIMIT} on each service day.",
                     "Shared room charges reach {old_room} on each service day in the facility's cash tariff."),
            RankPair("claim_form", "What validates a request to repay the patient's first inpatient bill?",
                     "To validate the initial request, supply the final account in line-item form and the ward exit statement.",
                     "To validate a request for a second copy of an inpatient bill, submit the counter receipt."),
        ),
    ),
    Family(
        "precision-renewal-register", "dotted",
        {
            "claim_form": (
                "Record filed {notice_date}. Carryover illustration {quote} is informational.\n"
                "Patient register key = {MEMBER_ID} | Coverage ledger key in force = {POLICY_ID}\n"
                "Inpatient occupancy -> opened {ADMISSION_DATE} | closed {DISCHARGE_DATE}."
            ),
            "schedule": "The replacement certificate declares {SUM_INSURED} as its initial insured balance. Prior memo carried {other_amount}.",
            "policy": "Ceiling payable by this certificate for qualifying room costs: {ROOM_LIMIT} per day. {old_room} was the former ceiling.",
            "receipt": "Contribution {other_amount} booked against quote {quote} on {notice_date}.",
        },
        (
            RankPair("schedule", "Where is the binding first-day balance on the replacement certificate?",
                     "The replacement certificate opens the insured benefit balance at {SUM_INSURED} on the first day.",
                     "A first-day balance of {other_amount} appears in the replacement certificate proposal awaiting acceptance."),
            RankPair("policy", "Which payable ceiling governs covered bed fees under the current revision?",
                     "The operative revision caps its payment toward covered bed fees at {ROOM_LIMIT} per day.",
                     "A payable ceiling of {old_room} for covered bed fees appears in the revision whose term ended on {notice_date}."),
        ),
    ),
    Family(
        "precision-reconciled-folio", "dmy",
        {
            "claim_form": (
                "Final folio {ref}\n"
                "Paying plan / {POLICY_ID}\nPatient card used / {MEMBER_ID}\n"
                "In-hospital period: through {DISCHARGE_DATE}, starting {ADMISSION_DATE}. "
                "Accounts reconciled the folio on {notice_date}."
            ),
            "schedule": "Approved amount insured at inception is {SUM_INSURED}. Account reference {quote} shows a deposit of {other_amount}.",
            "policy": "Billable occupancy on this cover has a reimbursable daily maximum of {ROOM_LIMIT}, exclusive of visitor fees.",
            "receipt": "Copy request booked {notice_date}. Desk collection {other_amount}. Tracking folio {ref}.",
        },
        (
            RankPair("claim_form", "What should be enclosed to repay covered hospital costs under the folio?",
                     "Enclose the facility's itemized closing statement together with the clinical discharge note for payment.",
                     "Enclose the folio and the deposit receipt to obtain a replacement copy of the covered hospital bill."),
            RankPair("policy", "Which part sets payment for overnight occupancy within the cover?",
                     "For occupancy overnight on this cover, reimburse eligible room costs at most {ROOM_LIMIT} per billable day.",
                     "For occupancy overnight, a daily payment of {old_room} is available under the caregiver's travel arrangement only."),
        ),
    ),
    Family(
        "precision-benefit-bulletin", "written",
        {
            "claim_form": (
                "Status update for {ref}, sent {notice_date}.\n"
                "Entry (as inpatient): {ADMISSION_DATE}. Exit (home): {DISCHARGE_DATE}.\n"
                "Insurance instrument accepted: {POLICY_ID}; beneficiary record accepted: {MEMBER_ID}."
            ),
            "schedule": "The benefit reserve insured for this term starts at {SUM_INSURED}. Reference {quote} is a renewal illustration.",
            "policy": "For covered overnight wards the insurer allows {ROOM_LIMIT} per patient day. Additional caretaker charges appear as {other_amount}.",
            "receipt": "Acknowledged {other_amount} on {notice_date}. This receipt does not identify cover.",
        },
        (
            RankPair("policy", "Is the ward's published day rate the same as the cover's per-patient allowance?",
                     "The per-patient covered ward allowance is {ROOM_LIMIT} each day, regardless of the published cashier price.",
                     "The ward bulletin lists {old_room} as the published per-patient price, independent of insurance allowances."),
            RankPair("schedule", "Which reserve is insured for this term based on the accepted instrument?",
                     "The accepted instrument insures an opening benefit reserve of {SUM_INSURED} for this term.",
                     "The renewal illustration records a reserve of {other_amount}; the illustration requires signature before it takes effect."),
        ),
    ),
)


def precision_holdout():
    rng = random.Random(20261121)
    result = {"span": [], "rank": []}
    for family in FAMILIES:
        for serial in range(1, 17):
            span, rank = _case_rows(family, serial, rng)
            result["span"].extend(span)
            result["rank"].extend(rank)
    return result
