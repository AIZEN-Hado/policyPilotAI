"""Prepare a licensed public ranking and synthetic room-cap experiment."""

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import shutil
import tempfile

from .artifacts import SOURCE_MAX_BYTES, package_directory, sha256_file, verify_manifest, write_manifest
from .contracts import TASKS, validate_corpus
from .prepare import ROOT, encoded
from .prepare_quality_run import VERSION as PRIOR, _unpack
from .prepare_research_run import _verify_text_isolation, _write_rows
from .public_policy_data import SOURCE, public_rank_rows
from .room_cap_data import room_rows
from .run import verify_data
from .runtime import DATA_PATH, _encode_span, _read_rows, _validate_training
from .structured import candidate_supervision, rank_groups


VERSION = "specialists-public-policy-v1"
EVAL_MODULES = ("evaluate.py", "evaluate_quality_run.py", "diagnose_quality_validation.py",
                "joint_selection.py", "evaluate_public_policy_run.py")


def prepare(*, root=ROOT, output=None, cpu=False):
    root = Path(root)
    version_name = f"{VERSION}-cpu" if cpu else VERSION
    research = root / "artifacts/research"
    previous = research / PRIOR
    verify_manifest(previous)
    base = json.loads((previous / "preparation.json").read_bytes())
    reference = json.loads((research / f"{PRIOR}-candidate-run.json").read_bytes())
    if any(base[key] != reference["inputs"][key] for key in ("training_manifest_sha256", "config_sha256")):
        raise ValueError("Reference checkpoint and source bundle differ")
    output = Path(output) if output is not None else research / version_name
    output.parent.mkdir(parents=True, exist_ok=True)
    train, dev, test, source = public_rank_rows(root / SOURCE)
    license_text = source.pop("license_text")
    additions = room_rows()
    for split, rows in (("train", train), ("validation", dev), ("test", test)):
        additions[split]["rank"].extend(rows)
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        staging = Path(temporary)
        frozen, runtime, evaluation = (staging / name for name in ("original", "runtime", "evaluation"))
        original = base["runtime"]
        _unpack(previous / original["path"], frozen, original["sha256"])
        frozen_data = frozen / DATA_PATH
        if verify_data(frozen_data) != base["training_manifest_sha256"]:
            raise ValueError("Verified training source differs from prior experiment")
        old_manifest = json.loads((frozen_data / "manifest.json").read_bytes())
        corpus = {"test": additions["test"]}
        for split in ("train", "validation"):
            corpus[split] = {}
            for task in TASKS:
                filename = f"{split}-{task}.jsonl"
                corpus[split][task] = (
                    _read_rows(frozen_data / filename, task, old_manifest["files"][filename])
                    + additions[split][task]
                )
        validate_corpus(corpus)
        _verify_text_isolation(corpus)
        config = json.loads((frozen / "specialists/config.json").read_bytes())
        for row in additions["train"]["span"]:
            candidate_supervision(row, _encode_span(row, config["span"]))
        optimizer = config["training"]
        if cpu:
            config["model_execution_location"] = "remote_runpod_cpu_only"
            optimizer["epochs"] = 6
        groups = rank_groups([(row, None) for row in corpus["train"]["rank"]])
        steps = {task: math.ceil(count / optimizer["batch_size"]) * optimizer["epochs"]
                 for task, count in (("rank", len(groups)), ("span", len(corpus["train"]["span"])))}
        optimizer["max_steps"] = max(steps.values())
        _validate_training(optimizer)

        runtime_source = runtime / "specialists"
        shutil.copytree(frozen / "specialists", runtime_source)
        if cpu:
            for name in ("run.py", "runtime.py"):
                shutil.copyfile(root / "specialists" / name, runtime_source / name)
        config_path = runtime_source / "config.json"
        config_path.write_bytes(encoded(config))
        data = runtime / DATA_PATH
        data.parent.mkdir(parents=True)
        files, counts = _write_rows(data, corpus, ("train", "validation"))
        (data / "manifest.json").write_bytes(encoded({
            "schema_version": 1, "dataset_version": version_name, "synthetic_only": True,
            "files": files, "splits": counts, "sources": source,
        }))
        dataset_sha = verify_data(data)
        (runtime / "PUBLIC_DATA_LICENSE.txt").write_text(license_text, encoding="utf-8")
        write_manifest(runtime, metadata={"kind": "runtime_source_and_synthetic_train_validation",
                       "experiment": version_name, "dataset_manifest_sha256": dataset_sha}, max_bytes=SOURCE_MAX_BYTES)

        eval_source = evaluation / "specialists"
        shutil.copytree(runtime_source, eval_source)
        for module in EVAL_MODULES:
            shutil.copyfile(root / "specialists" / module, eval_source / module)
        (evaluation / "PUBLIC_DATA_LICENSE.txt").write_text(license_text, encoding="utf-8")
        holdout = evaluation / "holdout"
        heldout_files, heldout_counts = _write_rows(holdout, corpus, ("test",))
        families = {row["family"] for rows in corpus["test"].values() for row in rows}
        source_by_family = {family: ("public_mit_publisher_questions" if family.startswith("public-synthetic-")
                                    else "authored_room_cap_scenarios") for family in sorted(families)}
        version = {"schema_version": 1, "experiment": VERSION, "split": "test", "synthetic_only": True,
                   "files": heldout_files, "source_by_family": source_by_family}
        (holdout / "manifest.json").write_bytes(encoded(version))
        holdout_sha = sha256_file(holdout / "manifest.json")
        write_manifest(evaluation, metadata={"kind": "public_policy_heldout_evaluation", "experiment": version_name,
                       "holdout_manifest_sha256": holdout_sha}, max_bytes=SOURCE_MAX_BYTES)

        release = staging / version_name
        release.mkdir()
        report = {"experiment": version_name, "config_sha256": sha256_file(config_path),
                  "training_manifest_sha256": dataset_sha, "holdout_manifest_sha256": holdout_sha,
                  "counts": {**counts, **heldout_counts}, "training_steps": steps, "public_source": source,
                  "added_rows": {split: {task: len(rows) for task, rows in by_task.items()}
                                 for split, by_task in additions.items()},
                  "holdout_span_support": dict(Counter(span["label"] for row in corpus["test"]["span"] for span in row["spans"])),
                  "holdout_rank_groups": len(rank_groups([(row, None) for row in corpus["test"]["rank"]])),
                  "heldout_public_rank_groups": len(test) // 4,
                  "reference": {"archive": reference["candidate"]["archive"], "sha256": reference["candidate"]["sha256"],
                                "config_sha256": base["config_sha256"], "training_manifest_sha256": base["training_manifest_sha256"]},
                  "model_execution_performed": False}
        for label, directory in (("runtime", runtime), ("evaluation", evaluation)):
            filename = f"policypilot-{version_name}-{label}.tar.gz"
            receipt = package_directory(directory, release / filename, max_bytes=SOURCE_MAX_BYTES)
            report[label] = {"path": filename, "sha256": receipt["sha256"], "bytes": receipt["bytes"]}
        (release / "preparation.json").write_bytes(encoded(report))
        write_manifest(release, metadata={"experiment": version_name})
        sealed = verify_manifest(release)
        if output.exists() or output.is_symlink():
            if verify_manifest(output) != sealed:
                raise ValueError("Existing public policy bundle differs from this package")
        else:
            release.rename(output)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--cpu", action="store_true")
    args = parser.parse_args()
    print(json.dumps(prepare(output=args.output, cpu=args.cpu), indent=2))


if __name__ == "__main__":
    main()
