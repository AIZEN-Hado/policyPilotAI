"""Compare the supervised teacher and self-trained student on a frozen holdout."""

import argparse
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tarfile

from .evaluate import load_verified_checkpoint, restore_models
from .evaluate_public_policy_run import score_models
from .evaluate_quality_run import _check_sha256, _read_holdout, _require_host
from .models import build_models
from .self_learning import TEACHER_FILE


TARGET = 0.95


def compare(archive, archive_sha256, training_manifest_sha256, config_sha256, holdout, holdout_sha256,
            previous=None):
    checkpoints = [archive] + ([previous[0]] if previous else [])
    _require_host("runpod-cpu", checkpoints, holdout)
    for digest in (archive_sha256, training_manifest_sha256, config_sha256, holdout_sha256,
                   *(previous[1:] if previous else ())):
        _check_sha256(digest)
    rows, sources = _read_holdout(holdout, holdout_sha256)

    import torch

    if torch.cuda.is_available() or torch.cuda.device_count():
        raise RuntimeError("Use hosted CPU for self-training evaluation")
    torch.set_num_threads(2)
    config, weights = load_verified_checkpoint(archive, archive_sha256, training_manifest_sha256,
                                               config_sha256=config_sha256)
    with tarfile.open(archive, "r:gz") as bundle:
        reload = json.load(bundle.extractfile("reload.json"))
        metadata = json.load(bundle.extractfile("metadata.json"))["self_training"]
        teacher_bytes = bundle.extractfile(TEACHER_FILE).read(metadata["teacher_bytes"] + 1)
    if reload.get("teacher_predictions_match") is not True or len(teacher_bytes) != metadata["teacher_bytes"]:
        raise ValueError("Supervised baseline failed independent reload verification")

    teacher = build_models(torch, config)
    baseline_weights = torch.load(io.BytesIO(teacher_bytes), map_location="cpu", weights_only=True)
    for task, model in teacher.items():
        model.load_state_dict(baseline_weights[task], strict=True)
    student = restore_models(torch, config, weights)
    reports = {label: score_models(torch, rows, sources, config, models, target=TARGET)
               for label, models in (("supervised", teacher), ("self_trained", student))}
    if previous:
        path, checksum, manifest, previous_config = previous
        previous_config, previous_weights = load_verified_checkpoint(path, checksum, manifest,
                                                                     config_sha256=previous_config)
        reports["previous"] = score_models(torch, rows, sources, previous_config,
                                          restore_models(torch, previous_config, previous_weights), target=TARGET)
    return {"scope": "held_out_synthetic_text", "target": TARGET, "recorded_at": datetime.now(timezone.utc).isoformat(),
            "archive_sha256": archive_sha256, "training_manifest_sha256": training_manifest_sha256,
            "config_sha256": config_sha256, "holdout_manifest_sha256": holdout_sha256,
            "previous_archive_sha256": previous[1] if previous else None,
            "independent_checkpoint_reload_verified": True, "self_training": metadata, "reports": reports,
            "production_accuracy_established": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "holdout"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    for name in ("archive-sha256", "training-manifest-sha256", "config-sha256", "holdout-sha256"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--previous", nargs=4, metavar=("ARCHIVE", "SHA", "TRAIN_SHA", "CONFIG_SHA"))
    print(json.dumps(compare(**vars(parser.parse_args())), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
