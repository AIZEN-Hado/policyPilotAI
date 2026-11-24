"""Original English synthetic cases for span extraction and evidence ranking.

Splits use different authored wording and text layouts. They share fictional
benefit concepts and value-generation rules. This corpus has no PDF or OCR
samples and does not measure performance on real claims.
"""

from dataclasses import dataclass
from datetime import date, timedelta
import random
from string import Formatter

from .contracts import Corpus, Row, SPAN_LABELS, SPLITS, TASKS, validate_corpus


DEFAULT_SEED = 20261118
CASES_PER_FAMILY = 32


@dataclass(frozen=True)
class RankPair:
    kind: str
    query: str
    relevant: str
    irrelevant: str


@dataclass(frozen=True)
class Family:
    name: str
    date_style: str
    documents: dict[str, str]
    ranking: tuple[RankPair, ...]


_FAMILIES = {
    "train": (
        Family(
            "cedar-grid",
            "iso",
            {
                "policy": (
                    "CEDAR  |  Benefit limits\n"
                    "Revision date: {notice_date}\n"
                    "Inpatient ward | Maximum room and board per day: {ROOM_LIMIT}\n"
                    "Outpatient recovery chair | Service charge: {other_amount}\n"
                    "The amount in the example from last year is not the current room limit."
                ),
                "schedule": (
                    "COVER SCHEDULE\n"
                    "Policy number  |  {POLICY_ID}\n"
                    "Renewal quote  |  {quote}\n"
                    "Beneficiary identifier  |  {MEMBER_ID}\n"
                    "Base sum insured  |  {SUM_INSURED}\n"
                    "Contribution received  |  {other_amount}"
                ),
                "claim_form": (
                    "HOSPITAL CLAIM FORM\n"
                    "Form reference: {ref}. Filed on: {notice_date}.\n"
                    "Policy number: {POLICY_ID}; member number: {MEMBER_ID}.\n"
                    "Admission date: {ADMISSION_DATE}; date of discharge: {DISCHARGE_DATE}."
                ),
                "discharge": (
                    "Inpatient episode record {ref}\n"
                    "Date of admission: {ADMISSION_DATE}\n"
                    "Date of discharge: {DISCHARGE_DATE}\n"
                    "Record printed: {notice_date}"
                ),
                "bill": (
                    "ITEMIZED INPATIENT BILL {ref}\n"
                    "Posted on: {notice_date}; admission date: {ADMISSION_DATE}.\n"
                    "Ward charge: {other_amount}."
                ),
                "receipt": "RECEIPT {ref}\nReceived on {notice_date} | Deposit payment {other_amount}.",
            },
            (
                RankPair(
                    "policy",
                    "What is the daily inpatient room limit?",
                    "This plan pays room and board for a covered inpatient stay up to {ROOM_LIMIT} per day.",
                    "The daily room limit of {old_room} is charged to visiting clinicians. It does not set the limit for hospital stays.",
                ),
                RankPair(
                    "claim_form",
                    "Which papers must be included with a hospital reimbursement claim?",
                    "For hospital reimbursement, include the itemized bill and the discharge summary. A deposit receipt alone is insufficient.",
                    "Hospital reimbursement workshop {ref} uses a sample discharge summary. Workshop registration requires the attendance sheet.",
                ),
            ),
        ),
        Family(
            "marsh-letter",
            "dmy",
            {
                "policy": (
                    "Marsh health plan circular {ref}\n"
                    "For an accepted admission, we reimburse a standard ward room at up to {ROOM_LIMIT} a night. "
                    "The figure of {old_room} from our illustration applies to private clinic rentals."
                ),
                "schedule": (
                    "Your active cover, effective {notice_date}, is recorded under policy {POLICY_ID}. "
                    "Covered member: {MEMBER_ID}. Your annual insured amount is {SUM_INSURED}. "
                    "Please quote correspondence number {quote} when updating your address."
                ),
                "claim_form": (
                    "Please attach this page to claim {ref}. Member ID {MEMBER_ID} belongs to plan "
                    "{POLICY_ID}. The patient was admitted on {ADMISSION_DATE} and discharged on {DISCHARGE_DATE}. "
                    "We received the form on {notice_date}."
                ),
                "discharge": (
                    "We issued this note on {notice_date} for stay {ref}. The patient went home on {DISCHARGE_DATE}; "
                    "the facility originally recorded their admission on {ADMISSION_DATE}."
                ),
                "bill": "Statement {ref} closes the stay discharged on {DISCHARGE_DATE}. This copy was posted on {notice_date}.",
                "receipt": (
                    "Payment acknowledgement\n"
                    "Terminal {ref} processed {other_amount} on {notice_date}. The bank's statement reference is {quote}."
                ),
            },
            (
                RankPair(
                    "policy",
                    "How much per night may be reimbursed for the ward room during an admission?",
                    "A standard ward room during an accepted admission is reimbursable up to {ROOM_LIMIT} a night.",
                    "The supplier may bill the facility up to {old_room} a night to make a ward room available during renovation.",
                ),
                RankPair(
                    "claim_form",
                    "What paperwork do I send for a refund after my hospital stay?",
                    "Send the discharge letter and a bill with separate charges when applying for a refund after leaving hospital.",
                    "Send a signed refund receipt to the cashier for hospital parking; the reimbursement claim desk uses a different form.",
                ),
            ),
        ),
        Family(
            "copper-sheet",
            "written",
            {
                "policy": (
                    "COPPER PLAN / WARD\n"
                    "Circular issued {notice_date} • Internal reference {ref}\n"
                    "Room allowance during inpatient stay = {ROOM_LIMIT} per occupied day.\n"
                    "Visitor meals = {other_amount} per order."
                ),
                "schedule": (
                    "ENROLMENT STATEMENT\n"
                    "Policy certificate       {POLICY_ID}\n"
                    "Person covered          {MEMBER_ID}\n"
                    "Insured total           {SUM_INSURED}\n"
                    "Quote tracker           {quote}\n"
                    "Run date                {notice_date}"
                ),
                "claim_form": (
                    "ADMISSION REIMBURSEMENT\n"
                    "Enrolment code: {MEMBER_ID} / Cover number: {POLICY_ID}\n"
                    "Hospital entry: {ADMISSION_DATE}\n"
                    "Hospital exit: {DISCHARGE_DATE}\n"
                    "Caseworker stamp: {notice_date} ({ref})"
                ),
                "discharge": (
                    "Ward transfer worksheet {ref}\n"
                    "Record generated\t{notice_date}\n"
                    "Admitted\t{ADMISSION_DATE}\n"
                    "Discharged\t{DISCHARGE_DATE}"
                ),
                "bill": "WARD BILL: {ref}\nInpatient days {ADMISSION_DATE} to {DISCHARGE_DATE}\nPrint date {notice_date}",
                "receipt": "CASH DESK\nReceipt: {ref}\nPaid: {other_amount}\nDate tendered: {notice_date}",
            },
            (
                RankPair(
                    "policy",
                    "What room allowance applies for each occupied day of an inpatient stay?",
                    "Ward benefit — for each occupied inpatient day, room charges are payable up to {ROOM_LIMIT}; visitor meals are excluded.",
                    "Facilities benefit sheet — room allowance per occupied day of inpatient stay: {old_room}. Cost centre: hospital ward maintenance.",
                ),
                RankPair(
                    "claim_form",
                    "What records does the claim desk require for admission reimbursement?",
                    "Admission reimbursement checklist: attach the final itemized charges and the departure summary from the ward.",
                    "Admissions calls are recorded for training. The reimbursement claim desk requires a staff pass to enter the records room.",
                ),
            ),
        ),
        Family(
            "harbor-notice",
            "month-first",
            {
                "policy": (
                    "HARBOR COVER NOTICE {ref}\n"
                    "4(a) A covered hospital admission has a daily room expense ceiling of {ROOM_LIMIT}.\n"
                    "4(b) The facility's administrative transfer charge of {other_amount} is excluded."
                ),
                "schedule": (
                    "Contract {POLICY_ID} has been issued to the covered person bearing membership code {MEMBER_ID}. "
                    "Total cover available under the contract: {SUM_INSURED}. "
                    "File number {quote} is for staff correspondence."
                ),
                "claim_form": (
                    "Cover contract #{POLICY_ID} | Individual card #{MEMBER_ID}\n"
                    "Admission ({ADMISSION_DATE}) arose under this contract. Discharge ({DISCHARGE_DATE}) occurred before "
                    "the form was filed on {notice_date} at intake desk {ref}."
                ),
                "discharge": (
                    "DISCHARGE ABSTRACT\n"
                    "The inpatient episode began on {ADMISSION_DATE} and ended with discharge on {DISCHARGE_DATE}. "
                    "Correction request {ref} was entered {notice_date}."
                ),
                "bill": (
                    "FINAL ACCOUNT\n"
                    "Discharge date: {DISCHARGE_DATE} / Account date: {notice_date}\n"
                    "Billing reference: {ref} / Ward line: {other_amount}"
                ),
                "receipt": "Receipt for state of account {ref}.\nThe cashier collected {other_amount} on {notice_date}.",
            },
            (
                RankPair(
                    "policy",
                    "Does this plan give a ceiling for daily room expenses during admission?",
                    "Daily room charges incurred during a covered hospital admission cannot be reimbursed above {ROOM_LIMIT}.",
                    "The admission office maintains a ceiling of {old_room} per day for the family waiting room. Collections go to the facility.",
                ),
                RankPair(
                    "claim_form",
                    "What items are mandatory with the application for inpatient reimbursement?",
                    "The applicant must lodge both the ward's discharge abstract and the hospital's itemized final account.",
                    "An applicant disputing inpatient reimbursement files a separate appeal. The appeal requires a copy of the determination notice.",
                ),
            ),
        ),
    ),
    "validation": (
        Family(
            "willow-margin",
            "written",
            {
                "policy": (
                    "Willow cover, section F (ward accommodation)\n"
                    "The accommodation component for an eligible inpatient is restricted to {ROOM_LIMIT} for one night. "
                    "Use circular {ref} for guidance on accompanying carer fees."
                ),
                "schedule": (
                    "WILLOW MEMBER RECORD\n"
                    "{MEMBER_ID} — person enrolled under certificate {POLICY_ID}\n"
                    "{SUM_INSURED} — maximum allocation for the policy term\n"
                    "{quote} — reference for the preliminary application"
                ),
                "claim_form": (
                    "Facility {ref} | Covered certificate {POLICY_ID} | Enrolled person {MEMBER_ID}\n"
                    "Dates (in to out)\n"
                    "    {ADMISSION_DATE}\n"
                    "    {DISCHARGE_DATE}\n"
                    "Receipt stamp {notice_date}"
                ),
                "discharge": (
                    "Episode {ref} • Separator sheet\n"
                    "Arrival to ward — {ADMISSION_DATE}. Released from ward — {DISCHARGE_DATE}. "
                    "The record office registered this note {notice_date}."
                ),
                "bill": "Charges account {ref}, generated {notice_date}\n{ADMISSION_DATE}  arrival at ward\n{other_amount}  ward services",
                "receipt": "Collection log\n{notice_date}, transaction {ref}, funds {other_amount}.\nAccount search key {quote}.",
            },
            (
                RankPair(
                    "policy",
                    "How high can the plan's nightly inpatient accommodation payment go?",
                    "For an eligible hospital inpatient, the plan's accommodation payment is restricted to {ROOM_LIMIT} for each night.",
                    "Nightly inpatient accommodation was estimated at {old_room} when the ward ordered furniture. The estimate is for procurement.",
                ),
                RankPair(
                    "claim_form",
                    "Which attachments do members need to lodge for an inpatient refund?",
                    "Lodge the final charges with line details, plus the ward record issued when you left, for the inpatient refund.",
                    "For a refund of unused inpatient meal vouchers, lodge the original vouchers with catering. A charge statement is optional.",
                ),
            ),
        ),
        Family(
            "prairie-ledger",
            "dotted",
            {
                "policy": (
                    "Prairie • Benefit endorsement {ref}\n"
                    "A room used overnight because of inpatient treatment has a payment maximum of {ROOM_LIMIT} for each day. "
                    "The outpatient recovery allowance remains {old_room}."
                ),
                "schedule": (
                    "CURRENT LEDGER\n"
                    "insured amount {SUM_INSURED} / member code {MEMBER_ID}\n"
                    "policy code {POLICY_ID} / ledger entry {quote}\n"
                    "ledger created {notice_date}"
                ),
                "claim_form": (
                    "Voucher {ref}, entered {notice_date}:\n"
                    "Discharge from admission: {DISCHARGE_DATE}\n"
                    "Admission to treatment: {ADMISSION_DATE}\n"
                    "Certificate claimed under: {POLICY_ID} / person: {MEMBER_ID}"
                ),
                "discharge": (
                    "{DISCHARGE_DATE} | leaving inpatient care\n"
                    "{ADMISSION_DATE} | checked into inpatient care\n"
                    "{notice_date} | sheet exported for ledger {ref}"
                ),
                "bill": (
                    "Debits on account {ref}\n"
                    "{other_amount}, inpatient room\n"
                    "{DISCHARGE_DATE}, stay closed by discharge\n"
                    "{notice_date}, entry posted"
                ),
                "receipt": "AMOUNT / ENTRY / DAY\n{other_amount} / {ref} / {notice_date}\nScope: cash received.",
            },
            (
                RankPair(
                    "policy",
                    "What is the payment maximum for a room used overnight in inpatient treatment?",
                    "Payment for a room occupied during an inpatient treatment stay is limited to {ROOM_LIMIT} for each day in the room.",
                    "Payment for linen used in inpatient rooms overnight is capped at {old_room} in the hospital's supplier contract.",
                ),
                RankPair(
                    "claim_form",
                    "What records are necessary when lodging an inpatient payment request?",
                    "Submit the treatment exit record and detailed invoice to request repayment for inpatient charges.",
                    "An inpatient payment request through a staff payroll advance needs a signed manager record. This is an employee loan form.",
                ),
            ),
        ),
    ),
    "test": (
        Family(
            "basalt-card",
            "month-first",
            {
                "policy": (
                    "Basalt terms\n"
                    "Section 7 / Hospital bed\n"
                    "{ROOM_LIMIT} is the most credited for one day of bed occupancy as an inpatient. "
                    "The day clinic tariff of {old_room} is listed in section 8."
                ),
                "schedule": (
                    "Enrolled life [{MEMBER_ID}]\n"
                    "Under insurance certificate [{POLICY_ID}]\n"
                    "Funding ceiling for the period [{SUM_INSURED}]\n"
                    "Unbound estimate [{quote}]  |  Generated [{notice_date}]"
                ),
                "claim_form": (
                    "INPATIENT RECOVERY REQUEST\n"
                    "Charge reference {ref}: admitted {ADMISSION_DATE}.\n"
                    "The discharge took place {DISCHARGE_DATE}.\n"
                    "Insurance file {POLICY_ID}; covered card {MEMBER_ID}; record date {notice_date}."
                ),
                "discharge": (
                    "Discharge note prepared {notice_date}\n"
                    "Episode {ref} was opened by an inpatient admission ({ADMISSION_DATE}). "
                    "The patient was released ({DISCHARGE_DATE})."
                ),
                "bill": "Account {ref} for the episode opened {ADMISSION_DATE}; invoice date {notice_date}; subtotal {other_amount}.",
                "receipt": "Statement stub {ref} [{notice_date}]\nAmount credited toward charges [{other_amount}].",
            },
            (
                RankPair(
                    "policy",
                    "What is the most that can be credited for a day's inpatient bed occupancy?",
                    "The insurer will credit no more than {ROOM_LIMIT} toward bed occupancy for each day of covered hospitalization.",
                    "The ward's asset register credits {old_room} a day for inpatient bed occupancy when calculating equipment depreciation.",
                ),
                RankPair(
                    "claim_form",
                    "What needs to go in the packet to recover inpatient expenses?",
                    "Put the discharge record and the provider's statement of individual charges into the packet for repayment after a hospital stay.",
                    "Put the visitor pass and parking ticket into the inpatient ward cashier's return packet. This recovers the parking deposit.",
                ),
            ),
        ),
        Family(
            "orchard-memo",
            "iso",
            {
                "policy": (
                    "Extract from the Orchard benefit memo\n"
                    "1. On a qualifying hospital admission, reimbursement for the room stops at {ROOM_LIMIT} a day.\n"
                    "2. The estimate dated {notice_date} shows a guest suite fee of {old_room}."
                ),
                "schedule": (
                    "To the enrollee using card {MEMBER_ID}\n\n"
                    "We have placed active coverage against contract {POLICY_ID}. The full insured balance at the start of "
                    "the period is {SUM_INSURED}. Proposal {quote} may be kept for reference."
                ),
                "claim_form": (
                    "Applicant's hospital stay details; claim tracking {ref}\n"
                    "(a) Sought against cover {POLICY_ID}\n"
                    "(b) Card presented {MEMBER_ID}\n"
                    "(c) Arrival as inpatient {ADMISSION_DATE}\n"
                    "(d) Released from hospital {DISCHARGE_DATE}\n"
                    "(e) Signature dated {notice_date}"
                ),
                "discharge": (
                    "Memorandum to accounts for stay {ref}\n"
                    "Release to home occurred on {DISCHARGE_DATE}. Reconcile against entry to inpatient care on {ADMISSION_DATE}. "
                    "Stamp for reconciliation: {notice_date}."
                ),
                "bill": "On {notice_date} we sent account {ref} for the stay ending on discharge {DISCHARGE_DATE}. Ward total {other_amount}.",
                "receipt": "Memo to cashier {ref}\nOn {notice_date} the desk accepted funds of {other_amount}.",
            },
            (
                RankPair(
                    "policy",
                    "At what amount per day does room reimbursement stop for a qualifying admission?",
                    "For a qualifying admission, reimbursement for the patient's room stops at {ROOM_LIMIT} per day.",
                    "For guests attending the admission orientation, room reimbursement stops at {old_room} per day under the employer travel memo.",
                ),
                RankPair(
                    "claim_form",
                    "What proof is mandatory to reclaim the cost of an inpatient stay?",
                    "To reclaim inpatient costs, provide the summary issued on leaving the ward and the final invoice broken down by service.",
                    "To reclaim the cost of travel to an inpatient stay, submit fare tickets and a mileage sheet; this is the transport allowance.",
                ),
            ),
        ),
    ),
}

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_FORMATTER = Formatter()


