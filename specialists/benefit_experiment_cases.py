"""Fictional benefit amounts, close evidence distractors, and separate wording families."""

from dataclasses import dataclass
from random import Random

from .data import _case_fields, _render_document


SPAN_LAYOUTS = {
    "train": (
        ("policy", "Overall plan maximum for all payable losses {SUM_INSURED}; ward benefit maximum each night {ROOM_LIMIT}. "
         "Quote before issuance {old_sum}. Hospital cash price {old_room}."),
        ("schedule", "{SUM_INSURED} | total amount assured for this term\n{ROOM_LIMIT} | payable limit on ordinary nightly lodging\n"
         "{old_sum} | previous term aggregate\n{other_amount} | facility fee"),
        ("policy", "A prior room allowance of {old_room} was withdrawn. Approved schedule: daily bed reimbursement {ROOM_LIMIT}. "
         "The insured amount for all claims combined is {SUM_INSURED}."),
        ("schedule", "Amount insured under the active policy is {SUM_INSURED}. Prior draft proposed {old_sum}. "
         "The printed ward tariff is {old_room}. This schedule specifies no insurer room allowance."),
        ("bill", "Ward room fee for the night {old_room}. This is the provider's own retail charge. "
         "Payment on account {other_amount}. Draft insured amount {old_sum} has no contractual effect."),
        ("policy", "The benefit table allows up to {ROOM_LIMIT} toward each approved bed night. "
         "An illustration assumes a total of {old_sum}. Consult the separate certificate for aggregate protection."),
        ("claim_form", "Payer record {POLICY_ID}; covered-person number {MEMBER_ID}. Entered inpatient care {ADMISSION_DATE}. "
         "Actual release {DISCHARGE_DATE}; note printed {notice_date}. Aggregate insured benefit {SUM_INSURED}. "
         "Per-night eligible room allowance {ROOM_LIMIT}. Contract quote {quote}; cash tariff {old_room}."),
        ("schedule", "Enrolled person {MEMBER_ID} on certificate {POLICY_ID}. Draft member code {ref}. "
         "This certificate is written with total coverage of {SUM_INSURED}. "
         "For each ordinary room day the insured may recover no more than {ROOM_LIMIT}."),
        ("receipt", "Receipt for proposed policy {quote}; administration entry {ref}. "
         "Deposit received {other_amount}. The suggested ward maximum {old_room} has not been adopted."),
        ("policy", "Per person, {SUM_INSURED} is the maximum insurer exposure over the full term. "
         "Per night, {ROOM_LIMIT} is the covered amount for standard accommodation. Cost charged at check-in {old_room}."),
    ),
    "validation": (
        ("schedule", "The active certificate sets the full insured total at {SUM_INSURED}. The standard inpatient bed's approved reimbursable "
         "rate cannot exceed {ROOM_LIMIT} overnight. Charges shown on the operator's sheet equal {old_room}."),
        ("policy", "Originally quoted {old_sum}; issued coverage for the year {SUM_INSURED}. "
         "An inpatient accommodation estimate of {old_room} is printed for convenience only."),
        ("bill", "An outstanding accommodation invoice of {old_room} reflects a hospital tariff. "
         "The reserve of {old_sum} belongs to an expired proposal. Advance amount posted {other_amount}."),
        ("claim_form", "Applicable agreement {POLICY_ID}, insured enrollee {MEMBER_ID}; intake {ADMISSION_DATE}, end of stay {DISCHARGE_DATE}. "
         "Insurer's lodging ceiling for an approved day {ROOM_LIMIT}; entire term benefit ceiling {SUM_INSURED}."),
    ),
    "test": (
        ("claim_form", "The admitted-care interval began {ADMISSION_DATE} and finished with return home {DISCHARGE_DATE}. "
         "Billing index {quote}. Insurance instrument {POLICY_ID} covers person roster entry {MEMBER_ID}. "
         "Plan-wide liability limit {SUM_INSURED}; allowed spending on one qualifying ward night {ROOM_LIMIT}."),
        ("schedule", "{old_sum} : withdrawn reserve projection\n{SUM_INSURED} : starting benefit balance in the signed insurance schedule\n"
         "{old_room} : posted accommodation tariff\n{ROOM_LIMIT} : allowable room charge for a covered inpatient night"),
        ("policy", "Use approved coverage record {POLICY_ID}; locate the insured under personal token {MEMBER_ID}. "
         "Total liability for this enrollment cannot exceed {SUM_INSURED}. A potential overnight maximum of {old_room} "
         "appears in the rejected proposal."),
        ("discharge", "The ward handed the patient over for admitted treatment on {ADMISSION_DATE}; home transfer took place on {DISCHARGE_DATE}. "
         "Document produced {notice_date}. The operative insurance reference is {POLICY_ID}, for eligible registrant {MEMBER_ID}."),
        ("policy", "Listed visitor overnight price {old_room}. For the insured's eligible daily ward stay this policy contributes no more than "
         "{ROOM_LIMIT}. Cash deposit {other_amount}; retrieve the separate term certificate for the insured total."),
        ("bill", "The fee ledger records private-room nights billed at {old_room} and a booking prepayment of {other_amount}. "
         "The annex reproduces a lapsed estimate of {old_sum}. No payable insurance benefit appears here."),
        ("schedule", "Ward day payable maximum {ROOM_LIMIT} follows clause 11. Clause 12 limits all reimbursement combined to {SUM_INSURED}. "
         "The previous ledger combined reimbursement with facility registration of {other_amount}. Applies to plan {POLICY_ID} and insured party {MEMBER_ID}."),
        ("claim_form", "Current stay | {DISCHARGE_DATE} final release | {ADMISSION_DATE} first treatment as an inpatient\n"
         "Covered individual {MEMBER_ID} | governing cover {POLICY_ID} | tracking reference {ref}. The benefit register was stamped {notice_date}."),
    ),
}


