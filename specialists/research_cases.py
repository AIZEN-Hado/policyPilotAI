"""Authored exact-span and relevance challenges for the first research run."""

from dataclasses import dataclass
import random

from .contracts import SPLITS, TASKS
from .data import _case_fields, _render_document


@dataclass(frozen=True)
class RankingScenario:
    topic: str
    kind: str
    query: str
    answer: str
    distractors: tuple[str, str, str]


# Candidate order is shuffled after assigning labels. All passages in a group
# share a document kind and mention values or evidence for nearby concepts.
RANK_SCENARIOS = {
    "train": (
        RankingScenario(
            "room", "policy", "Which nightly room limit applies to a standard inpatient admission?",
            "Active schedule: for an eligible inpatient night, the insurer recognizes ordinary accommodation charges up to {ROOM_LIMIT}.",
            (
                "The nightly room limit for a standard inpatient admission was {old_room} on the superseded schedule. Use the current schedule.",
                "The nightly room limit of {other_amount} applies to a standard inpatient companion and is payable by the visitor.",
                "Example only: a standard inpatient admission uses a nightly room limit of {other_amount} to illustrate the calculation.",
            ),
        ),
        RankingScenario(
            "evidence", "claim_form", "Which documents must accompany a hospital reimbursement claim under this form?",
            "To lodge request {ref}, enclose the hospital's final itemized invoice and its signed discharge note. Both enclosures are compulsory.",
            (
                "Under form {ref}, documents for hospital reimbursement claims can include optional copies of pharmacy receipts for your own records.",
                "The hospital reimbursement claim checklist for old form {quote} asked for bank statements. That checklist was retired.",
                "Training form {ref} shows which documents must accompany an example hospital reimbursement claim. Its sample task requests a prescription.",
            ),
        ),
        RankingScenario(
            "deadline", "claim_form", "How many days after leaving the hospital can this claim still be filed?",
            "Send the completed inpatient reimbursement packet within {days} calendar days of discharge under this edition of form {ref}.",
            (
                "The {decoy_days}-day clock after leaving the hospital only governs corrections to a claim already filed under {ref}.",
                "An inpatient claim filed {decoy_days} days after leaving the hospital appears here as a completed training example for {ref}.",
                "The old filing deadline was {decoy_days} days after leaving the hospital. That rule was withdrawn when form {ref} took effect.",
            ),
        ),
        RankingScenario(
            "endorsement", "schedule", "Does the additional hospital cash benefit apply to this member's claim?",
            "The cash benefit endorsement is in force for the covered member {MEMBER_ID} under this schedule and applies to eligible admissions.",
            (
                "The additional hospital cash benefit was quoted to this member under renewal illustration {quote}; a quote does not add coverage.",
                "The additional hospital cash benefit applies to the subscriber on schedule {ref}, a different membership from the one making this claim.",
                "The hospital cash benefit applies to the former policy ending on {notice_date}. It was deleted before this member's claim period.",
            ),
        ),
    ),
    "validation": (
        RankingScenario(
            "room", "policy", "What accommodation amount per day is payable for an overnight ward stay?",
            "The operative benefit table recognizes up to {ROOM_LIMIT} per occupied day for the insured patient's bed on the ward.",
            (
                "The accommodation amount payable per day for an overnight ward stay was printed as {old_room} in the prior version, now void.",
                "For an overnight ward stay, the hospital's own accommodation amount is {other_amount} per day. This is its posted tariff.",
                "The amount of {other_amount} payable per day for overnight accommodation applies to bedside attendants charged separately.",
            ),
        ),
        RankingScenario(
            "evidence", "claim_form", "What proof do I have to submit to recover the cost of the admission?",
            "Packet {ref} will be accepted only with the facility's release summary and a line-by-line final bill.",
            (
                "If you are applying to recover the cost of travel to the admission, submit the journey log as proof on attachment {ref}.",
                "The recover-cost guide for admission {ref} suggests proof you can submit later on request, including a payment screenshot.",
                "The example of proof submitted to recover the admission cost under file {quote} includes a referral letter for illustration.",
            ),
        ),
        RankingScenario(
            "deadline", "claim_form", "What is the time limit for submitting a fresh inpatient expense request?",
            "Count {days} calendar days from the patient's departure from the facility. We must receive the initial reimbursement request by then.",
            (
                "The original inpatient expense request is listed on {ref}, but the time limit of {decoy_days} days on this sheet is for appeals.",
                "A previous time limit for submitting a fresh inpatient expense request was {decoy_days} days from departure; it lapsed with {quote}.",
                "This example records an inpatient expense request submitted after {decoy_days} days. It shows a processed file rather than a limit.",
            ),
        ),
        RankingScenario(
            "endorsement", "schedule", "Is the daily hospital cash add-on included for the insured on this schedule?",
            "The in-force benefits list assigns a fixed cash payment per hospital day to insured {MEMBER_ID} under the attached endorsement.",
            (
                "The daily hospital cash add-on is included in the renewal illustration {quote}; the illustration is awaiting acceptance.",
                "The daily hospital cash add-on on schedule {ref} is included for the employee only; this schedule entry is for a separately insured dependent.",
                "A daily hospital cash add-on was included in the same insured's prior schedule, whose term closed on {notice_date}.",
            ),
        ),
    ),
    "test": (
        RankingScenario(
            "room", "policy", "For a covered hospital night, where is the ceiling on the patient's bed charge?",
            "Payment terms for this contract: use {ROOM_LIMIT} for each billable night of an eligible patient's stay in ordinary accommodation.",
            (
                "The ceiling on the patient's bed charge for a covered hospital night is marked {old_room} in the replaced certificate.",
                "The hospital lists a ceiling of {other_amount} on a bed charge per night in its own pricing circular. The contract uses its benefit table.",
                "A hospital night carries a bed charge ceiling of {other_amount} in the calculation worked out below for illustration.",
            ),
        ),
        RankingScenario(
            "evidence", "claim_form", "Which records are prerequisites when seeking repayment for the time spent on the ward?",
            "The insurer will open file {ref} after it receives both the ward's discharge report and the provider's full invoice by service.",
            (
                "For workshop reimbursement, staff seeking repayment for time spent on the ward must attach the participant register to {ref}.",
                "Records for a ward repayment request are shown for sample file {quote}. This example lists a prescription as the sole prerequisite.",
                "When seeking repayment for time spent on the ward, keep a bank transfer confirmation with your records. It is requested only on review.",
            ),
        ),
        RankingScenario(
            "deadline", "claim_form", "By when does a first reimbursement request for this stay have to arrive?",
            "Start on the hospital release date and allow {days} calendar days. Receipt of the first expense claim by the end of that period is required.",
            (
                "The reimbursement request has already arrived for {ref}. You have {decoy_days} days to furnish a corrected attachment.",
                "A previous form required the first reimbursement request to arrive before {decoy_days} days elapsed; that edition is obsolete.",
                "The demonstration file {quote} shows when a first reimbursement request arrived, {decoy_days} days after the stay in this example.",
            ),
        ),
        RankingScenario(
            "endorsement", "schedule", "Does the hospital-day cash allowance cover the person listed on this certificate?",
            "A payment for each qualifying night is an operative addition to the benefits of certificate holder {MEMBER_ID}.",
            (
                "A hospital-day cash allowance for the person listed is offered in the proposal {quote}; its addition awaits approval.",
                "The hospital-day cash allowance on certificate {ref} extends to the primary subscriber. The person listed here is a different insured.",
                "The hospital-day cash allowance covered the person listed before {notice_date}, when a replacement certificate removed it.",
            ),
        ),
    ),
}


