"""Package the quality training experiment and the reserved evaluation inputs separately."""

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import shutil
import tarfile
import tempfile

from .artifacts import SOURCE_MAX_BYTES, package_directory, sha256_file, verify_archive, verify_manifest, write_manifest
from .contracts import TASKS
from .features import encode_span
from .models import parameter_estimate
from .prepare import ROOT, encoded
from .prepare_date_run import ORIGINAL_HOLDOUT_SHA256, PRIOR
from .rank_quality_cases import rank_training_rows
from .run import verify_data
from .runtime import DATA_PATH, _read_rows, _validate_training
from .span_quality_cases import span_training_rows
from .structured import candidate_supervision, rank_groups


VERSION = "specialists-quality-v1"
BASE = Path("artifacts/research/specialists-date-diversity-v1")
BASE_RUNTIME_SHA256 = "029b89e167d765a013313aaa6f859974d7d1fd928eb2c1ddcf169414b6e5497c"
BASE_DATA_SHA256 = "33d9e8d0a8a46922f75b7d165165f6138876c0372bc0c1bb99c024a2fc2d7b7c"
HOLDOUT_SHA256 = "d0c6f7d3fc2b6c45833f17b1176876df9dece5d6e48e7cb1c43688d5675b20e0"
RUNTIME_UPDATES = ("features.py", "runtime.py", "structured.py", "span_context.py")


def _unpack(archive, output, expected_sha256):
    check = verify_archive(archive, max_bytes=SOURCE_MAX_BYTES)
    if check["sha256"] != expected_sha256:
        raise ValueError("Frozen input archive differs from its receipt")
    output.mkdir()
    with tarfile.open(archive) as bundle:
        bundle.extractall(output, filter="data")
    if verify_manifest(output, max_bytes=SOURCE_MAX_BYTES) != check["manifest"]:
        raise ValueError("Unpacked inventory differs from the original archive")


def _augment(runtime):
    data = runtime / DATA_PATH
    if verify_data(data) != BASE_DATA_SHA256:
        raise ValueError("Base training manifest differs from the date-diversity run")
    data_manifest_path = data / "manifest.json"
    data_manifest = json.loads(data_manifest_path.read_bytes())
    files = data_manifest["files"]
    original = {name: _read_rows(data / name, name.split("-")[1].removesuffix(".jsonl"), spec)
                for name, spec in files.items()}
    additions = {"span": span_training_rows(), "rank": rank_training_rows()}
    prior = [row for rows in original.values() for row in rows]
    added = additions["span"] + additions["rank"]
    for key in ("id", "case_id", "family", "text"):
        if {row[key] for row in prior} & {row[key] for row in added}:
            raise ValueError(f"Quality examples reuse an existing {key}")
    if len({row["id"] for row in added}) != len(added):
        raise ValueError("Quality examples have duplicate IDs")

    config_path = runtime / "specialists/config.json"
    config = json.loads(config_path.read_bytes())
    config["span"]["contextual_values"] = True
    config["rank"].update(feature_version=2, features=384, hidden_size=64)
    spans = original["train-span.jsonl"] + additions["span"]
    for row in spans:
        candidate_supervision(row, encode_span(row, config["span"]))
    groups = rank_groups([(row, None) for row in original["train-rank.jsonl"] + additions["rank"]])
    training = config["training"]
    steps = {task: math.ceil(count / training["batch_size"]) * training["epochs"]
             for task, count in (("span", len(spans)), ("rank", len(groups)))}
    training["max_steps"] = max(steps.values())
    _validate_training(training)
    parameters = parameter_estimate(config)
    config_path.write_bytes(encoded(config))

    for task in TASKS:
        name = f"train-{task}.jsonl"
        path = data / name
        with path.open("ab") as stream:
            for row in additions[task]:
                stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True).encode() + b"\n")
        count = len(original[name]) + len(additions[task])
        files[name] = {"bytes": path.stat().st_size, "sha256": sha256_file(path), "rows": count}
        data_manifest["splits"]["train"][task] = count
    data_manifest["dataset_version"] = VERSION
    data_manifest["sources"]["previous_training_manifest_sha256"] = BASE_DATA_SHA256
    data_manifest_path.write_bytes(encoded(data_manifest))
    return {
        "training_manifest_sha256": verify_data(data),
        "config_sha256": sha256_file(config_path),
        "counts": data_manifest["splits"],
        "training_steps": steps,
        "parameters": parameters,
        "additional_rows": {task: len(rows) for task, rows in additions.items()},
        "additional_span_labels": dict(Counter(item["label"] for row in additions["span"] for item in row["spans"])),
        "additional_families": {task: len({row["family"] for row in rows}) for task, rows in additions.items()},
        "unchanged_validation_sha256": {name: spec["sha256"] for name, spec in files.items()
                                       if name.startswith("validation-")},
    }


def prepare(*, root=ROOT, output=None):
    root = Path(root)
    output = Path(output) if output is not None else root / "artifacts/research" / VERSION
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        staging = Path(temporary)
        runtime = staging / "runtime"
        reference = staging / "reference"
        _unpack(root / BASE / "policypilot-specialists-date-diversity-v1-runtime.tar.gz", runtime, BASE_RUNTIME_SHA256)
        _unpack(root / PRIOR / "policypilot-specialists-precision-v1-evaluation.tar.gz", reference,
                ORIGINAL_HOLDOUT_SHA256)
        holdout = reference / "holdout"
        if sha256_file(holdout / "manifest.json") != HOLDOUT_SHA256:
            raise ValueError("Reserved holdout manifest differs from its receipt")

        source = root / "specialists"
        runtime_source = runtime / "specialists"
        for name in RUNTIME_UPDATES:
            shutil.copyfile(source / name, runtime_source / name)
        report = _augment(runtime)
        fingerprint = report["training_manifest_sha256"]
        write_manifest(runtime, metadata={"experiment": VERSION, "dataset_manifest_sha256": fingerprint,
                       "kind": "runtime_source_and_synthetic_train_validation"}, max_bytes=SOURCE_MAX_BYTES)
        evaluation = staging / "evaluation"
        eval_source = evaluation / "specialists"
        shutil.copytree(runtime_source, eval_source)
        for name in ("evaluate.py", "evaluate_quality_run.py"):
            shutil.copyfile(source / name, eval_source / name)
        shutil.copytree(holdout, evaluation / "holdout")
        write_manifest(evaluation, metadata={"experiment": VERSION, "holdout_manifest_sha256": HOLDOUT_SHA256,
                       "kind": "synthetic_quality_evaluation"}, max_bytes=SOURCE_MAX_BYTES)

        release = staging / VERSION
        release.mkdir()
        for label, directory in (("runtime", runtime), ("evaluation", evaluation)):
            path = f"policypilot-{VERSION}-{label}.tar.gz"
            receipt = package_directory(directory, release / path, max_bytes=SOURCE_MAX_BYTES)
            report[label] = {"path": path, "sha256": receipt["sha256"], "bytes": receipt["bytes"]}
        report.update(experiment=VERSION, holdout_manifest_sha256=HOLDOUT_SHA256,
                      previous_training_manifest_sha256=BASE_DATA_SHA256, model_execution_performed=False)
        (release / "preparation.json").write_bytes(encoded(report))
        write_manifest(release, metadata={"experiment": VERSION})
        inventory = verify_manifest(release)
        if output.exists() or output.is_symlink():
            if verify_manifest(output) != inventory:
                raise ValueError("Existing quality experiment differs from the prepared bundle")
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