@dataclass(frozen=True)
class EvidenceSet:
    kind: str
    questions: tuple[str, str]
    clauses: tuple[str, str, str]


RANK_LAYOUTS = {
    "train": (
        EvidenceSet("policy", ("Which ward-night amount is binding today?", "What bed-night amount applied in the replaced version?"),
                    ("Effective today: ordinary ward reimbursement per night is limited to {ROOM_LIMIT}.",
                     "The superseded policy paid at most {old_room} for each ordinary ward night.",
                     "The hospital cashier quotes an ordinary ward price of {other_amount} per night.")),
        EvidenceSet("schedule", ("Locate the issued total coverage for the term.", "Locate the amount in the pending aggregate-cover proposal."),
                    ("The issued aggregate cover for the full policy term is {SUM_INSURED}.",
                     "The aggregate cover pending signature in the proposal is {old_sum}.",
                     "The deposit credited against this term is {other_amount}.")),
        EvidenceSet("claim_form", ("When is the first request due after inpatient release?", "When must a claimant amend a request already filed?"),
                    ("Send the original inpatient expense request no later than {days} days after discharge.",
                     "Correct an already filed inpatient request within {other_days} days of its receipt.",
                     "A worked example shows the insurer paid inpatient expenses after {third_days} days.")),
        EvidenceSet("claim_form", ("Which hospital expense attachments are mandatory for the initial request?", "Which medical document is only needed on request after filing?"),
                    ("The first inpatient reimbursement packet must include an itemized hospital bill and signed discharge summary.",
                     "A medication receipt is requested separately if the insurer asks to verify an already filed claim.",
                     "For hospital staff training reimbursement, an attendance slip is required.")),
        EvidenceSet("schedule", ("Which hospital-day benefit pays the insured person today?", "Which hospital-day benefit did the retired arrangement pay the insured person?"),
                    ("The effective rider pays daily inpatient cash of {ROOM_LIMIT} to enrolled member {MEMBER_ID}.",
                     "The withdrawn rider offered daily inpatient cash of {old_room} to enrolled member {MEMBER_ID}.",
                     "An attendant's travel credit amounts to {other_amount} for each hospital day.")),
        EvidenceSet("policy", ("What deductible applies in the active contract?", "What deductible appeared in the draft contract?"),
                    ("The contract in force sets the insured's inpatient deductible at {ROOM_LIMIT}.",
                     "The unsigned contract draft suggested an inpatient deductible of {old_room}.",
                     "The facility collects an inpatient bed deposit of {other_amount} upon registration.")),
    ),
    "validation": (
        EvidenceSet("policy", ("Find the approved room cap under the signed wording.", "Under the expired wording, how much room cost was payable daily?"),
                    ("The accepted benefit schedule pays no more than {ROOM_LIMIT} per eligible room day.",
                     "The expired benefit wording had covered daily room charges up to {old_room}.",
                     "The printed private room rate for cash customers is {other_amount} per day.")),
        EvidenceSet("claim_form", ("When does the original inpatient claim need to arrive?", "Which clock applies to contesting a decision?"),
                    ("The first reimbursement packet must reach intake within {days} days of leaving hospital.",
                     "To dispute a determination submit an appeal within {other_days} days of notice.",
                     "A sample shows a claim packet arriving after {third_days} days.")),
    ),
    "test": (
        EvidenceSet("policy", ("Which section sets today's maximum payable amount for an occupied hospital room?", "How high was the reimbursable room charge before this week's change?"),
                    ("Under the binding change, accommodation for a covered inpatient may be reimbursed up to {ROOM_LIMIT} per night.",
                     "Before the change took effect, the outgoing policy set the same nightly inpatient benefit at {old_room}.",
                     "In an example the hospital used an accommodation charge of {other_amount} per night.")),
        EvidenceSet("schedule", ("Where is the full insured liability on the executed certificate?", "How much would the unsigned illustration provide for the entire term?"),
                    ("The signed certificate establishes total benefit liability of {SUM_INSURED} for the insured period.",
                     "The unsigned illustration puts total benefit liability for the insured period at {old_sum}.",
                     "Term collection for enrollment was {other_amount} per subscriber.")),
        EvidenceSet("claim_form", ("What period starts when the patient leaves for a first-time claim?", "How long may the insured wait to seek review of the adjudication?"),
                    ("For the first claim seeking inpatient repayment, file within {days} calendar days measured from hospital departure.",
                     "A member has {other_days} calendar days after delivery of the coverage determination to ask for review.",
                     "Under the withdrawn rules, a new application was due {third_days} calendar days from departure.")),
        EvidenceSet("claim_form", ("What has to accompany the first hospital reimbursement packet?", "What enclosure is requested for an amended inpatient claim?"),
                    ("Send the final facility account with separate charges and the ward release report with an original repayment application.",
                     "If amending an inpatient repayment application already received, attach the original determination and the corrected bill.",
                     "In the teaching file, the original reimbursement application was illustrated with a transfer note.")),
        EvidenceSet("schedule", ("Who receives the active per-day inpatient cash rider?", "Who was the beneficiary of inpatient cash before the replacement?"),
                    ("The new inpatient cash supplement under signed terms awards the occupied-day amount to the named dependent {MEMBER_ID}.",
                     "The retired inpatient cash supplement restricted the occupied-day amount to primary subscriber {ref}.",
                     "A pending offer extends an occupied-day cash amount to the attending caregiver.")),
        EvidenceSet("policy", ("Locate the cost share payable by the insured in the issued policy.", "Locate the deduction proposed before binding."),
                    ("For a qualifying hospital treatment the insured must first pay the applicable excess of {ROOM_LIMIT} under the issued policy.",
                     "The proposal pending review contemplated a patient excess of {old_room} on hospital treatment.",
                     "For qualifying treatment the hospital estimated an enrollment deposit of {other_amount}.")),
    ),
}


