"""Bounded pseudo-label selection and training on a sealed synthetic pool."""

import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from .contracts import TASKS, validate_row
from .diagnose_quality_validation import _score
from .runtime import _batch_rank, _batch_span, _encode_rows, _evaluate, _save, _train_structured, _verified_bytes
from .structured import value_candidates


POOL_DIRECTORY = "unlabeled"
TEACHER_FILE = "teacher.pt"


def _settings(settings):
    if settings.keys() != {"rounds", "epochs", "span_probability", "rank_probability", "margin", "pool"}:
        raise ValueError("Invalid self-training settings")
    for name, maximum in (("rounds", 3), ("epochs", 8)):
        if type(settings[name]) is not int or not 1 <= settings[name] <= maximum:
            raise ValueError(f"Invalid self-training {name}")
    for name in ("span_probability", "rank_probability"):
        if not 0.5 < settings[name] < 1:
            raise ValueError(f"Invalid self-training {name}")
    if not 0 < settings["margin"] <= 10 or settings["pool"].keys() != set(TASKS):
        raise ValueError("Invalid pseudo-label margin or inventory")


def load_pool(project, settings, train, validation):
    _settings(settings)
    used = [row for split in (train, validation) for examples in split.values() for row, _ in examples]
    used_ids = {row["id"] for row in used}
    used_cases = {row["case_id"] for row in used}
    used_families = {row["family"] for row in used}
    used_text = {row["text"] for row in used}
    used_queries = {row["query"] for row in used if row["task"] == "rank"}
    pool = {}
    for task, spec in settings["pool"].items():
        path = Path(project) / POOL_DIRECTORY / f"{task}.jsonl"
        raw = _verified_bytes(path, spec)
        rows = [json.loads(line) for line in raw.splitlines()]
        if not rows or len(rows) != spec["rows"]:
            raise ValueError("Unlabeled pool row count differs from its configuration")
        label = "spans" if task == "span" else "relevant"
        for row in rows:
            if label in row or row["task"] != task:
                raise ValueError("Self-training pool contains supervision or the wrong task")
            stub = [] if task == "span" else False
            validate_row({**row, label: stub})
            if (row["id"] in used_ids or row["case_id"] in used_cases or row["family"] in used_families
                    or row["text"] in used_text or row.get("query") in used_queries):
                raise ValueError("Self-training pool overlaps supervised inputs")
            used_ids.add(row["id"])
        pool[task] = rows
    return pool


def confident_winner(scores, probability, margin):
    if not scores or any(not math.isfinite(value) for value in scores):
        raise ValueError("Expected finite pseudo-label scores")
    order = sorted(range(len(scores)), key=scores.__getitem__, reverse=True)
    best = order[0]
    if len(order) == 1:
        return best
    gap = scores[best] - scores[order[1]]
    confidence = 1 / sum(math.exp(value - scores[best]) for value in scores)
    return best if gap >= margin and confidence >= probability else None


def _span_predictions(torch, model, config, rows, device, settings):
    examples = _encode_rows({"span": [{**row, "spans": []} for row in rows], "rank": []}, config)["span"]
    result = {}
    batch_size = config["training"]["batch_size"]
    model.eval()
    with torch.inference_mode():
        for start in range(0, len(examples), batch_size):
            batch = examples[start:start + batch_size]
            args, _ = _batch_span(torch, batch, device)
            for (row, encoded), logits in zip(batch, model(*args).cpu().tolist(), strict=True):
                offsets = encoded["offsets"]
                spans = []
                for label, choices in value_candidates(row["text"], offsets).items():
                    scores = [0.0] + [_score(logits, label, left, right) for left, right in choices]
                    winner = confident_winner(scores, settings["span_probability"], settings["margin"])
                    if winner is None:
                        break
                    if winner > 0:
                        left, right = choices[winner - 1]
                        spans.append((offsets[left][0], offsets[right][1], label))
                else:
                    spans.sort()
                    if spans and all(a[1] <= b[0] for a, b in zip(spans, spans[1:])):
                        result[row["id"]] = tuple(spans)
    return result


