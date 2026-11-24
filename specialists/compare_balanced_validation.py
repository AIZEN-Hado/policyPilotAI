"""Compare two checkpoints on the same balanced-run development inputs."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from .evaluate_public_policy_run import _score
from .evaluate_quality_run import _check_sha256, _require_host
from .run import verify_data
from .runtime import DATA_PATH, _read_rows


def compare(candidate, reference, manifest_sha256):
    _require_host("runpod-cpu", [candidate[0], reference[0]], Path("/tmp"))
    data = Path(__file__).resolve().parents[1] / DATA_PATH
    if verify_data(data) != manifest_sha256:
        raise ValueError("The validation files must come from the pinned balanced-run dataset")
    files = json.loads((data / "manifest.json").read_bytes())["files"]
    rows = {task: _read_rows(data / name, task, files[name]) for task, name in
            (("span", "validation-span.jsonl"), ("rank", "validation-rank.jsonl"))}
    sources = {row["family"]: ("balanced_development" if row["family"].startswith("balanced-fields-")
                               else "previous_development") for values in rows.values() for row in values}

    import torch

    if torch.cuda.is_available() or torch.cuda.device_count():
        raise RuntimeError("Use a CPU-only Runpod Pod for the comparison")
    torch.set_num_threads(1)
    reports = {}
    for label, (archive, checksum, training_sha256, config_sha256) in (("candidate", candidate),
                                                                    ("reference", reference)):
        for digest in (checksum, training_sha256, config_sha256):
            _check_sha256(digest)
        score = _score(torch, rows, sources, Path(archive), checksum, training_sha256, config_sha256)
        for group in (score, *score["by_source"].values()):
            group.pop("synthetic_target_met", None)
            group.pop("target_failures", None)
        reports[label] = {"checkpoint_sha256": checksum, "config_sha256": config_sha256,
                          "training_manifest_sha256": training_sha256, "development": score}
    return {"recorded_at": datetime.now(timezone.utc).isoformat(), "scope": "development_only",
            "development_manifest_sha256": manifest_sha256, "span_decoder": "joint", "reports": reports}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", nargs=4, required=True, metavar=("ARCHIVE", "SHA", "TRAIN_SHA", "CONFIG_SHA"))
    parser.add_argument("--reference", nargs=4, required=True, metavar=("ARCHIVE", "SHA", "TRAIN_SHA", "CONFIG_SHA"))
    parser.add_argument("--manifest-sha256", required=True)
    print(json.dumps(compare(**vars(parser.parse_args())), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
