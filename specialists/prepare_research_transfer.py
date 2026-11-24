"""Seal one research-grounded fine-tuning run and its separate benchmarks."""

import argparse
import json
import math
from pathlib import Path
import shutil
import tempfile

from .artifacts import SOURCE_MAX_BYTES, package_directory, sha256_file, verify_manifest, write_manifest
from .contracts import TASKS, validate_corpus
from .prepare import ROOT, encoded
from .prepare_quality_run import _unpack
from .prepare_research_run import FIELDBENCH_DATA, FIELDBENCH_MANIFEST_SHA256, _verify_text_isolation, _write_rows
from .prepare_self_learning import VERSION as PRIOR
from .research_transfer_data import cms_examples, policy_examples
from .run import verify_data
from .runtime import DATA_PATH, _encode_span, _read_rows, _validate_training
from .structured import candidate_supervision, rank_groups


VERSION = "specialists-research-transfer-v1"


def prepare(root=ROOT, *, output=None):
    root = Path(root)
    research = root / "artifacts/research"
    previous = research / PRIOR
    verify_manifest(previous)
    prior = json.loads((previous / "preparation.json").read_bytes())
    receipt = json.loads((research / f"{PRIOR}-candidate-run.json").read_bytes())
    for key in ("config_sha256", "training_manifest_sha256"):
        if prior[key] != receipt["inputs"][key]:
            raise ValueError("Reference checkpoint and frozen training inputs differ")
    if receipt["candidate"]["independent_reload"]["student"] is not True:
        raise ValueError("Warm start requires the verified self-trained student checkpoint")
    reference = {"archive": receipt["candidate"]["archive"], "sha256": receipt["candidate"]["sha256"],
                 "training_manifest_sha256": prior["training_manifest_sha256"], "config_sha256": prior["config_sha256"]}

    output = Path(output) if output is not None else research / VERSION
    output.parent.mkdir(parents=True, exist_ok=True)
    cms, cms_meta = cms_examples(root)
    policy, policy_meta = policy_examples(root)
    license_text = policy_meta.pop("license_text")
    fieldbench = root / FIELDBENCH_DATA
    verify_manifest(fieldbench)
    if sha256_file(fieldbench / "manifest.json") != FIELDBENCH_MANIFEST_SHA256:
        raise ValueError("FieldBench does not match the recorded benchmark")

    with tempfile.TemporaryDirectory(dir=output.parent) as temp:
        stage = Path(temp)
        runtime, old_eval, evaluation, release = (stage / name for name in ("runtime", "old-eval", "evaluation", "release"))
        for item, directory in (("runtime", runtime), ("evaluation", old_eval)):
            spec = prior[item]
            _unpack(previous / spec["path"], directory, spec["sha256"])
        data, config_path = runtime / DATA_PATH, runtime / "specialists/config.json"
        if verify_data(data) != prior["training_manifest_sha256"] or sha256_file(config_path) != prior["config_sha256"]:
            raise ValueError("Verified warm-start inputs changed")
        manifest = json.loads((data / "manifest.json").read_bytes())
        config = json.loads(config_path.read_bytes())
        corpus = {"test": {"span": cms["test"], "rank": policy["test"]}}
        for split in ("train", "validation"):
            additions = {"span": cms[split], "rank": policy[split]}
            corpus[split] = {}
            for task in TASKS:
                name = f"{split}-{task}.jsonl"
                original = _read_rows(data / name, task, manifest["files"][name])
                corpus[split][task] = original + additions[task]
        validate_corpus(corpus)
        _verify_text_isolation(corpus)
        for rows in cms.values():
            for row in rows:
                candidate_supervision(row, _encode_span(row, config["span"]))

        config.pop("self_training")
        config["warm_start"] = reference
        shutil.rmtree(runtime / "unlabeled")
        training = config["training"]
        training.update(epochs=6, learning_rate=0.00035)
        rank_train_groups = len(rank_groups([(row, None) for row in corpus["train"]["rank"]]))
        steps = {task: math.ceil(count / training["batch_size"]) * training["epochs"]
                 for task, count in (("span", len(corpus["train"]["span"])), ("rank", rank_train_groups))}
        training["max_steps"] = max(steps.values())
        _validate_training(training)
        config_path.write_bytes(encoded(config))
        shutil.rmtree(data)
        files, counts = _write_rows(data, corpus, ("train", "validation"))
        manifest.pop("unlabeled_inventory", None)
        (data / "manifest.json").write_bytes(encoded({**manifest, "dataset_version": VERSION,
            "files": files, "splits": counts, "research_sources": {"cms": cms_meta, "policy": policy_meta}}))
        data_sha = verify_data(data)
        (runtime / "PUBLIC_DATA_LICENSE.txt").write_text(license_text, encoding="utf-8")
        for name in ("run.py", "research_transfer_runtime.py"):
            shutil.copyfile(root / "specialists" / name, runtime / "specialists" / name)
        write_manifest(runtime, metadata={"kind": "runtime_source_and_research_train_validation", "experiment": VERSION,
                       "dataset_manifest_sha256": data_sha}, max_bytes=SOURCE_MAX_BYTES)

        shutil.copytree(runtime / "specialists", evaluation / "specialists")
        shutil.copyfile(root / "specialists/evaluate_research_transfer.py", evaluation / "specialists/evaluate_research_transfer.py")
        shutil.copyfile(runtime / "PUBLIC_DATA_LICENSE.txt", evaluation / "PUBLIC_DATA_LICENSE.txt")
        shutil.copytree(old_eval / "holdout", evaluation / "regression")
        shutil.copytree(fieldbench, evaluation / "fieldbench")
        holdout = evaluation / "holdout"
        holdout_files, test_counts = _write_rows(holdout, corpus, ("test",))
        source_names = {row["family"]: source for source, rows in
                        (("cms_synthetic_claim_dates", cms["test"]), ("publisher_policy_questions", policy["test"])) for row in rows}
        (holdout / "manifest.json").write_bytes(encoded({"schema_version": 1, "experiment": VERSION, "split": "test",
            "synthetic_only": True, "files": holdout_files, "source_by_family": source_names}))
        holdout_sha = sha256_file(holdout / "manifest.json")
        regression_sha = sha256_file(evaluation / "regression/manifest.json")
        if regression_sha != prior["holdout_manifest_sha256"]:
            raise ValueError("Previously reported holdout changed")
        write_manifest(evaluation, metadata={"kind": "held_out_research_evaluation", "experiment": VERSION,
                       "holdout_manifest_sha256": holdout_sha}, max_bytes=SOURCE_MAX_BYTES)

        release.mkdir()
        report = {"experiment": VERSION, "reference": reference, "training_manifest_sha256": data_sha,
                  "config_sha256": sha256_file(config_path), "holdout_manifest_sha256": holdout_sha,
                  "regression_manifest_sha256": regression_sha, "fieldbench_manifest_sha256": FIELDBENCH_MANIFEST_SHA256,
                  "counts": {**counts, **test_counts}, "planned_steps": steps,
                  "additional_cms_rows": {split: len(rows) for split, rows in cms.items()},
                  "additional_policy_groups": {split: len({(row["case_id"], row["query"]) for row in rows})
                                               for split, rows in policy.items()}, "model_execution_performed": False,
                  "research_sources": {"cms": cms_meta, "policy": policy_meta}}
        for label, folder in (("runtime", runtime), ("evaluation", evaluation)):
            filename = f"policypilot-{VERSION}-{label}.tar.gz"
            packed = package_directory(folder, release / filename, max_bytes=SOURCE_MAX_BYTES)
            report[label] = {"path": filename, "sha256": packed["sha256"], "bytes": packed["bytes"]}
        (release / "preparation.json").write_bytes(encoded(report))
        write_manifest(release, metadata={"experiment": VERSION})
        if output.exists() or output.is_symlink():
            if verify_manifest(output) != verify_manifest(release):
                raise ValueError("Existing research-transfer experiment differs from this package")
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