def _rank_predictions(torch, model, config, rows, device, settings):
    sources = [{**row, "relevant": False} for row in rows]
    examples = _encode_rows({"span": [], "rank": sources}, config)["rank"]
    groups = defaultdict(list)
    batch_size = config["training"]["batch_size"]
    model.eval()
    with torch.inference_mode():
        for start in range(0, len(examples), batch_size):
            batch = examples[start:start + batch_size]
            inputs, _ = _batch_rank(torch, batch, device)
            for (row, _), score in zip(batch, model(*inputs).cpu().tolist(), strict=True):
                groups[row["case_id"], row["query"]].append((row["id"], score))
    result = {}
    for candidates in groups.values():
        if len(candidates) < 2:
            raise ValueError("An unlabeled ranking group needs competing passages")
        ids, scores = zip(*candidates, strict=True)
        winner = confident_winner(scores, settings["rank_probability"], settings["margin"])
        if winner is not None:
            for index, row_id in enumerate(ids):
                result[row_id] = index == winner
    return result


def perturb_span(text):
    # Preserve all source offsets while moving existing clause separators to line breaks.
    return "".join("\n" if char == " " and text[index - 1:index] in {".", ";", "|"} else char
                   for index, char in enumerate(text))


def _rank_variant(text):
    return " ".join(word for word in text.split() if word.casefold() not in {"a", "an", "the"})


def pseudo_labels(torch, models, config, pool, device, settings):
    span = pool["span"]
    rank = pool["rank"]
    variants = [{**row, "text": perturb_span(row["text"])} for row in span]
    original = _span_predictions(torch, models["span"], config, span, device, settings)
    transformed = _span_predictions(torch, models["span"], config, variants, device, settings)
    labeled_span = []
    for row in span:
        key = row["id"]
        if key not in original or original[key] != transformed.get(key):
            continue
        spans = [{"label": label, "start": left, "end": right, "value": row["text"][left:right]}
                 for left, right, label in original[key]]
        labeled = {**row, "spans": spans}
        validate_row(labeled)
        labeled_span.append(labeled)

    # Perturb the passage only so ranking groups retain their original key.
    alternates = [{**row, "text": _rank_variant(row["text"])} for row in rank]
    original = _rank_predictions(torch, models["rank"], config, rank, device, settings)
    transformed = _rank_predictions(torch, models["rank"], config, alternates, device, settings)
    rejected = {row["case_id"] for row in rank if row["id"] not in original
                or original[row["id"]] != transformed.get(row["id"])}
    labeled_rank = [{**row, "relevant": original[row["id"]]} for row in rank if row["case_id"] not in rejected]
    return {"span": labeled_span, "rank": labeled_rank}


def prediction_fingerprint(report):
    predictions = {task: report[task]["predictions"] for task in TASKS}
    return hashlib.sha256(json.dumps(predictions, sort_keys=True, allow_nan=False).encode()).hexdigest()


def learn(torch, models, config, train, validation, output, device, pool):
    settings = config["self_training"]
    training = config["training"]
    batch_size = training["batch_size"]
    baseline = _evaluate(torch, models, validation, batch_size, device, structured=True)
    teacher = output / TEACHER_FILE
    state = {task: {key: value.detach().cpu() for key, value in model.state_dict().items()}
             for task, model in models.items()}
    _save(teacher, lambda stream: torch.save(state, stream))
    del state

    seen = {task: set() for task in TASKS}
    learned = {task: [] for task in TASKS}
    history = []
    for step in range(settings["rounds"]):
        fresh = {task: [row for row in pool[task] if row["id"] not in seen[task]] for task in TASKS}
        new = pseudo_labels(torch, models, config, fresh, device, settings)
        for task in TASKS:
            seen[task].update(row["id"] for row in new[task])
        round_report = {"round": step + 1, "span_rows_added": len(new["span"]),
                        "span_labels_added": dict(Counter(span["label"] for row in new["span"] for span in row["spans"])),
                        "rank_groups_added": len({(row["case_id"], row["query"]) for row in new["rank"]}),
                        "rank_rows_added": len(new["rank"]), "optimizer_updates": {}}
        encoded = _encode_rows(new, config)
        for task in TASKS:
            if not new[task]:
                continue
            learned[task].extend(encoded[task])
            round_training = {**training, "seed": training["seed"] + step + 1, "epochs": settings["epochs"],
                              "learning_rate": training["learning_rate"] * 0.45}
            round_report["optimizer_updates"][task] = _train_structured(
                torch, models[task], task, train[task] + learned[task], validation[task], round_training, device,
                macro_span=config["span"].get("contextual_values", False))
        history.append(round_report)

    return {"teacher_bytes": teacher.stat().st_size, "teacher_validation_fingerprint": prediction_fingerprint(baseline),
            "teacher_validation_metrics": {task: baseline[task]["metrics"] for task in TASKS},
            "pool_sizes": {task: len(rows) for task, rows in pool.items()}, "rounds": history}
