"""Score the frozen English synthetic test split on hosted Colab CPU."""

from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import resource
import tarfile
import time

from .artifacts import sha256_file, verify_archive
from .models import MAX_WEIGHT_BYTES, build_models, parameter_estimate
from .runtime import ARCHITECTURES, _evaluate, _read_split, _run_baseline


ARCHIVE_SHA256 = "3be489352f797be201e069f8dc33d77ca4e145eec257cf41a9238d865805add2"
ARCHIVE_BYTES = 2325184
TEST_MANIFEST_SHA256 = "e3483372fa4500e02be02fd6cdb7b323c925a56954141cf59612fdd95ecd422a"
TRAIN_MANIFEST_SHA256 = "488fad1d89d8508bd8712be9afd6e8d415da2bdf7982f9413c0343596c502739"


def require_hosted_colab():
    if not os.environ.get("COLAB_RELEASE_TAG") or not Path("/content").is_dir():
        raise RuntimeError("Select a hosted Google Colab runtime before running the evaluation.")


def load_verified_checkpoint(archive, archive_sha256, train_manifest_sha256, archive_bytes=None, *,
                             config_sha256=None):
    from .runtime import _feature_spec

    archive = Path(archive)
    if ((archive_bytes is not None and archive.stat().st_size != archive_bytes)
            or sha256_file(archive) != archive_sha256):
        raise ValueError("Checkpoint archive size or SHA-256 differs from the R2 receipt.")
    manifest = verify_archive(archive)["manifest"]
    if (manifest["metadata"].get("trained") is not True
            or manifest["metadata"].get("kind") != "remote_specialist_run"
            or manifest["metadata"].get("dataset_manifest_sha256") != train_manifest_sha256):
        raise ValueError("This archive does not match the completed training run.")
    entries = {item["path"]: item for item in manifest["files"]}
    with tarfile.open(archive, "r:gz") as bundle:
        with bundle.extractfile("metadata.json") as payload:
            metadata = json.load(payload)
        with bundle.extractfile("reload.json") as payload:
            reload = json.load(payload)
        config = metadata["config"]
        if (metadata.get("schema_version") != 1
                or metadata.get("architectures") != ARCHITECTURES
                or metadata.get("features") != _feature_spec(config)
                or metadata.get("parameters") != parameter_estimate(config)
                or metadata["input_fingerprints"].get("dataset_manifest_sha256") != train_manifest_sha256
                or (config_sha256 is not None
                    and metadata["input_fingerprints"].get("config_sha256") != config_sha256)
                or reload.get("passed") is not True
                or reload.get("predictions_match") is not True
                or reload.get("input_fingerprints") != metadata["input_fingerprints"]):
            raise ValueError("Architecture, training provenance or checkpoint reload does not match.")
        weights = {}
        for task in ("span", "rank"):
            name = f"{task}.pt"
            checkpoint = {"path": name, **{key: entries[name][key] for key in ("bytes", "sha256")}}
            if metadata["weights"][task] != checkpoint:
                raise ValueError(f"Checkpoint fingerprint differs for {task}.")
            with bundle.extractfile(name) as payload:
                weights[task] = payload.read()
        if sum(map(len, weights.values())) > min(config["max_weight_bytes"], MAX_WEIGHT_BYTES):
            raise ValueError("Checkpoints exceed the weight budget.")
    return config, weights


def restore_models(torch, config, weights):
    models = build_models(torch, config)
    for task, model in models.items():
        state = torch.load(io.BytesIO(weights[task]), map_location="cpu", weights_only=True)
        model.load_state_dict(state, strict=True)
    return models


def evaluate(archive, test_data):
    require_hosted_colab()
    started = time.monotonic()
    test_data = Path(test_data)
    stamp = test_data / "manifest.json"
    if sha256_file(stamp) != TEST_MANIFEST_SHA256:
        raise ValueError("The held-out test manifest differs from the frozen copy.")
    test_manifest = json.loads(stamp.read_text())
    if test_manifest.get("split") != "test" or test_manifest.get("synthetic_only") is not True:
        raise ValueError("This evaluation requires the synthetic test split.")
    files = {f"test-{task}.jsonl": {
        **test_manifest["files"][f"test-{task}.jsonl"], "rows": test_manifest["counts"][task]
    } for task in ("span", "rank")}
    config, weights = load_verified_checkpoint(archive, ARCHIVE_SHA256, TRAIN_MANIFEST_SHA256, ARCHIVE_BYTES)
    data = _read_split(test_data, "test", config, files)
    import torch

    torch.set_num_threads(1)
    models = restore_models(torch, config, weights)
    baseline = _run_baseline(data)
    trained = _evaluate(torch, models, data, config["training"]["batch_size"], torch.device("cpu"))
    comparison = {task: {"rules": baseline[task]["metrics"], "network": trained[task]["metrics"]}
                  for task in ("span", "rank")}
    return {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "archive_sha256": ARCHIVE_SHA256,
        "test_manifest_sha256": TEST_MANIFEST_SHA256,
        "split": "held_out_synthetic_english",
        "families": sorted({row["family"] for examples in data.values() for row, _ in examples}),
        "metrics": comparison,
        "model_improves_span_f1": comparison["span"]["network"]["exact_span"]["f1"]
        > comparison["span"]["rules"]["exact_span"]["f1"],
        "model_improves_rank_top1": comparison["rank"]["network"]["group_top1_accuracy"]
        > comparison["rank"]["rules"]["group_top1_accuracy"],
        "runtime": {"device": "cpu", "torch": torch.__version__,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024},
        "limitations": test_manifest["limitations"],
    }
