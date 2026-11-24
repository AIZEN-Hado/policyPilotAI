"""Extract explicitly labeled claim fields with page-level evidence."""

from datetime import date
from decimal import Decimal
import re

from .extract import ExtractionError

_ID = r"(?=[A-Za-z0-9/-]{1,40}[ \t]*(?:$|[.;|]))(?=[A-Za-z/-]*[0-9])[A-Za-z0-9]+(?:[-/][A-Za-z0-9]+)*"
_PAIRED_ID = r"(?=[A-Za-z0-9-]{1,40}(?![A-Za-z0-9-]))(?=[A-Za-z-]*[0-9])[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*"
_DATE = (r"[0-9]{4}[-/][0-9]{1,2}[-/][0-9]{1,2}"
         r"|[0-9]{1,2}[-/][0-9]{1,2}[-/][0-9]{4}"
         r"|[0-9]{1,2}[ \t]+[A-Za-z]{3,9}[ \t]+[0-9]{4}"
         r"|[A-Za-z]{3,9}[ \t]+[0-9]{1,2},?[ \t]+[0-9]{4}")
_MONEY = (r"(?:INR[ \t]+|Rs\.?[ \t]+|₹[ \t]*)"
          r"(?:[0-9]{1,3}(?:,[0-9]{3}){1,5}|[0-9]{1,2}(?:,[0-9]{2}){0,6},[0-9]{3}|[0-9]{1,18})"
          r"(?:\.[0-9]{1,2})?")
_FIELD_END = r"(?=[ \t]*(?:$|;|\||\.(?![0-9])|/(?:day|night)\b|per[ \t]+(?:day|night)\b))"
_MAX_FIELD_CANDIDATES = 250
_MONTHS = dict(enumerate(
    "january february march april may june july august september october november december".split(), 1
))
_MONTH_NUMBER = {alias: number for number, month in _MONTHS.items() for alias in (month, month[:3])}

_ID_DOCS = {"policy", "schedule", "claim_form", "discharge", "bill"}
_DATE_DOCS = {"claim_form", "discharge", "bill"}
_BENEFIT_DOCS = {"policy", "schedule", "endorsement"}


def _labeled(labels, value):
    # Anchor to a field boundary and keep the match on one extracted line.
    return re.compile(
        rf"(?:^|;)[ \t]*(?:{labels})(?:[ \t]*[:=|#][ \t]*|[ \t]+)"
        rf"(?P<value>{value}){_FIELD_END}",
        re.IGNORECASE | re.MULTILINE,
    )


