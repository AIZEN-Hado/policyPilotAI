"""Additional synthetic evidence-ranking groups for training."""

from dataclasses import dataclass
from random import Random

from .data import _case_fields


@dataclass(frozen=True)
class RankingCase:
    name: str
    kind: str
    queries: tuple[str, str]
    answer: str
    distractors: tuple[str, str, str]


CASES = (
    RankingCase("shared-ward", "policy",
        ("How much does the insurer allow each approved day in a shared ward?",
         "Where is the ceiling for a qualifying shared hospital room?"),
        "For eligible inpatient occupancy in a shared room, the plan pays at most {ROOM_LIMIT} per service day.",
        ("The cashier's ward price list shows a shared room charge of {old_room} each day.",
         "For comparison, the earlier policy paid up to {other_amount} per day in the shared room.",
         "An attendant may use a shared ward bed at the posted daily price of {old_room}.")),
    RankingCase("overnight-pricing", "policy",
        ("What amount is counted for each night of eligible room occupancy?",
         "How high may the insurer's ordinary accommodation credit go per night?"),
        "The ordinary bed charge counts up to {ROOM_LIMIT} for a covered overnight stay.",
        ("The posted accommodation rate at the facility is {other_amount} for an occupied night.",
         "A worked example assumes an ordinary bed charge of {old_room} per night.",
         "Overnight travel accommodation for the patient's companion is allowed at {other_amount}.")),
    RankingCase("room-revision", "policy",
        ("Which ceiling took effect for rooms under the issued revision?",
         "What daily bed-charge cap is in force for covered patients this term?"),
        "Under this revision the room allowance for an insured inpatient is limited to {ROOM_LIMIT} per day.",
        ("A proposal for the next revision would raise the insured inpatient's daily room allowance to {other_amount}.",
         "The hospital's nightly bed tariff printed beside the revision is {old_room} a day.",
         "An expired revision limited the insured inpatient's daily room allowance to {old_room}.")),
    RankingCase("prior-room-revision", "policy",
        ("How much was permitted for a ward room in the expired policy version?",
         "What inpatient room allowance did the old contract use?"),
        "In the expired policy, reimbursement for an eligible ward room was limited to {old_room} each day.",
        ("The policy now in force limits reimbursement for an eligible ward room to {ROOM_LIMIT} each day.",
         "A future ward room revision proposes a limit of {other_amount} each day.",
         "The old cashier price for a ward bed was {other_amount} each day.")),
    RankingCase("first-inpatient-packet", "claim_form",
        ("Which papers are required in the first request for repayment of inpatient charges?",
         "What evidence goes with the patient's initial hospital payment application?"),
        "On the first inpatient request, submit the item-by-item hospital invoice and the discharge report.",
        ("On appeal, submit the hospital invoice only if charges are disputed and attach the earlier decision.",
         "A parking refund request requires the cashier ticket and proof of payment.",
         "An illustration of a first inpatient request shows a blank hospital invoice.")),
    RankingCase("fixture-versus-document", "claim_form",
        ("What proof needs to accompany this request for hospital expenses?",
         "Which actual enclosures must the applicant send for a hospital refund?"),
        "Enclose the ward exit note and the facility's detailed final bill with the repayment application.",
        ("The workshop exercise describes a repayment application with a referral letter and dummy bill.",
         "The facility can provide optional copies of the ward exit note for your own records.",
         "For staff travel repayment, enclose a shift record and the journey receipts.")),
    RankingCase("compulsory-support", "claim_form",
        ("Which attachments are compulsory when applying to recover the cost of hospital treatment?",
         "What must be in the packet when I ask for payment after the stay?"),
        "The packet is accepted only with the signed release summary and final line-item statement of treatment charges.",
        ("A statement of treatment charges can accompany a different request for a reimbursement advance.",
         "The legacy packet asked for a deposit receipt instead of the signed release summary.",
         "A signed attendance sheet and line-item invoice are compulsory for hospital training expenses.")),
    RankingCase("optional-support", "claim_form",
        ("Which hospital repayment attachment is optional rather than required?",
         "What records may applicants send if requested separately?"),
        "For repayment applicants the medication receipt is requested separately and can be kept with their records.",
        ("A signed ward release summary must be included in the hospital repayment packet.",
         "Send the itemized hospital invoice with every repayment request.",
         "An example invoice appears in a staff training document for the repayment desk.")),
    RankingCase("initial-filing-clock", "claim_form",
        ("Within what period after leaving hospital must an initial claim reach the insurer?",
         "What clock governs the first request to recover inpatient charges?"),
        "Send the initial expense claim within {days} calendar days after leaving inpatient care.",
        ("A claimant has {other_days} days after leaving hospital to amend a claim already received.",
         "The policy once used {other_days} calendar days after releasing the patient for an initial expense claim.",
         "A sample application records a claimant filing {other_days} days after the end of the stay.")),
    RankingCase("first-packet-due", "claim_form",
        ("By when should a fresh inpatient repayment request be filed?",
         "How long from discharge until the deadline for the original hospital expenses packet?"),
        "The completed original packet must reach the claims desk no later than {days} days from discharge.",
        ("Corrections to the packet go to the claims desk no later than {other_days} days after it has been filed.",
         "The reimbursement date in the printed example is {notice_date}; it records a completed request.",
         "The old form set {other_days} days from discharge for the original packet and was withdrawn.")),
    RankingCase("amendment-clock", "claim_form",
        ("How long can a claimant correct an already submitted hospital payment request?",
         "What is the period to file a corrected enclosure after the insurer received the claim?"),
        "An amendment to an inpatient claim must reach the insurer within {days} days of the original filing.",
        ("A new inpatient claim must be submitted within {other_days} days of the inpatient discharge.",
         "The patient's inpatient invoice was processed {other_days} days after the claim reached the insurer.",
         "An appeal may be filed within {other_days} days of a coverage determination.")),
    RankingCase("appeal-clock", "claim_form",
        ("What deadline applies to an appeal after a claim is declined?",
         "How many days does a member have to dispute the determination?"),
        "Lodge the appeal within {days} calendar days after receipt of the determination notice.",
        ("Submit the initial expense claim within {other_days} days from the patient's discharge date.",
         "The determination took {other_days} days to reach the applicant in the worked example.",
         "A correction to the initial submission must be filed within {other_days} days.")),
    RankingCase("accepted-cash-rider", "schedule",
        ("Does the daily inpatient cash rider cover the insured patient on the active schedule?",
         "Which passage grants the named person a cash amount for each day in hospital?"),
        "The rider in force pays daily hospital cash to the insured person {MEMBER_ID} for qualifying admissions.",
        ("A quotation offers the named person daily hospital cash if they accept a future rider.",
         "The previous daily hospital cash rider ended with the former policy on {notice_date}.",
         "A cash allowance is available for the employee's travel to the hospital only.")),
    RankingCase("person-specific-supplement", "schedule",
        ("Does the currently issued hospital cash supplement apply to this certificate holder?",
         "Where is the accepted inpatient allowance for the person on the current certificate?"),
        "A binding supplement adds a daily inpatient cash payment to the benefits of certificate holder {MEMBER_ID}.",
        ("An illustration lists a daily inpatient cash supplement subject to the applicant's signature.",
         "A different insured on the same schedule has the daily inpatient cash allowance.",
         "A retired supplement lists daily inpatient cash for certificate holder {MEMBER_ID}.")),
    RankingCase("pending-cash-rider", "schedule",
        ("What does the pending proposal offer as a hospital-day allowance?",
         "Where is the cash rider shown in the draft renewal papers?"),
        "The proposed renewal would add {ROOM_LIMIT} a day in hospital as an inpatient cash rider.",
        ("The current accepted rider pays a daily inpatient hospital benefit of {old_room}.",
         "The hospital's technician cash allowance is {other_amount} for each work day.",
         "An old proposal for a travel allowance would pay {other_amount} a night.")),
    RankingCase("opening-cover", "schedule",
        ("What is the insured benefit pool at the start of this policy term?",
         "Which amount starts the year's aggregate cover for the named member?"),
        "Under the accepted instrument the named member begins the term with an insured balance of {SUM_INSURED}.",
        ("A renewal quote shows an aggregate cover of {other_amount} and awaits acceptance.",
         "An insured balance of {other_amount} belonged to the previous policy term.",
         "The cashier records an initial premium payment of {other_amount} for the term.")),
    RankingCase("initial-insured-reserve", "schedule",
        ("How large is the binding initial reserve under the replacement schedule?",
         "Which schedule amount is the issued annual benefit balance rather than a payment?"),
        "The issued replacement schedule opens the annual benefit reserve at {SUM_INSURED} for the insured patient.",
        ("The replacement schedule proposal quotes an annual reserve of {other_amount} subject to approval.",
         "The schedule records payment of {other_amount} as a deposit separate from the benefit reserve.",
         "The previous certificate set the annual insured reserve to {other_amount} before replacement.")),
    RankingCase("member-deduction", "policy",
        ("What deduction is due from the patient on this accepted inpatient claim?",
         "Which patient share applies to the payment under the active policy?"),
        "Under this policy the insured patient first pays a deductible of {ROOM_LIMIT} on a qualifying inpatient claim.",
        ("The draft revision proposed a deductible of {old_room} on a qualifying inpatient claim.",
         "The former inpatient policy assigned a deductible of {other_amount} to a qualifying patient.",
         "The hospital's cashier requests a deposit of {other_amount}; it is independent of the patient share under insurance.")),
)


def rank_training_rows():
    rng = Random(20261123)
    rows = []
    for case in CASES:
        family = f"rank-quality-train-{case.name}"
        for index in range(12):
            case_id = f"SYN-RQ-{case.name}-{index + 1:02d}"
            fields = _case_fields(rng, "iso")
            fields["days"], fields["other_days"] = rng.sample(range(7, 91), 2)
            candidates = [(case.answer, True), *((clause, False) for clause in case.distractors)]
            rng.shuffle(candidates)
            for number, (clause, relevant) in enumerate(candidates, start=1):
                passage = clause.format_map(fields)
                if index % 2:
                    passage = f"Section {fields['ref']} — {passage}"
                else:
                    passage = f"{passage} Entry {fields['ref']}."
                rows.append({
                    "id": f"{case_id}-{number}", "case_id": case_id, "family": family,
                    "kind": case.kind, "task": "rank", "synthetic": True,
                    "query": case.queries[index % len(case.queries)], "text": passage, "relevant": relevant,
                })
    return rows
