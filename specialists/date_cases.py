"""Synthetic training layouts for distinguishing current-stay dates from distractors."""

from datetime import date, timedelta
from random import Random

from .data import _format_date, _render_document


DATE_STYLES = ("iso", "dmy", "dotted", "written", "month-first")
ARRIVAL = ("Ward arrival", "Inpatient entry", "Taken into care", "Bed assignment",
           "Hospital intake", "Received on the ward", "Episode opened", "Admitted as inpatient")
DEPARTURE = ("Departure for home", "Release from care", "Exit from ward", "Stay closed",
             "Allowed to leave", "Final discharge", "Released to residence", "Discharged from inpatient care")
LAYOUTS = (
    ("nursing-grid", "discharge",
     "Unit log {reference}\nPrior stay | {arrival}: {old_admission} | {departure}: {old_discharge}\n"
     "Encounter selected for review | {departure}: {DISCHARGE_DATE} | {arrival}: {ADMISSION_DATE}\n"
     "Administrative print date: {notice}."),
    ("handover-message", "discharge",
     "For follow-up on the current admission, the bedside handoff records {arrival} on {ADMISSION_DATE}. "
     "The completed event is marked {departure} on {DISCHARGE_DATE}. The later call on {notice} was a welfare check."),
    ("approval-calendar", "claim_form",
     "Provisional reservation on {planned} cancelled. Actual occupancy from {ADMISSION_DATE} through "
     "{DISCHARGE_DATE} for encounter {reference}. Reconciliation was requested on {notice}."),
    ("billing-grid", "bill",
     "STATEMENT {reference}\nPosting | {notice}\nCurrent episode / {departure} | {DISCHARGE_DATE}\n"
     "Paid-through date for an earlier stay | {old_discharge}\nCurrent episode / {arrival} | {ADMISSION_DATE}."),
    ("reversal-slip", "claim_form",
     "Use the final inpatient entry {ADMISSION_DATE}. An earlier draft listed {planned} as the admission date "
     "and was withdrawn. The stay ended on {DISCHARGE_DATE}. Authorisation entered on {notice}."),
    ("accounts-letter", "bill",
     "Account {reference} was opened on {notice}. The ward confirms that this inpatient episode began "
     "on {ADMISSION_DATE}. The admission on {old_admission} belongs to a separate invoice."),
    ("discharge-only-note", "discharge",
     "Transport was booked for {planned}. {departure} actually took place on {DISCHARGE_DATE}. "
     "The follow-up desk will call on {notice}."),
    ("suspended-exit", "discharge",
     "Current encounter {reference}. {arrival}: {ADMISSION_DATE}. Planned {departure}: {planned}, "
     "cancelled while care continued. Review filed on {notice}."),
    ("audit-column", "claim_form",
     "AUTHORIZATION TIMELINE [{reference}]\nReview filed -> {notice}\n"
     "Current stay ->\n  {arrival} / {ADMISSION_DATE}\n  {departure} / {DISCHARGE_DATE}\n"
     "Earlier entry for comparison -> {old_admission}."),
    ("insurer-handoff", "claim_form",
     "The earlier encounter closed on {old_discharge}; exclude it from this request. "
     "For the claim under review use this interval: starting at inpatient intake {ADMISSION_DATE}, "
     "ending when the patient left {DISCHARGE_DATE}. The claim was signed on {notice}."),
    ("booking-notice", "receipt",
     "Bed reservation {reference}: planned intake {planned}. A deposit was authorized on {notice}. "
     "The reservation was cancelled before the patient was admitted."),
    ("archived-invoice", "bill",
     "Archived account {reference}. Historical {arrival}: {old_admission}; historical {departure}: "
     "{old_discharge}. Printed again on {notice} for audit. This account covers no current admission."),
)


def date_training_rows():
    rng = Random(20261122)
    rows = []
    for family, kind, template in LAYOUTS:
        for serial in range(1, 33):
            admission = date(2031, 1, 1) + timedelta(days=rng.randrange(3287))
            discharge = admission + timedelta(days=rng.randrange(1, 13))
            old_admission = admission - timedelta(days=rng.randrange(15, 161))
            values = {
                "ADMISSION_DATE": admission,
                "DISCHARGE_DATE": discharge,
                "old_admission": old_admission,
                "old_discharge": old_admission + timedelta(days=rng.randrange(1, 13)),
                "planned": discharge + timedelta(days=rng.randrange(1, 4)),
                "notice": discharge + timedelta(days=rng.randrange(5, 41)),
            }
            style = DATE_STYLES[(serial - 1) % len(DATE_STYLES)]
            fields = {key: _format_date(value, style) for key, value in values.items()}
            if serial % 3 == 0:
                different_style = DATE_STYLES[(serial + 1) % len(DATE_STYLES)]
                fields["DISCHARGE_DATE"] = _format_date(discharge, different_style)
                fields["notice"] = _format_date(values["notice"], different_style)
            fields.update(reference=f"TX-{rng.randrange(100000, 1000000)}",
                          arrival=rng.choice(ARRIVAL), departure=rng.choice(DEPARTURE))
            text, spans = _render_document(template, fields)
            case_id = f"SYN-DATE-{family}-{serial:03d}"
            rows.append({"id": f"{case_id}-span", "case_id": case_id, "family": f"date-{family}",
                         "synthetic": True, "task": "span", "kind": kind, "text": text, "spans": spans})
    return rows
