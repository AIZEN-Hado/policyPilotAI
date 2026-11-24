"""Package structured specialist training and a separate synthetic holdout."""

import argparse
import json
import math
from pathlib import Path
import shutil
import tempfile

from .artifacts import SOURCE_MAX_BYTES, package_directory, sha256_file, verify_manifest, write_manifest
from .contracts import SPLITS, TASKS, validate_corpus
from .evaluate_precision_run import TARGET, TRAIN_MANIFEST_SHA256, VERSION
from .features import encode_span
from .precision_cases import precision_holdout
from .prepare import ROOT, RUNTIME_FILES, encoded
from .prepare_research_run import BASELINE_DATA, _verify_text_isolation, _write_rows
from .run import verify_data
from .runtime import _read_rows, _validate_training
from .structured import candidate_supervision, rank_groups


TRAIN_DATA = Path("artifacts/research/specialists-research-v1/train-validation")
SOURCE_FILES = (*RUNTIME_FILES, "structured.py")


def prepare(root=ROOT, output=None):
    root = Path(root)
    output = Path(output) if output is not None else root / "artifacts/research" / VERSION
    data = root / TRAIN_DATA
    fingerprint = verify_data(data)
    if fingerprint != TRAIN_MANIFEST_SHA256:
        raise ValueError("Train and validation data differ from the reviewed research inputs")
    manifest = json.loads((data / "manifest.json").read_bytes())
    corpus = {
        split: {task: _read_rows(data / name, task, manifest["files"][name])
                for task in TASKS for name in [f"{split}-{task}.jsonl"]}
        for split in SPLITS if split != "test"
    }
    corpus["test"] = precision_holdout()
    validate_corpus(corpus)
    _verify_text_isolation(corpus)
    config = json.loads((root / "specialists/config.json").read_bytes())
    training = config["training"]
    training.update(structured_objectives=True, epochs=10, max_steps=800)
    _validate_training(training)
    span = corpus["train"]["span"]
    for row in span:
        candidate_supervision(row, encode_span(row, config["span"]))
    groups = rank_groups([(row, None) for row in corpus["train"]["rank"]])
    training_steps = {
        task: math.ceil(units / training["batch_size"]) * training["epochs"]
        for task, units in (("span", len(span)), ("rank", len(groups)))
    }
    if max(training_steps.values()) > training["max_steps"]:
        raise ValueError("Training step cap is too low for complete passes")

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        staging = Path(temporary)
        release = staging / VERSION
        release.mkdir()
        runtime = staging / "runtime"
        source = runtime / "specialists"
        source.mkdir(parents=True)
        for name in SOURCE_FILES:
            shutil.copyfile(root / "specialists" / name, source / name)
        (source / "config.json").write_bytes(encoded(config))
        shutil.copytree(data, runtime / BASELINE_DATA)
        if verify_data(runtime / BASELINE_DATA) != fingerprint:
            raise ValueError("Copied training and validation data differ from the reviewed inputs")
        write_manifest(runtime, metadata={
            "kind": "runtime_source_and_synthetic_train_validation",
            "experiment": VERSION,
            "dataset_manifest_sha256": fingerprint,
            "weights_included": False,
        }, max_bytes=SOURCE_MAX_BYTES)
        runtime_name = f"policypilot-{VERSION}-runtime.tar.gz"
        runtime_receipt = package_directory(runtime, release / runtime_name, max_bytes=SOURCE_MAX_BYTES)

        evaluation = staging / "evaluation"
        eval_source = evaluation / "specialists"
        shutil.copytree(source, eval_source)
        for name in ("evaluate.py", "evaluate_precision_run.py"):
            shutil.copyfile(root / "specialists" / name, eval_source / name)
        holdout = evaluation / "holdout"
        test_files, counts = _write_rows(holdout, corpus, ("test",))
        (holdout / "manifest.json").write_bytes(encoded({
            "schema_version": 1,
            "experiment": VERSION,
            "split": "test",
            "synthetic_only": True,
            "training_manifest_sha256": fingerprint,
            "files": test_files,
        }))
        holdout_sha256 = sha256_file(holdout / "manifest.json")
        write_manifest(evaluation, metadata={"kind": "synthetic_precision_evaluation", "experiment": VERSION})
        evaluation_name = f"policypilot-{VERSION}-evaluation.tar.gz"
        evaluation_receipt = package_directory(evaluation, release / evaluation_name, max_bytes=SOURCE_MAX_BYTES)
        if sha256_file(data / "manifest.json") != fingerprint:
            raise ValueError("Training and validation manifest changed during packaging")

        report = {
            "experiment": VERSION,
            "training_manifest_sha256": fingerprint,
            "config_sha256": sha256_file(source / "config.json"),
            "holdout_manifest_sha256": holdout_sha256,
            "training_steps": training_steps,
            "training_epochs_per_task": training["epochs"],
            "counts": {**manifest["splits"], **counts},
            "runtime": {"path": runtime_name, "sha256": runtime_receipt["sha256"]},
            "evaluation": {"path": evaluation_name, "sha256": evaluation_receipt["sha256"]},
            "synthetic_target": TARGET,
            "model_execution_performed": False,
        }
        (release / "preparation.json").write_bytes(encoded(report))
        write_manifest(release, metadata={"experiment": VERSION})
        inventory = verify_manifest(release)
        if output.exists() or output.is_symlink():
            if verify_manifest(output) != inventory:
                raise ValueError("Existing precision experiment differs from the prepared bundle")
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
