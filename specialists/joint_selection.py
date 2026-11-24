"""Compare greedy and joint field selection with a frozen checkpoint on hosted CPU."""

import argparse
from bisect import bisect_left
from collections import Counter, defaultdict
import json
from pathlib import Path

from .artifacts import sha256_file
from .contracts import SPAN_LABELS
from .diagnose_quality_validation import _score
from .evaluate import load_verified_checkpoint, restore_models
from .evaluate_quality_run import _check_sha256, _require_host, _span_summary
from .features import BIO_IDS, decode_spans
from .runtime import _batch_span, _encode_span, _read_rows
from .structured import select_tags, value_candidates


FIELD_BITS = {field: 1 << index for index, field in enumerate(SPAN_LABELS)}


def best_assignments(scored):
    """Maximize positive score over nonoverlapping intervals with unique fields."""
    candidates = sorted((end, start, label, score) for start, end, label, score in scored if score > 0)
    ends = [end for end, _, _, _ in candidates]
    # Each prefix stores one best solution per set of assigned fields.
    prefixes = [{0: (0.0, ())}]
    for index, (end, start, label, score) in enumerate(candidates):
        previous = prefixes[bisect_left(ends, start, hi=index)]
        current = prefixes[-1].copy()
        field = FIELD_BITS[label]
        for mask, (total, selected) in previous.items():
            if mask & field:
                continue
            updated = field | mask
            combined = total + score
            if updated not in current or combined > current[updated][0]:
                current[updated] = (combined, (*selected, (start, end, label)))
        prefixes.append(current)
    # Equal objectives favor fewer fields. The interval sort makes remaining ties deterministic.
    total, selected = max(prefixes[-1].values(), key=lambda entry: (entry[0], -len(entry[1])))
    return total, selected


def joint_tags(logits, choices):
    scored = [(start, end, label, _score(logits, label, start, end))
              for label, intervals in choices.items() for start, end in intervals]
    total, assignments = best_assignments(scored)
    tags = [BIO_IDS["O"]] * len(logits)
    for start, end, label in assignments:
        tags[start] = BIO_IDS[f"B-{label}"]
        tags[start + 1:end + 1] = [BIO_IDS[f"I-{label}"]] * (end - start)
    return tags, total


def _predictions(torch, model, examples, batch_size):
    greedy, joint = {}, {}
    model.eval()
    with torch.inference_mode():
        for index in range(0, len(examples), batch_size):
            batch = examples[index:index + batch_size]
            inputs, _ = _batch_span(torch, batch, torch.device("cpu"))
            raw = model(*inputs)
            if not torch.isfinite(raw).all().item():
                raise ValueError("Nonfinite span model scores")
            for (row, encoded), logits, size in zip(batch, raw.cpu().tolist(), inputs[-1], strict=True):
                logits = logits[:size]
                text, offsets = row["text"], encoded["offsets"]
                choices = value_candidates(text, offsets)
                baseline = decode_spans(text, offsets, select_tags(logits, choices))
                tags, optimal_score = joint_tags(logits, choices)
                starts = {left: ix for ix, (left, _) in enumerate(offsets)}
                ends = {right: ix for ix, (_, right) in enumerate(offsets)}
                baseline_score = sum(_score(logits, p["label"], starts[p["start"]], ends[p["end"]]) for p in baseline)
                if optimal_score + 1e-8 < baseline_score:
                    raise RuntimeError("Joint selection failed to match the greedy objective")
                greedy[row["id"]] = {"spans": baseline}
                joint[row["id"]] = {"spans": decode_spans(text, offsets, tags)}
    return greedy, joint


def compare_outputs(rows, greedy, joint):
    comparisons = Counter()
    families = defaultdict(list)
    for row in rows:
        families[row["family"]].append(row)
        expected = {(p["label"], p["start"], p["end"]) for p in row["spans"]}
        key = row["id"]
        left, right = ({(p["label"], p["start"], p["end"]) for p in report[key]["spans"]}
                       for report in (greedy, joint))
        comparisons["rows_changed"] += left != right
        comparisons["gold_recovered"] += len((right - left) & expected)
        comparisons["gold_lost"] += len((left - right) & expected)
    before, after = (_span_summary(rows, baseline) for baseline in (greedy, joint))
    return {
        "greedy": before,
        "joint": after,
        "changes": dict(comparisons),
        "by_family": {key: {"greedy": _span_summary(group, greedy)["exact_span"],
                             "joint": _span_summary(group, joint)["exact_span"]}
                      for key, group in sorted(families.items())},
        "evaluation_criterion_met": (
            after["exact_span"]["correct"] > before["exact_span"]["correct"]
            and after["exact_span"]["false_positives"] <= before["exact_span"]["false_positives"]
        ),
    }


def compare(*, checkpoint, checkpoint_sha256, config_sha256, training_manifest_sha256, validation):
    _require_host("runpod-cpu", [checkpoint], validation)
    for digest in (checkpoint_sha256, config_sha256, training_manifest_sha256):
        _check_sha256(digest)
    validation = Path(validation)
    manifest = validation / "manifest.json"
    if sha256_file(manifest) != training_manifest_sha256:
        raise ValueError("Use validation files from the pinned training manifest")
    inventory = json.loads(manifest.read_bytes())
    if inventory.get("synthetic_only") is not True:
        raise ValueError("Use synthetic development data")
    name = "validation-span.jsonl"
    rows = _read_rows(validation / name, "span", inventory["files"][name])

    import torch

    if torch.cuda.is_available() or torch.cuda.device_count():
        raise RuntimeError("Use a CPU-only Runpod Pod for this comparison")
    torch.set_num_threads(1)
    config, weights = load_verified_checkpoint(checkpoint, checkpoint_sha256, training_manifest_sha256,
                                               config_sha256=config_sha256)
    if config["training"].get("structured_objectives") is not True:
        raise ValueError("The comparison requires structured specialist weights")
    model = restore_models(torch, config, weights)["span"]
    examples = [(row, _encode_span(row, config["span"])) for row in rows]
    greedy, joint = _predictions(torch, model, examples, config["training"]["batch_size"])
    return {"scope": "synthetic_development_only",
            "checkpoint_sha256": checkpoint_sha256, "training_manifest_sha256": training_manifest_sha256,
            "config_sha256": config_sha256, "comparison": compare_outputs(rows, greedy, joint)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("checkpoint-sha256", "config-sha256", "training-manifest-sha256"):
        parser.add_argument(f"--{flag}", required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    print(json.dumps(compare(**vars(parser.parse_args())), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
