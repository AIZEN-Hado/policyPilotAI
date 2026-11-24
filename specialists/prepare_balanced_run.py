"""Prepare a controlled extraction experiment from the frozen CPU runtime."""

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import shutil
import tempfile

from .artifacts import SOURCE_MAX_BYTES, package_directory, sha256_file, verify_manifest, write_manifest
from .balanced_field_cases import balanced_rows
from .prepare import ROOT, encoded
from .prepare_quality_run import _unpack
from .prepare_research_run import _write_rows
from .run import verify_data
from .runtime import DATA_PATH, _encode_span, _read_rows, _validate_training
from .structured import candidate_supervision


VERSION = "specialists-balanced-fields-v1"
PRIOR = "specialists-public-policy-v1-cpu"
COMPARISON_MODULES = ("evaluate.py", "evaluate_quality_run.py", "joint_selection.py",
                      "diagnose_quality_validation.py", "evaluate_public_policy_run.py",
                      "compare_balanced_validation.py")


def prepare(root=ROOT, *, output=None):
    root = Path(root)
    research = root / "artifacts/research"
    previous = research / PRIOR
    verify_manifest(previous)
    prior = json.loads((previous / "preparation.json").read_bytes())
    output = Path(output) if output is not None else research / VERSION
    output.parent.mkdir(parents=True, exist_ok=True)
    added = balanced_rows()
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        staging = Path(temporary)
        runtime = staging / "runtime"
        source = prior["runtime"]
        _unpack(previous / source["path"], runtime, source["sha256"])
        data = runtime / DATA_PATH
        if verify_data(data) != prior["training_manifest_sha256"]:
            raise ValueError("The source training data differs from its preparation receipt")
        manifest = json.loads((data / "manifest.json").read_bytes())
        config_path = runtime / "specialists/config.json"
        if sha256_file(config_path) != prior["config_sha256"]:
            raise ValueError("The source configuration differs from its preparation receipt")
        config = json.loads(config_path.read_bytes())
        rows = {split: {} for split in added}
        labels_added = {}
        for split, new_rows in added.items():
            for task in ("span", "rank"):
                filename = f"{split}-{task}.jsonl"
                rows[split][task] = _read_rows(data / filename, task, manifest["files"][filename])
            for row in new_rows:
                candidate_supervision(row, _encode_span(row, config["span"]))
            labels_added[split] = dict(Counter(label["label"] for row in new_rows for label in row["spans"]))
            rows[split]["span"].extend(new_rows)
        if ({r["text"] for x in rows["train"].values() for r in x}
                & {r["text"] for x in rows["validation"].values() for r in x}):
            raise ValueError("Training and validation repeat a document")
        if ({r["query"] for r in rows["train"]["rank"]}
                & {r["query"] for r in rows["validation"]["rank"]}):
            raise ValueError("Training and validation repeat a ranking query")
        shutil.rmtree(data)
        files, counts = _write_rows(data, rows, ("train", "validation"))
        for split in rows:
            filename = f"{split}-rank.jsonl"
            if files[filename] != manifest["files"][filename]:
                raise ValueError("The controlled experiment changed ranking data")
        (data / "manifest.json").write_bytes(encoded({**manifest, "files": files, "splits": counts,
            "dataset_version": VERSION, "previous_training_manifest_sha256": prior["training_manifest_sha256"]}))
        fingerprint = verify_data(data)
        training = config["training"]
        training["max_steps"] = math.ceil(counts["train"]["span"] / training["batch_size"]) * training["epochs"]
        _validate_training(training)
        config_path.write_bytes(encoded(config))
        for name in COMPARISON_MODULES:
            shutil.copyfile(root / "specialists" / name, runtime / "specialists" / name)
        write_manifest(runtime, metadata={"kind": "runtime_source_and_synthetic_train_validation",
                       "experiment": VERSION, "dataset_manifest_sha256": fingerprint}, max_bytes=SOURCE_MAX_BYTES)
        release = staging / VERSION
        release.mkdir()
        filename = f"policypilot-{VERSION}-runtime.tar.gz"
        archive = package_directory(runtime, release / filename, max_bytes=SOURCE_MAX_BYTES)
        report = {"experiment": VERSION, "runtime": {"path": filename, "sha256": archive["sha256"],
                  "bytes": archive["bytes"]}, "previous_runtime_sha256": source["sha256"],
                  "training_manifest_sha256": fingerprint, "config_sha256": sha256_file(config_path),
                  "counts": counts, "additional_span_rows": {split: len(new) for split, new in added.items()},
                  "additional_span_labels": labels_added, "planned_steps": {"span": training["max_steps"],
                  "rank": prior["training_steps"]["rank"]}, "holdout_included": False,
                  "model_execution_performed": False}
        (release / "preparation.json").write_bytes(encoded(report))
        write_manifest(release, metadata={"experiment": VERSION})
        if output.exists():
            if verify_manifest(output) != verify_manifest(release):
                raise ValueError("Existing balanced experiment differs from this package")
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
