"""Measure a verified candidate on the separately packaged synthetic holdout."""

import argparse
import json
from pathlib import Path

from .artifacts import sha256_file
from .contracts import SPAN_LABELS
from .evaluate import load_verified_checkpoint, require_hosted_colab, restore_models
from .runtime import _evaluate, _rank_report, _read_split, _run_baseline


VERSION = "specialists-precision-v1"
TRAIN_MANIFEST_SHA256 = "3a44bf598e8190bb4e81f972f2891c5fd688d1334b60196f9e72258ca6329dc3"
TARGET = 0.99


def target_met(span_metrics, rank_metrics):
    exact = span_metrics["exact_span_by_label"]
    return rank_metrics["strict_group_top1_accuracy"] >= TARGET and all(
        label in exact and exact[label]["support"] > 0
        and exact[label]["precision"] >= TARGET and exact[label]["recall"] >= TARGET
        for label in SPAN_LABELS
    )


def _summarize(report, data):
    by_family = {}
    examples = data["rank"]
    scores = [prediction["score"] for prediction in report["rank"]["predictions"]]
    for family in sorted({row["family"] for row, _ in examples}):
        pairs = [(example, score) for example, score in zip(examples, scores, strict=True)
                 if example[0]["family"] == family]
        subset, values = zip(*pairs, strict=True)
        by_family[family] = _rank_report(subset, values)["metrics"]["strict_group_top1_accuracy"]
    span, rank = (report[task]["metrics"] for task in ("span", "rank"))
    return {"span": span, "rank": rank, "rank_strict_top1_by_family": by_family,
            "synthetic_target_met": target_met(span, rank)}


def evaluate(candidate, candidate_sha256, holdout, holdout_sha256, reference=None, reference_sha256=None):
    require_hosted_colab()
    stamp = holdout / "manifest.json"
    if sha256_file(stamp) != holdout_sha256:
        raise ValueError("Holdout manifest differs from its preparation receipt")
    manifest = json.loads(stamp.read_bytes())
    if (manifest.get("experiment") != VERSION or manifest.get("split") != "test"
            or manifest.get("synthetic_only") is not True
            or manifest.get("training_manifest_sha256") != TRAIN_MANIFEST_SHA256):
        raise ValueError("Holdout manifest does not belong to the precision experiment")
    config, weights = load_verified_checkpoint(candidate, candidate_sha256, TRAIN_MANIFEST_SHA256)
    packaged_config = json.loads(Path(__file__).with_name("config.json").read_bytes())
    if config != packaged_config or config["training"].get("structured_objectives") is not True:
        raise ValueError("Candidate does not match the reviewed precision configuration")
    data = _read_split(holdout, "test", config, manifest["files"])
    reports = {"rules": _summarize(_run_baseline(data), data)}

    import torch

    torch.set_num_threads(1)
    device = torch.device("cpu")
    models = restore_models(torch, config, weights)
    result = _evaluate(torch, models, data, config["training"]["batch_size"], device, structured=True)
    reports["candidate"] = _summarize(result, data)
    del models
    if reference is not None:
        prior_config, prior_weights = load_verified_checkpoint(reference, reference_sha256, TRAIN_MANIFEST_SHA256)
        if prior_config["training"].get("structured_objectives", False):
            raise ValueError("Reference must use the original specialist objectives")
        prior_data = _read_split(holdout, "test", prior_config, manifest["files"])
        prior = restore_models(torch, prior_config, prior_weights)
        result = _evaluate(torch, prior, prior_data, prior_config["training"]["batch_size"], device)
        reports["reference"] = _summarize(result, prior_data)

    return {
        "experiment": VERSION,
        "candidate_sha256": candidate_sha256,
        "reference_sha256": reference_sha256,
        "holdout_manifest_sha256": holdout_sha256,
        "target": TARGET,
        "reports": reports,
        "scope": "Synthetic text only. Template variants do not establish production accuracy.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--candidate-sha256", required=True)
    parser.add_argument("--holdout", required=True, type=Path)
    parser.add_argument("--holdout-sha256", required=True)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--reference-sha256")
    args = parser.parse_args()
    if bool(args.reference) != bool(args.reference_sha256):
        parser.error("Provide both the reference archive and its SHA-256, or neither")
    print(json.dumps(evaluate(**vars(args)), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
