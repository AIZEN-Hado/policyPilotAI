"""Small development-only stress test for contextual evidence ranking."""


CASES = (
    ("shared-limit", "policy", "Which ceiling binds the insurer for the patient's standard cot under the ratified terms?",
     "For an eligible patient the ratified contract credits 5,600 rupees each night in a standard shared ward.",
     ("The clinic's posted price for the patient's standard cot under the shared tariff is 7,800 rupees.",
      "An unratified proposal raises the insurer's standard cot ceiling to 6,200 rupees.")),
    ("old-ceiling", "policy", "Which daily lodging amount governed before the replacement contract took effect?",
     "For dates preceding the renewal, standard inpatient accommodation was reimbursable up to 4,100 rupees per diem.",
     ("Beginning with the renewal, the replacement contract pays 5,500 rupees for daily lodging.",
      "The administrator's report estimates 4,300 rupees for lodging under a future reimbursement plan.")),
    ("dependent-benefit", "schedule", "Does the approved inpatient cash amount attach to the enrolled child?",
     "For dependent child record K25 the attached signed rider pays 1,000 rupees for every qualifying inpatient day.",
     ("A signed rider pays the primary policyholder 1,000 rupees per inpatient day; the enrolled child is excluded.",
      "The enrolment quotation proposes 1,200 rupees in inpatient cash for the child, subject to approval.")),
    ("replacement-proof", "claim_form", "What paperwork is compulsory when asking a provider to reprint an invoice?",
     "For a replacement provider invoice present the original cashier slip and the hospital account reference.",
     ("For reimbursement attach a provider invoice broken down by service and the inpatient exit statement.",
      "A sample replacement invoice shows an account reference, but the sample is for demonstration.")),
    ("submitted-not-draft", "claim_form", "What time window applies to lodging the first request after departure?",
     "The initial reimbursement packet must reach the intake desk within twenty-one days of release.",
     ("An initial packet was delivered twenty-one days after departure. The log records arrival only.",
      "A draft grants thirty days after departure for the first request. It has never taken effect.")),
    ("wrong-kind-of-deadline", "claim_form", "Which clock governs a reply when the insurer asks for a clearer attachment?",
     "After the notice requests a replacement attachment, send the readable replacement within eight business days.",
     ("After hospital release, file the first reimbursement request within twenty days.",
      "An appeal of the final decision is due within eight business days of denial.")),
    ("allowance-not-deposit", "schedule", "Which opening amount belongs to the active insurance benefit balance?",
     "On the activation date the confirmed benefit pool starts with 360,000 rupees of protection.",
     ("On activation the enrolled person paid a refundable deposit. The deposit is listed separately.",
      "The discarded illustration describes an opening benefit balance of 380,000 rupees.")),
    ("binding-exclusion", "policy", "Which clause determines whether caregiver meals can be reimbursed?",
     "Under the binding contract, meals supplied to accompanying caregivers are excluded from payment.",
     ("The hospital lists caregiver meals as payable items on its patient bill.",
      "The proposed amendment would reimburse caregiver meals if a subsequent approval is issued.")),
)


def rank_probe_rows():
    rows = []
    for name, kind, query, relevant, distractors in CASES:
        case = f"dev-probe-{name}"
        for index, (passage, label) in enumerate(((relevant, True), *((text, False) for text in distractors))):
            rows.append({"id": f"{case}-{index}", "case_id": case, "family": "development-context-probe",
                         "kind": kind, "task": "rank", "synthetic": True, "query": query,
                         "text": passage, "relevant": label})
    return rows
