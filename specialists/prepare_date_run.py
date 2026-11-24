"""Package a controlled comparison with additional synthetic date contexts."""

import argparse
from collections import Counter
from hashlib import sha256
import json
import math
from pathlib import Path
import tarfile
import tempfile

from .artifacts import SOURCE_MAX_BYTES, package_directory, sha256_file, verify_archive, verify_manifest, write_manifest
from .date_cases import date_training_rows
from .features import encode_span
from .prepare import ROOT, encoded
from .run import verify_data
from .runtime import DATA_PATH, _read_rows, _validate_training
from .structured import candidate_supervision, rank_groups


VERSION = "specialists-date-diversity-v1"
PRIOR = Path("artifacts/research/specialists-precision-v1")
PRIOR_RUNTIME_SHA256 = "304b02a19ba14961696fead2f656558de248444ca33a2dedfa1d64423a70479a"
PRIOR_DATA_SHA256 = "3a44bf598e8190bb4e81f972f2891c5fd688d1334b60196f9e72258ca6329dc3"
ORIGINAL_HOLDOUT_SHA256 = "11b876d0d9a4df846ac6e75b0f2931ce0f54f7b16d04a14249352a01dcb02244"
TRAIN_FILE = "train-span.jsonl"


def _augment(runtime):
    data = runtime / DATA_PATH
    if verify_data(data) != PRIOR_DATA_SHA256:
        raise ValueError("Extracted dataset differs from the frozen precision inputs")
    stamp = data / "manifest.json"
    original = json.loads(stamp.read_bytes())
    files = original["files"]
    existing = _read_rows(data / TRAIN_FILE, "span", files[TRAIN_FILE])
    validation = _read_rows(data / "validation-span.jsonl", "span", files["validation-span.jsonl"])
    rank_train = _read_rows(data / "train-rank.jsonl", "rank", files["train-rank.jsonl"])
    rank_validation = _read_rows(data / "validation-rank.jsonl", "rank", files["validation-rank.jsonl"])
    added = date_training_rows()
    other = existing + validation + rank_train + rank_validation
    for field in ("id", "case_id", "family", "text"):
        if {row[field] for row in added} & {row[field] for row in other}:
            raise ValueError(f"Additional date examples reuse an existing {field}")

    config_path = runtime / "specialists/config.json"
    config = json.loads(config_path.read_bytes())
    for row in added:
        candidate_supervision(row, encode_span(row, config["span"]))
    train_path = data / TRAIN_FILE
    new_rows = b"".join((json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode() for row in added)
    with train_path.open("ab") as stream:
        stream.write(new_rows)
    files[TRAIN_FILE] = {"sha256": sha256_file(train_path), "bytes": train_path.stat().st_size,
                         "rows": len(existing) + len(added)}
    original["splits"]["train"]["span"] = files[TRAIN_FILE]["rows"]
    original["dataset_version"] = VERSION
    original["sources"]["prior_training_manifest_sha256"] = PRIOR_DATA_SHA256
    original["sources"]["date_augmentation_sha256"] = sha256(new_rows).hexdigest()
    stamp.write_bytes(encoded(original))
    train_digest = verify_data(data)

    training = config["training"]
    rank_group_count = len(rank_groups([(row, None) for row in rank_train]))
    steps = {task: math.ceil(count / training["batch_size"]) * training["epochs"]
             for task, count in (("span", files[TRAIN_FILE]["rows"]), ("rank", rank_group_count))}
    training["max_steps"] = max(steps.values())
    _validate_training(training)
    config_path.write_bytes(encoded(config))
    return {
        "training_manifest_sha256": train_digest,
        "config_sha256": sha256_file(config_path),
        "counts": original["splits"],
        "training_steps": steps,
        "added_span_rows": len(added),
        "added_layout_families": len({row["family"] for row in added}),
        "added_gold_spans": dict(Counter(span["label"] for row in added for span in row["spans"])),
        "added_without_current_stay_dates": sum(not row["spans"] for row in added),
        "unchanged_data_sha256": {name: item["sha256"] for name, item in files.items() if name != TRAIN_FILE},
    }


def prepare(*, root=ROOT, output=None):
    root = Path(root)
    prior = root / PRIOR
    runtime_archive = prior / "policypilot-specialists-precision-v1-runtime.tar.gz"
    holdout_archive = prior / "policypilot-specialists-precision-v1-evaluation.tar.gz"
    verified = verify_archive(runtime_archive, max_bytes=SOURCE_MAX_BYTES)
    if verified["sha256"] != PRIOR_RUNTIME_SHA256 or sha256_file(holdout_archive) != ORIGINAL_HOLDOUT_SHA256:
        raise ValueError("Frozen precision archives differ from their verified receipts")

    output = Path(output) if output is not None else root / "artifacts/research" / VERSION
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        staging = Path(temporary)
        runtime = staging / "runtime"
        runtime.mkdir()
        with tarfile.open(runtime_archive) as bundle:
            bundle.extractall(runtime, filter="data")
        if verify_manifest(runtime, max_bytes=SOURCE_MAX_BYTES) != verified["manifest"]:
            raise ValueError("Extracted runtime differs from its archive")
        report = _augment(runtime)
        write_manifest(runtime, metadata={
            "kind": "runtime_source_and_synthetic_train_validation",
            "experiment": VERSION,
            "dataset_manifest_sha256": report["training_manifest_sha256"],
            "prior_runtime_sha256": PRIOR_RUNTIME_SHA256,
            "weights_included": False,
        }, max_bytes=SOURCE_MAX_BYTES)
        release = staging / VERSION
        release.mkdir()
        archive_name = f"policypilot-{VERSION}-runtime.tar.gz"
        artifact = package_directory(runtime, release / archive_name, max_bytes=SOURCE_MAX_BYTES)
        report.update(
            experiment=VERSION,
            runtime={"path": archive_name, "sha256": artifact["sha256"], "bytes": artifact["bytes"]},
            reserved_holdout_archive_sha256=ORIGINAL_HOLDOUT_SHA256,
            prior_training_manifest_sha256=PRIOR_DATA_SHA256,
            model_execution_performed=False,
        )
        (release / "preparation.json").write_bytes(encoded(report))
        write_manifest(release, metadata={"experiment": VERSION})
        inventory = verify_manifest(release)
        if output.exists() or output.is_symlink():
            if verify_manifest(output) != inventory:
                raise ValueError("Existing date experiment differs from the prepared bundle")
        else:
            release.rename(output)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(output=args.output), indent=2))


if __name__ == "__main__":
    main()