def _format_date(value: date, style: str) -> str:
    if style == "iso":
        return value.isoformat()
    if style == "dmy":
        return f"{value.day:02d}/{value.month:02d}/{value.year}"
    if style == "dotted":
        return f"{value.day:02d}.{value.month:02d}.{value.year}"
    month = _MONTHS[value.month - 1]
    if style == "written":
        return f"{value.day} {month} {value.year}"
    if style == "month-first":
        return f"{month} {value.day}, {value.year}"
    raise ValueError(f"Unknown date style {style}")


def _case_fields(rng: random.Random, date_style: str) -> dict[str, str]:
    admission = date(2034, 1, 1) + timedelta(days=rng.randrange(1460))
    discharge = admission + timedelta(days=rng.randint(1, 12))
    notice = discharge + timedelta(days=rng.randint(1, 40))
    policy, quote = rng.sample(range(100000, 1000000), 2)
    member, reference = rng.sample(range(100000, 1000000), 2)
    # Distractors sometimes share the field's identifier format. The two room
    # amounts share a range so their size does not identify relevance.
    quote_prefix = rng.choice(("PX", "QX"))
    reference_prefix = rng.choice(("MB", "RX"))
    room, other_room = rng.sample(range(2500, 12001, 250), 2)
    return {
        "POLICY_ID": f"PX-{policy}",
        "MEMBER_ID": f"MB-{member}",
        "ADMISSION_DATE": _format_date(admission, date_style),
        "DISCHARGE_DATE": _format_date(discharge, date_style),
        "ROOM_LIMIT": f"INR {room:,}",
        "SUM_INSURED": f"INR {rng.randrange(150000, 1200001, 25000):,}",
        "notice_date": _format_date(notice, date_style),
        "ref": f"{reference_prefix}-{reference}",
        "quote": f"{quote_prefix}-{quote}",
        "other_amount": f"INR {rng.randrange(300, 14001, 100):,}",
        "old_room": f"INR {other_room:,}",
    }


