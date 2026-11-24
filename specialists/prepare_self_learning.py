"""Prepare separately sealed self-training and holdout bundles without model calls."""

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import shutil
import tempfile

from .artifacts import SOURCE_MAX_BYTES, package_directory, sha256_file, verify_manifest, write_manifest
from .contracts import SPAN_LABELS, TASKS, validate_corpus
from .prepare import ROOT, encoded
from .prepare_benefit_run import VERSION as PRIOR
from .prepare_quality_run import _unpack
from .prepare_research_run import _verify_text_isolation, _write_rows
from .run import verify_data
from .runtime import DATA_PATH, _encode_span, _read_rows, _validate_training
from .self_learning import POOL_DIRECTORY
from .self_learning_cases import composed_rows
from .structured import candidate_supervision, rank_groups


VERSION = "specialists-self-learning-v1"
MODULES = ("runtime.py", "features.py", "span_context.py", "semantic_cues.py", "self_learning.py",
           "evaluate_quality_run.py", "evaluate_public_policy_run.py", "evaluate_self_learning.py")


def _seal_pool(directory, pool, corpus):
    used_rows = [row for split in corpus.values() for task in TASKS for row in split[task]]
    for key in ("id", "case_id", "family", "text", "query"):
        used = {row[key] for row in used_rows if key in row}
        if used & {row[key] for task in TASKS for row in pool[task] if key in row}:
            raise ValueError(f"Unlabeled pool and supervised splits share {key}")
    directory.mkdir()
    inventory = {}
    for task, label in (("span", "spans"), ("rank", "relevant")):
        path = directory / f"{task}.jsonl"
        rows = [{key: value for key, value in row.items() if key != label} for row in pool[task]]
        path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
        inventory[task] = {"bytes": path.stat().st_size, "sha256": sha256_file(path), "rows": len(rows)}
    return inventory


