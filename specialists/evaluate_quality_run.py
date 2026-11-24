"""Compare verified specialists on a pinned synthetic holdout on hosted CPU."""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import resource
import sys
import time

from .artifacts import SOURCE_MAX_BYTES, _open_regular
from .contracts import SPAN_LABELS, TASKS
from .evaluate import load_verified_checkpoint, require_hosted_colab, restore_models
from .runtime import _encode_rows, _evaluate, _prf, _read_rows, _run_baseline


TARGET = 0.99
MANIFEST_LIMIT = 1024 * 1024
RUNPOD_WORKSPACE = Path("/workspace")


def _check_sha256(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("Use lowercase SHA-256 fingerprints from the verified receipts")


def _require_host(host, checkpoints, holdout):
    if host == "colab":
        require_hosted_colab()
    elif host == "runpod-cpu":
        if (sys.platform != "linux" or not os.environ.get("RUNPOD_POD_ID", "").strip()
                or not os.path.ismount(RUNPOD_WORKSPACE)):
            raise RuntimeError("Runpod evaluation requires a hosted CPU Pod with /workspace mounted.")
        workspace = RUNPOD_WORKSPACE.resolve()
        if any(not Path(path).resolve().is_relative_to(workspace) for path in checkpoints):
            raise RuntimeError("Keep checkpoints inside the mounted Runpod workspace.")
        if not Path(holdout).resolve().is_relative_to(Path("/tmp").resolve()):
            raise RuntimeError("Extract the holdout into the CPU Pod's /tmp directory.")
    else:
        raise ValueError("Unknown hosted CPU environment")


def _read_holdout(directory, expected_sha256):
    _check_sha256(expected_sha256)
    directory = Path(directory)
    with _open_regular(directory / "manifest.json") as handle:
        content = handle.read(MANIFEST_LIMIT + 1)
    if len(content) > MANIFEST_LIMIT or sha256(content).hexdigest() != expected_sha256:
        raise ValueError("Holdout manifest does not match the pinned SHA-256")
    manifest = json.loads(content)
    if (not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int
            or manifest["schema_version"] != 1 or manifest.get("split") != "test"
            or manifest.get("synthetic_only") is not True):
        raise ValueError("Use a version 1 held-out synthetic test manifest")
    files = manifest.get("files")
    if not isinstance(files, dict) or files.keys() != {f"test-{task}.jsonl" for task in TASKS}:
        raise ValueError("The holdout must contain exactly two test datasets")
    for name, entry in files.items():
        if (not isinstance(entry, dict) or type(entry.get("rows")) is not int or entry["rows"] < 1
                or type(entry.get("bytes")) is not int or not 1 <= entry["bytes"] <= SOURCE_MAX_BYTES
                or entry["rows"] > entry["bytes"]):
            raise ValueError(f"Invalid holdout inventory for {name}")
        _check_sha256(entry.get("sha256"))
    rows = {task: _read_rows(directory / f"test-{task}.jsonl", task, files[f"test-{task}.jsonl"])
            for task in TASKS}

    cases, groups, ids = {}, defaultdict(set), set()
    for task in TASKS:
        for row in rows[task]:
            row_id, case, family = row["id"], row["case_id"], row["family"]
            if row_id in ids or cases.setdefault(case, family) != family:
                raise ValueError("Holdout row IDs must be unique and cases must stay in one family")
            ids.add(row_id)
            if task == "rank":
                groups[case, row["query"]].add(row["relevant"])
    if any(labels != {False, True} for labels in groups.values()):
        raise ValueError("Each holdout ranking group needs a relevant and an irrelevant passage")

    families = set(cases.values())
    sources = manifest.get("source_by_family")
    if sources is None:
        source = manifest.get("source", "unspecified")
        sources = dict.fromkeys(families, source)
    if (not isinstance(sources, dict) or sources.keys() != families
            or any(not isinstance(source, str) or not source.strip() for source in sources.values())):
        raise ValueError("The holdout must map each scored family to one source")
    return rows, sources


def _predictions(rows, report, task):
    """Index outputs by row ID so missing predictions count as misses."""
    valid = {row["id"] for row in rows[task]}
    result = {}
    for prediction in report[task]["predictions"]:
        row_id = prediction["id"]
        if row_id not in valid or row_id in result:
            raise ValueError(f"Unexpected or duplicate {task} prediction for {row_id}")
        result[row_id] = prediction
    return result


def _span_key(span):
    return span["label"], span["start"], span["end"]


def _exact_metrics(correct, predicted, expected):
    return {
        **_prf(correct, predicted, expected),
        "correct": correct,
        "predicted": predicted,
        "false_positives": predicted - correct,
        "false_negatives": expected - correct,
    }


def _span_summary(rows, predictions):
    counts = {label: [0, 0, 0] for label in SPAN_LABELS}
    missing_rows = 0
    for row in rows:
        output = predictions.get(row["id"])
        missing_rows += output is None
        expected = {_span_key(span) for span in row["spans"]}
        actual = {_span_key(span) for span in output["spans"]} if output is not None else set()
        if any(label not in counts for label, _, _ in actual):
            raise ValueError("Predicted an unknown span label")
        for label, *_ in actual & expected:
            counts[label][0] += 1
        for label, *_ in actual:
            counts[label][1] += 1
        for label, *_ in expected:
            counts[label][2] += 1
    return {
        "rows": len(rows),
        "unscored_rows": missing_rows,
        "exact_span": _exact_metrics(*(sum(values) for values in zip(*counts.values()))),
        "exact_span_by_label": {label: _exact_metrics(*values) for label, values in counts.items()},
    }


def _rank_summary(rows, predictions):
    grouped = defaultdict(list)
    for row in rows:
        output = predictions.get(row["id"])
        score = None if output is None else output.get("score")
        if score is not None and (type(score) not in (int, float) or not math.isfinite(score)):
            raise ValueError("All ranking scores must be finite numbers")
        grouped[row["case_id"], row["query"]].append((score, row["relevant"]))
    outcomes = Counter()
    for group in grouped.values():
        if any(score is None for score, _ in group):
            outcomes["incomplete"] += 1
            continue
        top = max(score for score, _ in group)
        leaders = [relevant for score, relevant in group if score == top]
        if len(leaders) > 1:
            outcomes["tied"] += 1
        else:
            outcomes["correct" if leaders[0] else "incorrect"] += 1
    count = len(grouped)
    return {
        "rows": len(rows),
        "groups": count,
        "correct_groups": outcomes["correct"],
        "missed_groups": count - outcomes["correct"],
        "incorrect_top_groups": outcomes["incorrect"],
        "tied_top_groups": outcomes["tied"],
        "incomplete_groups": outcomes["incomplete"],
        "strict_group_top1_accuracy": outcomes["correct"] / count if count else None,
    }


def _target_failures(span, rank, target=TARGET):
    failures = {}
    for label in SPAN_LABELS:
        metrics = span["exact_span_by_label"].get(label)
        if metrics is None or not metrics["support"]:
            failures[label] = ["missing_support"]
            continue
        below_target = [metric for metric in ("precision", "recall") if metrics[metric] < target]
        if below_target:
            failures[label] = below_target
    score = rank["strict_group_top1_accuracy"]
    if score is None or score < target:
        failures["ranking"] = ["strict_group_top1_accuracy"]
    return failures


def summarize(rows, report, source_by_family, *, target=TARGET):
    span_predictions = _predictions(rows, report, "span")
    rank_predictions = _predictions(rows, report, "rank")

    def score(subset):
        return {
            "span": _span_summary(subset["span"], span_predictions),
            "rank": _rank_summary(subset["rank"], rank_predictions),
        }

    overall = score(rows)
    failures = _target_failures(overall["span"], overall["rank"], target)
    by_family, by_source = defaultdict(lambda: {task: [] for task in TASKS}), defaultdict(
        lambda: {task: [] for task in TASKS})
    for task in TASKS:
        for row in rows[task]:
            by_family[row["family"]][task].append(row)
            by_source[source_by_family[row["family"]]][task].append(row)
    return {
        **overall,
        "by_family": {key: score(subset) for key, subset in sorted(by_family.items())},
        "by_source": {key: score(subset) for key, subset in sorted(by_source.items())},
        "synthetic_target_met": not failures,
        "target_failures": failures,
    }


def _score_checkpoint(torch, rows, config, weights):
    examples = _encode_rows(rows, config)
    models = restore_models(torch, config, weights)
    return _evaluate(torch, models, examples, config["training"]["batch_size"], torch.device("cpu"),
                     structured=config["training"].get("structured_objectives", False))


def evaluate(candidate, candidate_sha256, candidate_train_manifest_sha256, holdout, holdout_sha256,
             reference=None, reference_sha256=None, reference_train_manifest_sha256=None,
             candidate_config_sha256=None, reference_config_sha256=None, host="colab"):
    paths = [candidate]
    if reference is not None:
        paths.append(reference)
    _require_host(host, paths, holdout)
    started = time.monotonic()
    ref = (reference, reference_sha256, reference_train_manifest_sha256)
    if any(value is not None for value in ref) != all(value is not None for value in ref):
        raise ValueError("A reference needs its archive, archive SHA-256 and training manifest SHA-256")
    if reference_config_sha256 is not None and reference is None:
        raise ValueError("A reference config SHA-256 requires a reference checkpoint")
    for digest in (candidate_sha256, candidate_train_manifest_sha256):
        _check_sha256(digest)
    for digest in (reference_sha256, reference_train_manifest_sha256, candidate_config_sha256,
                   reference_config_sha256):
        if digest is not None:
            _check_sha256(digest)
    rows, sources = _read_holdout(holdout, holdout_sha256)

    import torch

    if torch.cuda.is_available() or torch.cuda.device_count():
        raise RuntimeError("Select a CPU-only hosted runtime for holdout evaluation.")
    torch.set_num_threads(1)
    config, weights = load_verified_checkpoint(
        candidate, candidate_sha256, candidate_train_manifest_sha256, config_sha256=candidate_config_sha256)
    rules = _run_baseline(_encode_rows(rows, config))
    reports = {
        "rules": summarize(rows, rules, sources),
        "candidate": summarize(rows, _score_checkpoint(torch, rows, config, weights), sources),
    }
    del weights
    if reference is not None:
        config, weights = load_verified_checkpoint(
            reference, reference_sha256, reference_train_manifest_sha256, config_sha256=reference_config_sha256)
        reports["reference"] = summarize(rows, _score_checkpoint(torch, rows, config, weights), sources)
    return {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "candidate_sha256": candidate_sha256,
        "candidate_train_manifest_sha256": candidate_train_manifest_sha256,
        "candidate_config_sha256": candidate_config_sha256,
        "reference_sha256": reference_sha256,
        "reference_train_manifest_sha256": reference_train_manifest_sha256,
        "reference_config_sha256": reference_config_sha256,
        "holdout_manifest_sha256": holdout_sha256,
        "scope": "held_out_synthetic_text",
        "production_accuracy_established": False,
        "target": TARGET,
        "reports": reports,
        "runtime": {
            "host": host, "device": "cpu", "torch": torch.__version__,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=("colab", "runpod-cpu"), default="colab")
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--candidate-sha256", required=True)
    parser.add_argument("--candidate-train-manifest-sha256", required=True)
    parser.add_argument("--candidate-config-sha256")
    parser.add_argument("--holdout", type=Path, required=True)
    parser.add_argument("--holdout-sha256", required=True)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--reference-sha256")
    parser.add_argument("--reference-train-manifest-sha256")
    parser.add_argument("--reference-config-sha256")
    try:
        report = evaluate(**vars(parser.parse_args()))
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        parser.error(str(error))
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