def _render_document(template: str, fields: dict[str, str]) -> tuple[str, list[dict]]:
    parts = []
    spans = []
    offset = 0
    for literal, field, _, _ in _FORMATTER.parse(template):
        parts.append(literal)
        offset += len(literal)
        if field is not None:
            value = fields[field]
            parts.append(value)
            if field in SPAN_LABELS:
                spans.append({"label": field, "start": offset, "end": offset + len(value), "value": value})
            offset += len(value)
    return "".join(parts), spans


def _case_rows(family: Family, serial: int, rng: random.Random) -> tuple[list[Row], list[Row]]:
    fields = _case_fields(rng, family.date_style)
    case_id = f"SYN-SP-{family.name}-{serial:03d}"
    shared = {"case_id": case_id, "family": family.name, "synthetic": True}
    span_rows = []
    for kind, template in family.documents.items():
        text, spans = _render_document(template, fields)
        span_rows.append({
            **shared,
            "id": f"{case_id}-span-{kind}",
            "task": "span",
            "kind": kind,
            "text": text,
            "spans": spans,
        })

    rank_rows = []
    for group, pair in enumerate(family.ranking, start=1):
        candidates = [(pair.relevant, True), (pair.irrelevant, False)]
        rng.shuffle(candidates)
        for candidate, (template, relevant) in enumerate(candidates, start=1):
            rank_rows.append({
                **shared,
                "id": f"{case_id}-rank-{group}-{candidate}",
                "task": "rank",
                "kind": pair.kind,
                "text": template.format_map(fields),
                "query": pair.query,
                "relevant": relevant,
            })
    return span_rows, rank_rows


def generate_corpus(seed: int = DEFAULT_SEED) -> Corpus:
    """Build deterministic text and labels without reading or writing files."""
    if type(seed) is not int:
        raise ValueError("Corpus seed must be an integer")
    rng = random.Random(seed)
    corpus = {split: {task: [] for task in TASKS} for split in SPLITS}
    for split, families in _FAMILIES.items():
        for family in families:
            for serial in range(1, CASES_PER_FAMILY + 1):
                span_rows, rank_rows = _case_rows(family, serial, rng)
                corpus[split]["span"].extend(span_rows)
                corpus[split]["rank"].extend(rank_rows)
    validate_corpus(corpus)
    return corpus