SPAN_SCENARIOS = {
    "transfer-ledger": (
        "month-first",
        {
            "claim_form": "Accounts admission abstract / prepared {notice_date}\n"
                "Former contract on file {quote}; contract charged {POLICY_ID}.\n"
                "Person charged {MEMBER_ID}; record locator {ref}.\n"
                "Episode ended {DISCHARGE_DATE} following arrival {ADMISSION_DATE}.",
            "policy": "What we pay for the insured's overnight accommodation\n"
                "The daily tariff is {other_amount}. Payment stops at {ROOM_LIMIT} for each covered night.\n"
                "An earlier version listed {old_room}.",
            "schedule": "Posting account {ref} / print date {notice_date}\n"
                "Declared cover for the term: {SUM_INSURED}. Deposit: {other_amount}.\n"
                "The enrolled beneficiary, {MEMBER_ID}, is insured under contract {POLICY_ID}.",
            "receipt": "Ledger {ref} | printed {notice_date}\n"
                "The office took a deposit of {other_amount} against its estimate of {old_room}.",
        },
    ),
    "ward-circular": (
        "dotted",
        {
            "claim_form": "Movement slip {ref}\n"
                "Issued {notice_date}. Transfer into this ward: {ADMISSION_DATE}.\n"
                "Sent home: {DISCHARGE_DATE}. Attached quote: {quote}.\n"
                "Insured person identity: {MEMBER_ID}; certifying plan: {POLICY_ID}.",
            "policy": "Accommodation charges: the covered sleeper's allowance is capped at {ROOM_LIMIT} per day. "
                "The accompanying visitor pays {old_room} according to the ward's price sheet.",
            "schedule": "Certificate of subscription / {notice_date}\n"
                "Renewal illustration {quote} is included for reference. Binding certificate {POLICY_ID}.\n"
                "Benefit pool available to enrolled person {MEMBER_ID}: {SUM_INSURED}. Fee: {other_amount}.",
            "receipt": "Collection register {ref}\n"
                "Cash received {notice_date}. Hospital price estimate {old_room}. Paid {other_amount}.",
        },
    ),
}


