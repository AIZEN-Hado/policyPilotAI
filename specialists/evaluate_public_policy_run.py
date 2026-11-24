"""Score the data-augmented and previous checkpoints on newly frozen inputs."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from .evaluate import load_verified_checkpoint, restore_models
from .evaluate_quality_run import TARGET, _check_sha256, _read_holdout, _require_host, summarize
from .joint_selection import _predictions
from .runtime import _encode_rows, _predict_rank


def _score(torch, rows, sources, checkpoint, archive_sha256, training_sha256, config_sha256):
    config, weights = load_verified_checkpoint(checkpoint, archive_sha256, training_sha256,
                                               config_sha256=config_sha256)
    if config["training"].get("structured_objectives") is not True:
        raise ValueError("Compare structured specialist checkpoints")
    models = restore_models(torch, config, weights)
    return score_models(torch, rows, sources, config, models)


def score_models(torch, rows, sources, config, models, *, target=TARGET):
    inputs = _encode_rows(rows, config)
    batch = config["training"]["batch_size"]
    _, spans = _predictions(torch, models["span"], inputs["span"], batch)
    values = _predict_rank(torch, models["rank"], inputs["rank"], batch, torch.device("cpu"), structured=True)
    ranking = [{"id": row["id"], "score": score} for row, score in zip(rows["rank"], values, strict=True)]
    return summarize(rows, {"span": {"predictions": [{"id": key, **value} for key, value in spans.items()]},
                            "rank": {"predictions": ranking}}, sources, target=target)


def evaluate(*, candidate, candidate_sha256, candidate_train_sha256, candidate_config_sha256,
             reference, reference_sha256, reference_train_sha256, reference_config_sha256,
             holdout, holdout_sha256):
    _require_host("runpod-cpu", [candidate, reference], holdout)
    start = time.monotonic()
    for digest in (candidate_sha256, candidate_train_sha256, candidate_config_sha256, reference_sha256,
                   reference_train_sha256, reference_config_sha256, holdout_sha256):
        _check_sha256(digest)
    rows, sources = _read_holdout(holdout, holdout_sha256)

    import torch

    if torch.cuda.is_available() or torch.cuda.device_count():
        raise RuntimeError("Use a CPU-only Runpod Pod for evaluation")
    torch.set_num_threads(1)
    reports = {
        "candidate": _score(torch, rows, sources, candidate, candidate_sha256,
                            candidate_train_sha256, candidate_config_sha256),
        "reference": _score(torch, rows, sources, reference, reference_sha256,
                            reference_train_sha256, reference_config_sha256),
    }
    return {"recorded_at": datetime.now(timezone.utc).isoformat(), "scope": "held_out_synthetic_text",
            "candidate_sha256": candidate_sha256, "reference_sha256": reference_sha256,
            "candidate_train_manifest_sha256": candidate_train_sha256,
            "reference_train_manifest_sha256": reference_train_sha256,
            "candidate_config_sha256": candidate_config_sha256,
            "reference_config_sha256": reference_config_sha256,
            "holdout_manifest_sha256": holdout_sha256, "target": TARGET, "span_decoder": "joint",
            "reports": reports, "production_accuracy_established": False,
            "runtime": {"device": "cpu", "torch": torch.__version__,
                        "elapsed_seconds": round(time.monotonic() - start, 3)}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("candidate", "reference", "holdout"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    for name in ("candidate-sha256", "candidate-train-sha256", "candidate-config-sha256",
                 "reference-sha256", "reference-train-sha256", "reference-config-sha256", "holdout-sha256"):
        parser.add_argument(f"--{name}", required=True)
    print(json.dumps(evaluate(**vars(parser.parse_args())), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