_RULES = {
    "POLICY_ID": (_ID_DOCS, _labeled(r"policy (?:number|no\.?|id|identifier|certificate)|cover number", _ID)),
    "MEMBER_ID": (_ID_DOCS, _labeled(r"(?:member|beneficiary) (?:number|no\.?|id|identifier)", _ID)),
    "ADMISSION_DATE": (_DATE_DOCS, _labeled(r"admission(?: date)?|date of admission|admitted|hospital entry", _DATE)),
    "DISCHARGE_DATE": (_DATE_DOCS, _labeled(r"discharge(?: date)?|date of discharge|discharged|hospital exit", _DATE)),
    "ROOM_LIMIT": (_BENEFIT_DOCS, _labeled(
        r"(?:daily )?room (?:rent )?(?:limit|cap)|maximum room and board per day"
        r"|room allowance during inpatient stay", _MONEY)),
    "SUM_INSURED": (_BENEFIT_DOCS, _labeled(r"(?:base )?sum insured|insured total", _MONEY)),
}
_MEMBER_AND_POLICY = re.compile(
    rf"^[ \t]*member[ \t]*/[ \t]*policy[ \t]*:[ \t]*"
    rf"(?P<MEMBER_ID>{_PAIRED_ID})[ \t]*/[ \t]*(?P<POLICY_ID>{_PAIRED_ID})[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)
_SCHEDULE_ROOM_CAP = _labeled(r"room benefit[ \t]*:[^;\n]{1,120};[ \t]*daily cap", _MONEY)
_ENDORSED_ROOM_LIMIT = re.compile(
    rf"^[ \t]*(?:the[ \t]+)?daily room limit is (?:increased|decreased|changed) from[ \t]+"
    rf"{_MONEY}[ \t]+to[ \t]+(?P<value>{_MONEY})"
    rf"(?:{_FIELD_END}|(?=[ \t]+for[ \t]+policy\b))",
    re.IGNORECASE | re.MULTILINE,
)


def _date_value(text):
    parts = re.split(r"[-/, \t]+", text.casefold())
    first, middle, last = parts
    if len(first) == 4 and first.isdigit():
        year, month, day = map(int, parts)
    elif middle in _MONTH_NUMBER:
        day, month, year = int(first), _MONTH_NUMBER[middle], int(last)
    elif first in _MONTH_NUMBER:
        month, day, year = _MONTH_NUMBER[first], int(middle), int(last)
    elif first.isdigit() and middle.isdigit():
        a, b, year = map(int, parts)
        if a <= 12 and b <= 12 and a != b:
            return None, "ambiguous_numeric_date"
        month, day = (a, b) if b > 12 else (b, a)
    else:
        return None, "unrecognized_date"
    try:
        return date(year, month, day).isoformat(), None
    except ValueError:
        return None, "invalid_calendar_date"


def _candidate(doc, page, label, start, end):
    text = page["text"][start:end]
    reasons = list(page.get("quality_reasons", []))
    if page.get("needs_verification") or page.get("method") == "ocr":
        reasons.append("check_against_original")
    if doc["kind"] == "endorsement":
        reasons.append("endorsement_applicability_unverified")
    if label.endswith("_DATE"):
        value, error = _date_value(text)
        if error:
            reasons.append(error)
    elif label in {"ROOM_LIMIT", "SUM_INSURED"}:
        digits = re.sub(r"^(?:INR|Rs\.?|₹)[ \t]*", "", text, flags=re.IGNORECASE).replace(",", "")
        value = format(Decimal(digits), ".2f")
    else:
        value = text.upper()
    return {
        "value": value, "source_text": text,
        "document_id": str(doc["id"]), "filename": doc["filename"], "page": page["page"],
        "start_offset": start, "end_offset": end,
        "review_reasons": reasons,
    }


def extract_review_fields(documents):
    """Return sourced candidates and resolution statuses, without deciding coverage."""
    candidates = {label: [] for label in _RULES}

    def append(doc, page, label, span):
        items = candidates[label]
        if len(items) >= _MAX_FIELD_CANDIDATES:
            raise ExtractionError("Too many repeated field values. Review a smaller set of PDFs.")
        items.append(_candidate(doc, page, label, *span))

    for doc in documents:
        for page in doc["pages"]:
            for label, (kinds, pattern) in _RULES.items():
                if doc["kind"] in kinds:
                    for match in pattern.finditer(page["text"]):
                        append(doc, page, label, match.span("value"))
            if doc["kind"] in _ID_DOCS:
                for match in _MEMBER_AND_POLICY.finditer(page["text"]):
                    for label in ("MEMBER_ID", "POLICY_ID"):
                        append(doc, page, label, match.span(label))
            if doc["kind"] == "schedule":
                for match in _SCHEDULE_ROOM_CAP.finditer(page["text"]):
                    append(doc, page, "ROOM_LIMIT", match.span("value"))
            elif doc["kind"] == "endorsement":
                for match in _ENDORSED_ROOM_LIMIT.finditer(page["text"]):
                    append(doc, page, "ROOM_LIMIT", match.span("value"))

    fields = {}
    for label, items in candidates.items():
        values = {item["value"] for item in items if item["value"] is not None}
        status = "missing"
        if len(values) > 1:
            status = "conflicting"
        elif items:
            status = "needs_verification" if any(item["review_reasons"] for item in items) else "found"
        fields[label] = {
            "status": status,
            "value": next(iter(values)) if status == "found" else None,
            "candidates": items,
        }

    issues = []
    admission, discharge = fields["ADMISSION_DATE"], fields["DISCHARGE_DATE"]
    if admission["value"] and discharge["value"] and discharge["value"] < admission["value"]:
        issues.append("discharge_before_admission")
        for field in (admission, discharge):
            field.update(status="needs_verification", value=None)
    return {"fields": fields, "issues": issues}
