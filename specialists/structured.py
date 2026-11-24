"""Complete-value candidates and query-group supervision for specialist training."""

from collections import defaultdict
import re

from .contracts import SPAN_LABELS
from .features import BIO_IDS


MONTH = (
    r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
    r"|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
)
VALUE_PATTERNS = (
    (
        ("ADMISSION_DATE", "DISCHARGE_DATE"),
        re.compile(
            rf"(?<![\w/-])(?:\d{{4}}[-/.]\d{{1,2}}[-/.]\d{{1,2}}"
            rf"|\d{{1,2}}[-/.]\d{{1,2}}[-/.]\d{{4}}"
            rf"|\d{{1,2}}[ -]+(?:{MONTH})[ -]+\d{{4}}"
            rf"|(?:{MONTH})\.?\s+\d{{1,2}},?\s+\d{{4}})(?![\w/-]|\.\d)",
            re.IGNORECASE,
        ),
    ),
    (
        ("POLICY_ID", "MEMBER_ID"),
        re.compile(r"(?<![\w/-])(?=[A-Z0-9/-]*\d)[A-Z0-9]+(?:[-/][A-Z0-9]+)*(?![\w/-])", re.IGNORECASE),
    ),
    (
        ("ROOM_LIMIT", "SUM_INSURED"),
        re.compile(
            r"(?<![\w/.,-])(?:(?:INR|Rs\.?)\s*|₹\s*)?\d+(?:,\d{2,3})*(?:\.\d{2})?"
            r"(?:\s+(?:INR|rupees))?(?![\w/,-]|\.\d)",
            re.IGNORECASE,
        ),
    ),
)


def value_candidates(text, offsets):
    """Return inclusive token positions for complete values considered by each field."""
    starts = {start: index for index, (start, _) in enumerate(offsets)}
    ends = {end: index for index, (_, end) in enumerate(offsets)}
    candidates = {label: [] for label in SPAN_LABELS}
    for labels, pattern in VALUE_PATTERNS:
        for match in pattern.finditer(text):
            start, end = starts.get(match.start()), ends.get(match.end())
            if start is None or end is None:
                continue
            if labels[0] != "ADMISSION_DATE" and any(
                left <= end and start <= right for left, right in candidates["ADMISSION_DATE"]
            ):
                continue
            for label in labels:
                candidates[label].append((start, end))
    return candidates


def candidate_supervision(row, encoded):
    choices = value_candidates(row["text"], encoded["offsets"])
    gold = {span["label"]: (span["start"], span["end"]) for span in row["spans"]}
    targets = {}
    for label, bounds in choices.items():
        for index, (start, end) in enumerate(bounds, start=1):
            offsets = encoded["offsets"]
            if (offsets[start][0], offsets[end][1]) == gold.get(label):
                targets[label] = index
                break
        else:
            if label in gold:
                raise ValueError(f"{row['id']} has no complete candidate for {label}")
            targets[label] = 0
    return choices, targets


def candidate_loss(torch, logits, examples):
    """Score complete spans against a zero-logit null candidate for every field."""
    width = max(1, max(len(bounds) for _, encoded in examples for bounds in encoded["choices"].values()))
    groups, targets = [], []
    for index, (_, encoded) in enumerate(examples):
        for label, bounds in encoded["choices"].items():
            begin, inside = BIO_IDS[f"B-{label}"], BIO_IDS[f"I-{label}"]
            slots = [(index, start, end, begin, inside, True) for start, end in bounds]
            slots.extend([(index, 0, 0, begin, inside, False)] * (width - len(bounds)))
            groups.append(slots)
            targets.append(encoded["targets"][label])
    batch, start, end, begin, inside, valid = torch.tensor(groups, device=logits.device).unbind(-1)
    margins = logits - logits[..., :1]
    cumulative = margins.cumsum(dim=1)
    scores = (
        margins[batch, start, begin] + cumulative[batch, end, inside] - cumulative[batch, start, inside]
    ) / (end - start + 1)
    scores = scores.masked_fill(~valid.bool(), float("-inf"))
    return torch.nn.functional.cross_entropy(
        torch.cat((torch.zeros_like(scores[:, :1]), scores), dim=1),
        torch.tensor(targets, device=logits.device),
    )


def select_tags(logits, candidates):
    """Decode complete, nonoverlapping values with at most one span per field."""
    ranked = []
    for label, bounds in candidates.items():
        begin, inside = BIO_IDS[f"B-{label}"], BIO_IDS[f"I-{label}"]
        for start, end in bounds:
            total = logits[start][begin] - logits[start][0]
            total += sum(logits[i][inside] - logits[i][0] for i in range(start + 1, end + 1))
            score = total / (end - start + 1)
            if score > 0:
                ranked.append((-score, start, end, label))
    tags, assigned = [BIO_IDS["O"]] * len(logits), set()
    for _, start, end, label in sorted(ranked):
        if label in assigned or any(tags[start:end + 1]):
            continue
        tags[start] = BIO_IDS[f"B-{label}"]
        tags[start + 1:end + 1] = [BIO_IDS[f"I-{label}"]] * (end - start)
        assigned.add(label)
    return tags


def rank_groups(examples):
    groups = defaultdict(list)
    for example in examples:
        row, _ = example
        groups[row["case_id"], row["query"]].append(example)
    if any({row["relevant"] for row, _ in group} != {False, True} for group in groups.values()):
        raise ValueError("Each training query needs relevant and irrelevant candidates")
    return list(groups.values())


def rank_group_loss(torch, logits, targets, lengths):
    """Penalize probability assigned outside the relevant set for each query."""
    losses = [
        scores.logsumexp(dim=0) - scores[relevant.bool()].logsumexp(dim=0)
        for scores, relevant in zip(logits.split(lengths), targets.split(lengths), strict=True)
    ]
    return torch.stack(losses).mean()