def prepare(root=ROOT, *, output=None):
    root = Path(root)
    research = root / "artifacts/research"
    previous = research / PRIOR
    verify_manifest(previous)
    prior = json.loads((previous / "preparation.json").read_bytes())
    reference = json.loads((research / f"{PRIOR}-candidate-run.json").read_bytes())
    if (not reference["archive"]["independent_reload_predictions_match"]
            or any(prior[key] != reference["inputs"][key] for key in ("training_manifest_sha256", "config_sha256"))):
        raise ValueError("Reference checkpoint differs from the verified inputs")
    output = Path(output) if output is not None else research / VERSION
    output.parent.mkdir(parents=True, exist_ok=True)
    additions = composed_rows()
    pool = additions.pop("pool")
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        stage = Path(temporary)
        runtime, evaluator, release = (stage / name for name in ("runtime", "evaluation", VERSION))
        source = prior["runtime"]
        _unpack(previous / source["path"], runtime, source["sha256"])
        data, config_path = runtime / DATA_PATH, runtime / "specialists/config.json"
        if verify_data(data) != prior["training_manifest_sha256"] or sha256_file(config_path) != prior["config_sha256"]:
            raise ValueError("Base dataset or configuration failed read-back verification")
        prior_data = json.loads((data / "manifest.json").read_bytes())
        config = json.loads(config_path.read_bytes())
        corpus = {"test": additions["test"]}
        for split in ("train", "validation"):
            corpus[split] = {}
            for task in TASKS:
                name = f"{split}-{task}.jsonl"
                old = _read_rows(data / name, task, prior_data["files"][name])
                corpus[split][task] = old + additions[split][task]
        validate_corpus(corpus)
        _verify_text_isolation(corpus)
        config["span"].update(context_feature_version=2)
        config["rank"].update(feature_version=3, features=448, hidden_size=96)
        for split in additions.values():
            for row in split["span"]:
                candidate_supervision(row, _encode_span(row, config["span"]))
        pool_directory = runtime / POOL_DIRECTORY
        pool_meta = _seal_pool(pool_directory, pool, corpus)
        training = config["training"]
        training.update(epochs=12, batch_size=32)
        config["self_training"] = {"rounds": 2, "epochs": 3, "span_probability": 0.9,
                                   "rank_probability": 0.9, "margin": 1.5, "pool": pool_meta}
        examples = {"span": len(corpus["train"]["span"]),
                    "rank": len(rank_groups([(row, None) for row in corpus["train"]["rank"]]))}
        pool_units = {"span": len(pool["span"]),
                      "rank": len({(row["case_id"], row["query"]) for row in pool["rank"]})}
        steps = {task: math.ceil(count / training["batch_size"]) * training["epochs"] for task, count in examples.items()}
        round_maximum = {task: math.ceil((examples[task] + pool_units[task]) / training["batch_size"])
                         * config["self_training"]["epochs"] for task in TASKS}
        training["max_steps"] = max(*steps.values(), *round_maximum.values())
        _validate_training(training)
        config_path.write_bytes(encoded(config))
        shutil.rmtree(data)
        files, counts = _write_rows(data, corpus, ("train", "validation"))
        (data / "manifest.json").write_bytes(encoded({**prior_data, "files": files, "splits": counts,
            "dataset_version": VERSION, "previous_training_manifest_sha256": prior["training_manifest_sha256"],
            "unlabeled_inventory": pool_meta}))
        data_sha = verify_data(data)
        for name in MODULES:
            shutil.copyfile(root / "specialists" / name, runtime / "specialists" / name)
        write_manifest(runtime, metadata={"experiment": VERSION, "kind": "runtime_source_and_synthetic_train_validation",
                                           "dataset_manifest_sha256": data_sha}, max_bytes=SOURCE_MAX_BYTES)
        shutil.copytree(runtime / "specialists", evaluator / "specialists")
        holdout = evaluator / "holdout"
        test_files, test_counts = _write_rows(holdout, corpus, ("test",))
        support = Counter(span["label"] for row in corpus["test"]["span"] for span in row["spans"])
        if support.keys() != set(SPAN_LABELS):
            raise ValueError("Frozen holdout must cover all field labels")
        holdout_queries = {row["query"] for row in corpus["test"]["rank"]}
        holdout_groups = {(row["case_id"], row["query"]) for row in corpus["test"]["rank"]}
        (holdout / "manifest.json").write_bytes(encoded({"schema_version": 1, "split": "test", "synthetic_only": True,
            "experiment": VERSION, "source": "synthetic_composed_english", "files": test_files,
            "limitations": ["Synthetic clause combinations share field semantics and do not establish real-world accuracy."]}))
        holdout_sha = sha256_file(holdout / "manifest.json")
        write_manifest(evaluator, metadata={"experiment": VERSION, "kind": "held_out_synthetic_evaluation",
                    "holdout_manifest_sha256": holdout_sha}, max_bytes=SOURCE_MAX_BYTES)
        release.mkdir()
        report = {"experiment": VERSION, "reference": {"archive": reference["archive"]["path"],
                  "sha256": reference["archive"]["sha256"], "training_manifest_sha256": prior["training_manifest_sha256"],
                  "config_sha256": prior["config_sha256"]}, "training_manifest_sha256": data_sha,
                  "config_sha256": sha256_file(config_path), "holdout_manifest_sha256": holdout_sha,
                  "teacher_steps": steps, "maximum_steps_per_self_training_round": round_maximum,
                  "counts": {**counts, **test_counts}, "unlabeled_units": pool_units,
                  "holdout_span_support": dict(support), "holdout_rank_groups": len(holdout_groups),
                  "holdout_unique_questions": len(holdout_queries), "model_execution_performed": False}
        for label, directory in (("runtime", runtime), ("evaluation", evaluator)):
            name = f"policypilot-{VERSION}-{label}.tar.gz"
            receipt = package_directory(directory, release / name, max_bytes=SOURCE_MAX_BYTES)
            report[label] = {"path": name, "sha256": receipt["sha256"], "bytes": receipt["bytes"]}
        (release / "preparation.json").write_bytes(encoded(report))
        write_manifest(release, metadata={"experiment": VERSION})
        if output.exists() or output.is_symlink():
            if verify_manifest(output) != verify_manifest(release):
                raise ValueError("Existing self-training experiment differs from this package")
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