def generate_challenges(seed):
    """Generate fixed-size challenges under the runtime row contract."""
    rng = random.Random(seed)
    corpus = {split: {task: [] for task in TASKS} for split in SPLITS}
    for split, scenarios in RANK_SCENARIOS.items():
        cases_per_topic = 32 if split == "train" else 16
        for scenario in scenarios:
            family = f"research-rank-{split}-{scenario.topic}"
            for number in range(1, cases_per_topic + 1):
                case_id = f"SYN-RV1-{family}-{number:03d}"
                fields = _case_fields(rng, "written")
                fields.update(zip(("days", "decoy_days"), rng.sample(range(10, 91, 5), 2)))
                candidates = [(scenario.answer, True), *((text, False) for text in scenario.distractors)]
                rng.shuffle(candidates)
                for index, (template, relevant) in enumerate(candidates, start=1):
                    corpus[split]["rank"].append({
                        "id": f"{case_id}-{index}",
                        "case_id": case_id,
                        "family": family,
                        "kind": scenario.kind,
                        "task": "rank",
                        "synthetic": True,
                        "query": scenario.query,
                        "text": template.format_map(fields),
                        "relevant": relevant,
                    })

    for name, (date_style, documents) in SPAN_SCENARIOS.items():
        family = f"research-span-test-{name}"
        for number in range(1, 33):
            case_id = f"SYN-RV1-{family}-{number:03d}"
            fields = _case_fields(rng, date_style)
            for kind, template in documents.items():
                text, spans = _render_document(template, fields)
                corpus["test"]["span"].append({
                    "id": f"{case_id}-{kind}",
                    "case_id": case_id,
                    "family": family,
                    "kind": kind,
                    "task": "span",
                    "synthetic": True,
                    "text": text,
                    "spans": spans,
                })
    return corpus
