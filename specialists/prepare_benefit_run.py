"""Seal benefit training and independently worded synthetic evaluation bundles."""

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import shutil
import tempfile

from .artifacts import SOURCE_MAX_BYTES, package_directory, sha256_file, verify_manifest, write_manifest
from .benefit_experiment_cases import benefit_rows
from .contracts import SPAN_LABELS, TASKS, validate_corpus
from .prepare import ROOT, encoded
from .prepare_balanced_run import VERSION as PRIOR
from .prepare_quality_run import _unpack
from .prepare_research_run import _verify_text_isolation, _write_rows
from .run import verify_data
from .runtime import DATA_PATH, _encode_span, _read_rows, _validate_training
from .structured import candidate_supervision, rank_groups


VERSION = "specialists-benefit-evidence-v1"


def prepare(root=ROOT, *, output=None):
    root = Path(root)
    research = root / "artifacts/research"
    previous = research / PRIOR
    verify_manifest(previous)
    prior = json.loads((previous / "preparation.json").read_bytes())
    reference = json.loads((research / f"{PRIOR}-candidate-run.json").read_bytes())
    if any(prior[key] != reference["input_fingerprints"][key] for key in ("training_manifest_sha256", "config_sha256")):
        raise ValueError("Reference checkpoint inputs differ from the frozen source")
    if reference["archive"]["independent_reload_predictions_match"] is not True:
        raise ValueError("The reference checkpoint must have verified reload predictions")
    output = Path(output) if output is not None else research / VERSION
    output.parent.mkdir(parents=True, exist_ok=True)
    additions = benefit_rows()
    with tempfile.TemporaryDirectory(dir=output.parent) as temp:
        stage = Path(temp)
        runtime, evaluator, release = (stage / name for name in ("runtime", "evaluation", VERSION))
        source = prior["runtime"]
        _unpack(previous / source["path"], runtime, source["sha256"])
        data, config_path = runtime / DATA_PATH, runtime / "specialists/config.json"
        if verify_data(data) != prior["training_manifest_sha256"] or sha256_file(config_path) != prior["config_sha256"]:
            raise ValueError("The frozen base data or config differs from the reference")
        manifest = json.loads((data / "manifest.json").read_bytes())
        config = json.loads(config_path.read_bytes())
        corpus = {"test": additions["test"]}
        for split in ("train", "validation"):
            corpus[split] = {}
            for task in TASKS:
                name = f"{split}-{task}.jsonl"
                previous_rows = _read_rows(data / name, task, manifest["files"][name])
                corpus[split][task] = previous_rows + additions[split][task]
        validate_corpus(corpus)
        _verify_text_isolation(corpus)
        for split in additions.values():
            for row in split["span"]:
                candidate_supervision(row, _encode_span(row, config["span"]))
        training = config["training"]
        rank_count = len(rank_groups([(row, None) for row in corpus["train"]["rank"]]))
        steps = {task: math.ceil(count / training["batch_size"]) * training["epochs"]
                 for task, count in (("span", len(corpus["train"]["span"])), ("rank", rank_count))}
        training["max_steps"] = max(steps.values())
        _validate_training(training)
        config_path.write_bytes(encoded(config))
        shutil.rmtree(data)
        files, counts = _write_rows(data, corpus, ("train", "validation"))
        (data / "manifest.json").write_bytes(encoded({**manifest, "files": files, "splits": counts,
            "dataset_version": VERSION, "previous_training_manifest_sha256": prior["training_manifest_sha256"]}))
        data_sha = verify_data(data)
        write_manifest(runtime, metadata={"experiment": VERSION, "kind": "runtime_source_and_synthetic_train_validation",
                                          "dataset_manifest_sha256": data_sha}, max_bytes=SOURCE_MAX_BYTES)
        shutil.copytree(runtime / "specialists", evaluator / "specialists")
        (evaluator / "specialists/compare_balanced_validation.py").unlink()
        holdout = evaluator / "holdout"
        test_files, test_counts = _write_rows(holdout, corpus, ("test",))
        support = Counter(span["label"] for row in corpus["test"]["span"] for span in row["spans"])
        if support.keys() != set(SPAN_LABELS):
            raise ValueError("The held-out split must cover all required fields")
        questions = {row["query"] for row in corpus["test"]["rank"]}
        rank_groups_test = {(row["case_id"], row["query"]) for row in corpus["test"]["rank"]}
        (holdout / "manifest.json").write_bytes(encoded({"schema_version": 1, "split": "test", "synthetic_only": True,
            "experiment": VERSION, "source": "authored_fictional_benefits_and_clauses", "files": test_files,
            "limitations": ["Values vary within authored wording families. The sample covers English text only."]}))
        holdout_sha = sha256_file(holdout / "manifest.json")
        write_manifest(evaluator, metadata={"experiment": VERSION, "kind": "held_out_synthetic_evaluation",
                    "holdout_manifest_sha256": holdout_sha}, max_bytes=SOURCE_MAX_BYTES)
        release.mkdir()
        report = {"experiment": VERSION, "reference": {"archive": reference["archive"]["path"],
            "sha256": reference["archive"]["sha256"], "training_manifest_sha256": prior["training_manifest_sha256"],
            "config_sha256": prior["config_sha256"]}, "training_manifest_sha256": data_sha,
            "config_sha256": sha256_file(config_path), "holdout_manifest_sha256": holdout_sha,
            "planned_steps": steps, "counts": {**counts, **test_counts},
            "additional_rows": {split: {task: len(rows) for task, rows in split_rows.items()}
                                for split, split_rows in additions.items()},
            "holdout_span_support": dict(support), "holdout_rank_groups": len(rank_groups_test),
            "holdout_unique_questions": len(questions), "model_execution_performed": False}
        for label, directory in (("runtime", runtime), ("evaluation", evaluator)):
            name = f"policypilot-{VERSION}-{label}.tar.gz"
            receipt = package_directory(directory, release / name, max_bytes=SOURCE_MAX_BYTES)
            report[label] = {"path": name, "sha256": receipt["sha256"], "bytes": receipt["bytes"]}
        (release / "preparation.json").write_bytes(encoded(report))
        write_manifest(release, metadata={"experiment": VERSION})
        if output.exists() or output.is_symlink():
            if verify_manifest(output) != verify_manifest(release):
                raise ValueError("Existing benefit experiment differs from this package")
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
