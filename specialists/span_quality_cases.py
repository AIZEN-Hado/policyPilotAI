"""Additional synthetic field contexts for specialist training."""

from random import Random

from .data import _case_fields, _render_document


LAYOUTS = (
    ("reissued-certificate", "schedule",
     "Reissue register {ref}\nSuperseded contract {prior_cover} | certificate now in force {POLICY_ID}\n"
     "Prior card {prior_person} | enrolled person on this revision {MEMBER_ID}\n"
     "Opening cover available for the new period {SUM_INSURED} | quoted renewal amount {other_amount}."),
    ("room-benefit-comparison", "policy",
     "Visitor lodging tariff {other_amount} per night. A retired standard ward rate was {old_room}.\n"
     "For current eligible inpatient stays, the room expense payable cannot exceed {ROOM_LIMIT} per day."),
    ("revision-charges-table", "policy",
     "BENEFITS IN FORCE | APPROVED PAYABLE MAXIMA\n"
     "Standard ward accommodation (per night) | {ROOM_LIMIT}\n"
     "Total declared insured protection | {SUM_INSURED}\n"
     "Administrative levy and excluded services | {other_amount}."),
    ("person-match-note", "claim_form",
     "Please charge this episode to instrument {POLICY_ID}. For correspondence use {quote}. "
     "At intake the patient produced card {MEMBER_ID}; visitor details record {prior_person}. "
     "The patient took a ward bed on {ADMISSION_DATE}."),
    ("encounter-chronology", "discharge",
     "Reconciliation note printed {notice_date}. File this against {POLICY_ID}.\n"
     "Completed transfer out of this inpatient ward on {DISCHARGE_DATE}; "
     "the inpatient stay began on {ADMISSION_DATE}. A planned booking appears in the archive."),
    ("new-annual-reserve", "schedule",
     "Activated enrolment on plan record {POLICY_ID} for person token {MEMBER_ID}.\n"
     "The current annual reserve starts at {SUM_INSURED}. Illustrated future reserve: {other_amount}.\n"
     "For each eligible night the ward cost allowance on this cover is {ROOM_LIMIT}."),
    ("reverse-column-schedule", "schedule",
     "{other_amount} | previous allowance illustration\n"
     "{SUM_INSURED} | sum established for the current insurance term\n"
     "{MEMBER_ID} | member key validated\n"
     "{POLICY_ID} | payer coverage key recorded."),
    ("bed-management-record", "discharge",
     "{notice_date} | administration copied the unit record\n"
     "{DISCHARGE_DATE} | inpatient episode ended; patient left the unit\n"
     "{ADMISSION_DATE} | inpatient episode started; bed was occupied\n"
     "{ref} | clerical reference."),
    ("claim-window-summary", "claim_form",
     "Subject: inpatient expenses for the interval {ADMISSION_DATE} to {DISCHARGE_DATE}. "
     "The expense request arrived later on {notice_date}. Apply it to member {MEMBER_ID} "
     "under plan agreement {POLICY_ID}, separate from prior agreement {prior_cover}."),
    ("diagnostic-amounts-only", "bill",
     "Charges checked on {notice_date}. Deposit collected {other_amount}. "
     "Room fee displayed at {old_room} nightly in the facility price list. "
     "The account records charges only; payable policy benefits are shown separately."),
    ("cancelled-enrolment-receipt", "receipt",
     "Payment receipt {ref}, recorded {notice_date}. Proposal {prior_cover} was withdrawn "
     "before acceptance. The amount {other_amount} is a refundable application fee."),
    ("instrument-register", "policy",
     "File {quote} is supporting correspondence. Use payer agreement {POLICY_ID} for the listed terms. "
     "Covered room costs draw at most {ROOM_LIMIT} per complete inpatient day. "
     "A typical cash charge is {other_amount}."),
    ("verified-stay-invoice", "bill",
     "Bill sent on {notice_date}. Authorised member key {MEMBER_ID}; billing account {ref}.\n"
     "The patient was first received into inpatient care on {ADMISSION_DATE}. "
     "Final release took place on {DISCHARGE_DATE}. Only these events belong to this account."),
    ("reserve-correction-addendum", "schedule",
     "CORRECTION FOR ACTIVE INSURANCE TERM\n"
     "Discard draft reserve {other_amount}; this term is insured for {SUM_INSURED}. "
     "The old contract entry {prior_cover} is retained for audit. Current authority: {POLICY_ID}."),
    ("care-notice-entry-only", "claim_form",
     "Status completed on {notice_date} for current claim {ref}. "
     "Received into the inpatient service on {ADMISSION_DATE}. "
     "The patient remains admitted and the release time has yet to be confirmed."),
    ("transfer-date-exit-only", "discharge",
     "County records dispatched this document on {notice_date}. "
     "The current ward episode terminated on {DISCHARGE_DATE}, when the person left for home. "
     "The entry information is on a separate sheet."),
)
DATE_STYLES = ("iso", "dmy", "dotted", "written", "month-first")


def span_training_rows():
    rng = Random(20261123)
    rows = []
    for key, kind, template in LAYOUTS:
        for index in range(32):
            fields = _case_fields(rng, DATE_STYLES[index % len(DATE_STYLES)])
            fields["prior_cover"] = f"PC-{rng.randrange(100000, 1000000)}"
            fields["prior_person"] = f"MR-{rng.randrange(100000, 1000000)}"
            if index % 4 == 0:
                for name in ("POLICY_ID", "MEMBER_ID", "prior_cover", "prior_person"):
                    fields[name] = "REG/" + fields[name].partition("-")[2]
            if index % 4 == 1:
                for name in ("ROOM_LIMIT", "SUM_INSURED", "other_amount", "old_room"):
                    fields[name] = fields[name].replace("INR ", "₹ ")
            text, spans = _render_document(template, fields)
            case_id = f"SYN-SPECIALIST-{key}-{index + 1:03d}"
            rows.append({"id": f"{case_id}-span", "case_id": case_id, "family": f"span-quality-{key}",
                         "synthetic": True, "task": "span", "kind": kind, "text": text, "spans": spans})
    return rows
