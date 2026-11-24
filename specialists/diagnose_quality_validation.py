"""Attribute specialist errors on pinned development inputs using hosted CPU."""

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path

from .artifacts import sha256_file
from .evaluate import load_verified_checkpoint, restore_models
from .evaluate_quality_run import _check_sha256, _rank_summary, _require_host
from .features import BIO_IDS, decode_spans
from .runtime import _batch_span, _encode_rows, _predict_rank, _read_rows
from .structured import select_tags, value_candidates


def _bounds_by_label(row, encoded):
    offsets = encoded["offsets"]
    choices = value_candidates(row["text"], offsets)
    return choices, {label: {(offsets[start][0], offsets[end][1]): (start, end)
                             for start, end in bounds} for label, bounds in choices.items()}


def span_candidate_coverage(examples):
    """Audit the candidate generator independently of weights and thresholds."""
    coverage = defaultdict(Counter)
    for row, encoded in examples:
        _, bounds = _bounds_by_label(row, encoded)
        for span in row["spans"]:
            counter = coverage[span["label"]]
            counter["gold"] += 1
            if (span["start"], span["end"]) in bounds[span["label"]]:
                counter["available"] += 1
    return {field: {"gold": counts["gold"], "available": counts["available"],
                    "missing": counts["gold"] - counts["available"]}
            for field, counts in sorted(coverage.items())}


def _score(logits, label, start, end):
    begin, inside = BIO_IDS[f"B-{label}"], BIO_IDS[f"I-{label}"]
    score = logits[start][begin] - logits[start][0]
    score += sum(logits[index][inside] - logits[index][0] for index in range(start + 1, end + 1))
    return score / (end - start + 1)


def span_row_outcomes(row, encoded, logits):
    choices, bounds = _bounds_by_label(row, encoded)
    spans = decode_spans(row["text"], encoded["offsets"], select_tags(logits, choices))
    predicted = {(span["label"], span["start"], span["end"]) for span in spans}
    expected = {(span["label"], span["start"], span["end"]) for span in row["spans"]}
    events = []
    for label, left, right in sorted(expected):
        position = bounds[label].get((left, right))
        if (label, left, right) in predicted:
            status = "correct"
        elif position is None:
            status = "no_complete_candidate"
        elif _score(logits, label, *position) <= 0:
            status = "null_score_won"
        elif any(other != label and left < end and start < right for other, start, end in predicted):
            status = "overlap_with_output"
        elif any(other == label for other, _, _ in predicted):
            status = "another_value_selected"
        else:
            raise RuntimeError("Span decoder produced an unexplained omission")
        events.append((label, status))
    events.extend((label, "false_positive") for label, _, _ in sorted(predicted - expected))
    return events


def _summarize_spans(torch, model, examples, batch_size):
    model.eval()
    overall = defaultdict(Counter)
    families = defaultdict(lambda: defaultdict(Counter))
    with torch.inference_mode():
        for index in range(0, len(examples), batch_size):
            batch = examples[index:index + batch_size]
            inputs, _ = _batch_span(torch, batch, torch.device("cpu"))
            scores = model(*inputs)
            if not torch.isfinite(scores).all().item():
                raise ValueError("The model returned nonfinite span scores")
            for (row, encoded), logits, length in zip(batch, scores.cpu().tolist(), inputs[-1], strict=True):
                for label, event in span_row_outcomes(row, encoded, logits[:length]):
                    overall[label][event] += 1
                    families[row["family"]][label][event] += 1
    return {"rows": len(examples), "by_field": overall, "by_family": families}


def _summarize_rank(torch, model, examples, batch_size):
    scores = _predict_rank(torch, model, examples, batch_size, torch.device("cpu"), structured=True)
    if any(not math.isfinite(score) for score in scores):
        raise ValueError("The model returned nonfinite ranking scores")
    rows = [row for row, _ in examples]
    predictions = {row["id"]: {"score": score} for row, score in zip(rows, scores, strict=True)}
    families = defaultdict(list)
    for row in rows:
        families[row["family"]].append(row)
    return {"overall": _rank_summary(rows, predictions),
            "by_family": {name: _rank_summary(group, predictions) for name, group in sorted(families.items())}}


def diagnose(*, checkpoint, checkpoint_sha256, config_sha256, training_manifest_sha256,
             validation, rank_probe_sha256):
    _require_host("runpod-cpu", [checkpoint], validation)
    for digest in (checkpoint_sha256, config_sha256, training_manifest_sha256, rank_probe_sha256):
        _check_sha256(digest)
    validation = Path(validation)
    manifest = validation / "manifest.json"
    if sha256_file(manifest) != training_manifest_sha256:
        raise ValueError("Validation files must come from the pinned training manifest")
    data = json.loads(manifest.read_bytes())
    if data.get("synthetic_only") is not True:
        raise ValueError("This diagnostic expects synthetic development data")
    rows = {task: _read_rows(validation / name, task, data["files"][name])
            for task, name in (("span", "validation-span.jsonl"), ("rank", "validation-rank.jsonl"))}
    probe_path = validation / "rank-probe.jsonl"
    probe = _read_rows(probe_path, "rank", {"sha256": rank_probe_sha256,
                      "bytes": probe_path.stat().st_size, "rows": 24})

    import torch

    if torch.cuda.is_available() or torch.cuda.device_count():
        raise RuntimeError("Use a CPU-only Pod for the development diagnostic")
    torch.set_num_threads(1)
    config, weights = load_verified_checkpoint(checkpoint, checkpoint_sha256, training_manifest_sha256,
                                               config_sha256=config_sha256)
    if config["training"].get("structured_objectives") is not True:
        raise ValueError("The diagnostic requires the structured specialist checkpoint")
    model = restore_models(torch, config, weights)
    batch_size = config["training"]["batch_size"]
    inputs = _encode_rows(rows, config)
    return {
        "scope": "synthetic_development_only",
        "checkpoint_sha256": checkpoint_sha256,
        "config_sha256": config_sha256,
        "training_manifest_sha256": training_manifest_sha256,
        "rank_probe_sha256": rank_probe_sha256,
        "span_candidate_coverage": span_candidate_coverage(inputs["span"]),
        "span": _summarize_spans(torch, model["span"], inputs["span"], batch_size),
        "rank_validation": _summarize_rank(torch, model["rank"], inputs["rank"], batch_size),
        "rank_probe": _summarize_rank(torch, model["rank"], _encode_rows({"span": [], "rank": probe}, config)["rank"],
                                      batch_size),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("checkpoint-sha256", "config-sha256", "training-manifest-sha256", "rank-probe-sha256"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    print(json.dumps(diagnose(**vars(parser.parse_args())), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
