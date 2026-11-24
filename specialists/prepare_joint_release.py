"""Freeze a new holdout and package the joint decoder for paired evaluation."""

import argparse
from collections import Counter
import json
from pathlib import Path
import shutil
import tempfile

from .artifacts import SOURCE_MAX_BYTES, package_directory, sha256_file, verify_manifest, write_manifest
from .contracts import SPAN_LABELS, TASKS, validate_corpus
from .joint_holdout_cases import holdout_rows
from .prepare import ROOT, encoded
from .prepare_joint_selection import VERSION as DECODER_VERSION
from .prepare_quality_run import VERSION as WEIGHTS_VERSION, _unpack
from .prepare_research_run import _verify_text_isolation, _write_rows
from .runtime import DATA_PATH, _read_rows


VERSION = "specialists-joint-release-v1"


def _receipt(directory):
    verify_manifest(directory)
    return json.loads((directory / "preparation.json").read_bytes())


def prepare(*, root=ROOT, output=None):
    root = Path(root)
    research = root / "artifacts/research"
    decoder_dir, weights_dir = research / DECODER_VERSION, research / WEIGHTS_VERSION
    decoder, weights = _receipt(decoder_dir), _receipt(weights_dir)
    for key in ("training_manifest_sha256", "config_sha256"):
        if decoder[key] != weights[key]:
            raise ValueError("The decoder experiment and checkpoint inputs disagree")
    evidence = json.loads((research / f"{DECODER_VERSION}-comparison.json").read_bytes())
    if (evidence["experiment_archive_sha256"] != decoder["diagnostic"]["sha256"]
            or evidence["comparison"]["evaluation_criterion_met"] is not True):
        raise ValueError("Joint selection must pass the frozen validation comparison")
    checkpoint = json.loads((research / f"{WEIGHTS_VERSION}-candidate-run.json").read_bytes())
    if (checkpoint["candidate"]["sha256"] != evidence["checkpoint_sha256"]
            or checkpoint["candidate"]["independent_reload_predictions_match"] is not True
            or any(checkpoint["inputs"][key] != weights[key] or evidence[key] != weights[key]
                   for key in ("training_manifest_sha256", "config_sha256"))):
        raise ValueError("The paired comparison requires the verified development checkpoint")

    output = Path(output) if output is not None else research / VERSION
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temp:
        stage = Path(temp)
        runtime, bundle = stage / "training", stage / "evaluation"
        decoder_archive = decoder["diagnostic"]
        _unpack(decoder_dir / decoder_archive["path"], bundle, decoder_archive["sha256"])
        shutil.rmtree(bundle / "validation")
        code = root / "specialists/evaluate_joint_release.py"
        shutil.copyfile(code, bundle / "specialists/evaluate_joint_release.py")
        runtime_archive = weights["runtime"]
        _unpack(weights_dir / runtime_archive["path"], runtime, runtime_archive["sha256"])
        data = runtime / DATA_PATH
        manifest = data / "manifest.json"
        if sha256_file(manifest) != weights["training_manifest_sha256"]:
            raise ValueError("Training source digest changed")
        inventory = json.loads(manifest.read_bytes())["files"]
        corpus = {}
        for split in ("train", "validation"):
            corpus[split] = {}
            for task in TASKS:
                name = f"{split}-{task}.jsonl"
                corpus[split][task] = _read_rows(data / name, task, inventory[name])
        corpus["test"] = holdout_rows()
        validate_corpus(corpus)
        _verify_text_isolation(corpus)
        holdout = bundle / "holdout"
        files, counts = _write_rows(holdout, corpus, ("test",))
        fields = Counter(span["label"] for row in corpus["test"]["span"] for span in row["spans"])
        if any(fields[label] == 0 for label in SPAN_LABELS):
            raise ValueError("Each required field needs holdout support")
        groups = len({(row["case_id"], row["query"]) for row in corpus["test"]["rank"]})
        families = len({row["family"] for row in corpus["test"]["span"]})
        queries = len({row["query"] for row in corpus["test"]["rank"]})
        (holdout / "manifest.json").write_bytes(encoded({
            "schema_version": 1, "split": "test", "synthetic_only": True,
            "experiment": VERSION, "source": "authored_synthetic_text",
            "files": files, "authored_families": families, "unique_question_wordings": queries,
            "limitations": ["Variants share authored wording and use fictional generated values.",
                            "The benchmark scores English text only and answerable ranking groups."],
        }))
        holdout_sha256 = sha256_file(holdout / "manifest.json")
        write_manifest(bundle, metadata={"experiment": VERSION, "kind": "synthetic_joint_release_evaluation",
                       "holdout_manifest_sha256": holdout_sha256})
        release = stage / VERSION
        release.mkdir()
        name = f"policypilot-{VERSION}-evaluation.tar.gz"
        archive = package_directory(bundle, release / name, max_bytes=SOURCE_MAX_BYTES)
        report = {"experiment": VERSION, "candidate": checkpoint["candidate"],
                  "training_manifest_sha256": weights["training_manifest_sha256"],
                  "config_sha256": weights["config_sha256"],
                  "source_decoder_archive_sha256": decoder_archive["sha256"],
                  "holdout_manifest_sha256": holdout_sha256,
                  "holdout_rows": counts["test"], "authored_families": families,
                  "ranking_groups": groups, "unique_question_wordings": queries,
                  "field_support": dict(fields),
                  "evaluation": {"path": name, "sha256": archive["sha256"], "bytes": archive["bytes"]},
                  "model_execution_performed": False}
        (release / "preparation.json").write_bytes(encoded(report))
        write_manifest(release, metadata={"experiment": VERSION})
        sealed = verify_manifest(release)
        if output.exists() or output.is_symlink():
            if verify_manifest(output) != sealed:
                raise ValueError("Existing paired release bundle differs from this package")
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
