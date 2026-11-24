"""Contracts shared by synthetic data preparation and specialist training."""

from collections import defaultdict
import re
from typing import Any


SPAN_LABELS = (
    "POLICY_ID",
    "MEMBER_ID",
    "ADMISSION_DATE",
    "DISCHARGE_DATE",
    "ROOM_LIMIT",
    "SUM_INSURED",
)
DOCUMENT_KINDS = ("policy", "schedule", "claim_form", "discharge", "bill", "receipt")
SPLITS = ("train", "validation", "test")
TASKS = ("span", "rank")
TOKEN_PATTERN = re.compile(r"\w+|[^\w\s]")

Row = dict[str, Any]
Corpus = dict[str, dict[str, list[Row]]]

_ROW_FIELDS = {"id", "case_id", "family", "synthetic", "task", "kind", "text"}
_TASK_FIELDS = {"span": {"spans"}, "rank": {"query", "relevant"}}
_SPAN_FIELDS = {"label", "start", "end", "value"}


def validate_row(row: object) -> None:
    """Raise ValueError if a row cannot be used by the specialist pipeline."""
    if not isinstance(row, dict):
        raise ValueError("Row must be an object")
    task = row.get("task")
    if task not in TASKS:
        raise ValueError("Row has an unknown task")
    if row.keys() != _ROW_FIELDS | _TASK_FIELDS[task]:
        raise ValueError(f"Invalid fields for {task} row")
    if row["synthetic"] is not True:
        raise ValueError("Row must be marked synthetic")
    for field in ("id", "case_id", "family", "text"):
        if not isinstance(row[field], str) or not row[field].strip():
            raise ValueError(f"Row {field} must be a nonempty string")
    if row["kind"] not in DOCUMENT_KINDS:
        raise ValueError("Row has an unknown document kind")
    if any(label in row["text"] for label in SPAN_LABELS):
        raise ValueError("Row text contains an annotation label")
    if task == "rank":
        if not isinstance(row["query"], str) or not row["query"].strip():
            raise ValueError("Rank query must be a nonempty string")
        if type(row["relevant"]) is not bool:
            raise ValueError("Rank relevance must be an explicit boolean")
        if any(label in row["query"] for label in SPAN_LABELS):
            raise ValueError("Rank query contains an annotation label")
        return

    spans = row["spans"]
    if not isinstance(spans, list):
        raise ValueError("Row spans must be a list")
    tokens = list(TOKEN_PATTERN.finditer(row["text"]))
    token_starts = {token.start() for token in tokens}
    token_ends = {token.end() for token in tokens}
    labels = set()
    ranges = []
    for span in spans:
        if not isinstance(span, dict) or span.keys() != _SPAN_FIELDS:
            raise ValueError("Invalid span fields")
        label, start, end, value = (span[field] for field in ("label", "start", "end", "value"))
        if label not in SPAN_LABELS:
            raise ValueError("Unknown span label")
        if label in labels:
            raise ValueError(f"Repeated span label {label}")
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(row["text"]):
            raise ValueError("Span offsets must be integers within the source text")
        if start not in token_starts or end not in token_ends:
            raise ValueError("Span offsets must align to token boundaries")
        if not isinstance(value, str) or value != row["text"][start:end]:
            raise ValueError("Span value must match the exact source slice")
        labels.add(label)
        ranges.append((start, end))
    ranges.sort()
    if any(left[1] > right[0] for left, right in zip(ranges, ranges[1:])):
        raise ValueError("Span ranges must be nonoverlapping")


def validate_corpus(corpus: object) -> None:
    """Check rows, split isolation, and supervision for each ranking group."""
    if not isinstance(corpus, dict) or corpus.keys() != set(SPLITS):
        raise ValueError("Corpus must contain train, validation, and test splits")
    ids = set()
    family_splits = {}
    cases = {}
    for split in SPLITS:
        tasks = corpus[split]
        if not isinstance(tasks, dict) or tasks.keys() != set(TASKS):
            raise ValueError(f"Split {split} must contain both tasks")
        rank_labels = defaultdict(set)
        for task in TASKS:
            rows = tasks[task]
            if not isinstance(rows, list) or not rows:
                raise ValueError(f"Split {split} needs a nonempty {task} row list")
            for row in rows:
                validate_row(row)
                if row["task"] != task:
                    raise ValueError(f"Row {row['id']} is under the wrong task")
                if row["id"] in ids:
                    raise ValueError(f"Repeated row ID {row['id']}")
                ids.add(row["id"])
                family = row["family"]
                case_id = row["case_id"]
                if family_splits.setdefault(family, split) != split:
                    raise ValueError(f"Family {family} appears in multiple splits")
                if cases.setdefault(case_id, (split, family)) != (split, family):
                    raise ValueError(f"Case {case_id} appears in multiple splits or families")
                if task == "rank":
                    rank_labels[case_id, row["query"]].add(row["relevant"])
        if any(labels != {False, True} for labels in rank_labels.values()):
            raise ValueError(f"Rank groups in {split} require both relevance labels")