def _fields(rng, index):
    styles = ("iso", "dmy", "dotted", "written", "month-first")
    fields = _case_fields(rng, styles[index % len(styles)])
    currency = ("INR ", "₹ ", "Rs. ")[index % 3]
    for key in ("SUM_INSURED", "ROOM_LIMIT", "other_amount", "old_room"):
        fields[key] = fields[key].replace("INR ", currency, 1)
    fields["old_sum"] = f"{currency}{rng.randrange(125000, 1200001, 25000):,}"
    fields["days"], fields["other_days"], fields["third_days"] = rng.sample(range(5, 92), 3)
    return fields


def _case(split, task, layout, index):
    family = f"benefit-evidence-{split}-{task}-{layout:02d}"
    return {"case_id": f"{family}-{index:02d}", "family": family, "task": task, "synthetic": True}


def benefit_rows():
    output = {}
    for split, count, seed in (("train", 48, 20261201), ("validation", 24, 20261202), ("test", 24, 20261203)):
        rng = Random(seed)
        output[split] = {"span": [], "rank": []}
        for layout, (kind, template) in enumerate(SPAN_LAYOUTS[split]):
            for index in range(count):
                row = _case(split, "span", layout, index)
                text, spans = _render_document(template, _fields(rng, index))
                output[split]["span"].append({**row, "id": row["case_id"], "kind": kind,
                                               "text": text, "spans": spans})
        for layout, evidence in enumerate(RANK_LAYOUTS[split]):
            seen_passages = set()
            for index in range(count):
                row = _case(split, "rank", layout, index)
                fields = _fields(rng, index)
                passages = tuple(clause.format_map(fields) for clause in evidence.clauses)
                if passages in seen_passages:
                    continue
                seen_passages.add(passages)
                for target, question in enumerate(evidence.questions):
                    order = rng.sample(range(len(passages)), len(passages))
                    for passage in order:
                        output[split]["rank"].append({**row, "id": f"{row['case_id']}-{target}-{passage}",
                            "kind": evidence.kind, "text": passages[passage], "query": question,
                            "relevant": target == passage})
    return output
