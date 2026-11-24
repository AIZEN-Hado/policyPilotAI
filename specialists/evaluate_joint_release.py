"""Score two frozen field decoders on the same new held-out synthetic documents."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from .evaluate import load_verified_checkpoint, restore_models
from .evaluate_quality_run import TARGET, _check_sha256, _read_holdout, _require_host, summarize
from .joint_selection import _predictions, compare_outputs
from .runtime import _encode_rows, _predict_rank


def evaluate(*, checkpoint, checkpoint_sha256, config_sha256, training_manifest_sha256, holdout, holdout_sha256):
    _require_host("runpod-cpu", [checkpoint], holdout)
    started = time.monotonic()
    for digest in (checkpoint_sha256, config_sha256, training_manifest_sha256, holdout_sha256):
        _check_sha256(digest)
    rows, source_by_family = _read_holdout(holdout, holdout_sha256)

    import torch

    if torch.cuda.is_available() or torch.cuda.device_count():
        raise RuntimeError("Use a CPU-only Runpod Pod for evaluation")
    torch.set_num_threads(1)
    config, weights = load_verified_checkpoint(checkpoint, checkpoint_sha256, training_manifest_sha256,
                                               config_sha256=config_sha256)
    if config["training"].get("structured_objectives") is not True:
        raise ValueError("Joint selection requires the structured specialist checkpoint")
    models = restore_models(torch, config, weights)
    inputs = _encode_rows(rows, config)
    batch = config["training"]["batch_size"]
    greedy, joint = _predictions(torch, models["span"], inputs["span"], batch)
    rank_scores = _predict_rank(torch, models["rank"], inputs["rank"], batch, torch.device("cpu"), structured=True)
    rank = [{"id": row["id"], "score": score} for row, score in zip(rows["rank"], rank_scores, strict=True)]
    reports = {}
    for mode, outputs in (("greedy", greedy), ("joint", joint)):
        predictions = [{"id": row["id"], **outputs[row["id"]]} for row in rows["span"]]
        reports[mode] = summarize(rows, {"span": {"predictions": predictions}, "rank": {"predictions": rank}},
                                  source_by_family)
    comparison = compare_outputs(rows["span"], greedy, joint)
    return {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "scope": "held_out_synthetic_text",
        "checkpoint_sha256": checkpoint_sha256,
        "config_sha256": config_sha256,
        "training_manifest_sha256": training_manifest_sha256,
        "holdout_manifest_sha256": holdout_sha256,
        "target": TARGET,
        "reports": reports,
        "paired_changes": comparison["changes"],
        "joint_improvement_criterion_met": comparison["evaluation_criterion_met"],
        "production_accuracy_established": False,
        "ranker_same_checkpoint_and_scores": True,
        "runtime": {"device": "cpu", "torch": torch.__version__,
                    "elapsed_seconds": round(time.monotonic() - started, 3)},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("checkpoint-sha256", "config-sha256", "training-manifest-sha256", "holdout-sha256"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--holdout", type=Path, required=True)
    print(json.dumps(evaluate(**vars(parser.parse_args())), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
