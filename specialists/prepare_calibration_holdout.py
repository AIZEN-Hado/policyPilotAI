"""Freeze a new synthetic holdout for development-only score calibration."""

import argparse
from collections import Counter
import json
from pathlib import Path
from random import Random
import tempfile

from .artifacts import SOURCE_MAX_BYTES, package_directory, sha256_file, verify_manifest, write_manifest
from .contracts import TASKS, validate_corpus
from .prepare import ROOT, encoded
from .prepare_quality_run import _unpack
from .prepare_research_run import _verify_text_isolation, _write_rows
from .prepare_self_learning import VERSION as TRAINING
from .runtime import DATA_PATH, _read_rows
from .self_learning_cases import _rank_rows, _span_rows


VERSION = "specialists-self-learning-calibration-v1"
WORDING = (
    ("applicable coverage number", "policy reference for this record", "accepted certificate identifier"),
    ("covered person identifier", "named insured registration", "member identity code"),
    ("hospital admission recorded", "first inpatient day", "entering the ward for care"),
    ("release from the hospital", "last day of inpatient care", "discharged to the home address"),
    ("per-night amount payable for the ordinary room", "covered overnight ward allowance", "accommodation benefit cap for each admitted day"),
    ("maximum total cover for the policy term", "insured protection across all claims", "combined benefit liability under this schedule"),
)
TOPICS = ("accommodation limit for a covered night", "annual benefit liability", "deadline for first filing",
          "supplemental claim correction", "appeal of a determination", "compulsory hospital paperwork",
          "optional supporting copy on request", "patient cost share")
AUTHORITY = (("authorized", "agreed", "applicable"), ("historical", "obsolete", "replaced"),
             ("pending approval", "unsigned proposal", "provisional"))


def prepare(root=ROOT, *, output=None):
    root = Path(root)
    research = root / "artifacts/research"
    training_root = research / TRAINING
    verify_manifest(training_root)
    original = json.loads((training_root / "preparation.json").read_bytes())
    output = Path(output) if output is not None else research / VERSION
    output.parent.mkdir(parents=True, exist_ok=True)
    rng = Random(20261226)
    holdout = {"span": _span_rows("test", 520, rng, wording=WORDING,
                                  active=("Operative certificate", "Authorized record", "Accepted entry"),
                                  inactive_status=("Obsolete", "Proposal only", "Earlier version"),
                                  layouts=(0, 1, 2, 3, 4, 5), family_prefix="calibration-holdout"),
               "rank": _rank_rows("test", 312, rng, topics=TOPICS, authority=AUTHORITY,
                                  question_stems=("Which {} source describes {} for this review?", "Cite the {} record for {}."),
                                  clause_stems=("The {} clause concerning {} specifies {}.", "For the {} version, the provision on {} states {}."),
                                  family_prefix="calibration-holdout")}
    with tempfile.TemporaryDirectory(dir=output.parent) as temp:
        stage = Path(temp)
        runtime, old, sealed, release = (stage / name for name in ("training", "old", "evaluation", "release"))
        for spec, target in ((original["runtime"], runtime), (original["evaluation"], old)):
            _unpack(training_root / spec["path"], target, spec["sha256"])
        data = runtime / DATA_PATH
        inventory = json.loads((data / "manifest.json").read_bytes())["files"]
        corpus = {split: {task: _read_rows(data / f"{split}-{task}.jsonl", task, inventory[f"{split}-{task}.jsonl"])
                          for task in TASKS} for split in ("train", "validation")}
        corpus["test"] = holdout
        validate_corpus(corpus)
        _verify_text_isolation(corpus)
        older = old / "holdout"
        first_manifest = json.loads((older / "manifest.json").read_bytes())["files"]
        for task in TASKS:
            name = f"test-{task}.jsonl"
            first_rows = _read_rows(older / name, task, first_manifest[name])
            unlabeled = [json.loads(line) for line in (runtime / "unlabeled" / f"{task}.jsonl").read_bytes().splitlines()]
            for key in ("id", "case_id", "family", "text", "query"):
                if {row[key] for row in first_rows + unlabeled if key in row} & {row[key] for row in holdout[task] if key in row}:
                    raise ValueError(f"New holdout shares {key} with earlier scoring data or the unlabeled pool")
        sealed.mkdir()
        files, counts = _write_rows(sealed / "holdout", corpus, ("test",))
        manifest = sealed / "holdout/manifest.json"
        manifest.write_bytes(encoded({"schema_version": 1, "split": "test", "synthetic_only": True,
            "experiment": VERSION, "source": "independently_worded_synthetic_english", "files": files}))
        digest = sha256_file(manifest)
        write_manifest(sealed, metadata={"experiment": VERSION, "holdout_manifest_sha256": digest})
        release.mkdir()
        filename = f"{VERSION}-holdout.tar.gz"
        archive = package_directory(sealed, release / filename, max_bytes=SOURCE_MAX_BYTES)
        spec = {"experiment": VERSION, "holdout_manifest_sha256": digest, "counts": counts["test"],
                "support": dict(Counter(p["label"] for row in holdout["span"] for p in row["spans"])),
                "calibration_source_sha256": sha256_file(root / "specialists/calibrate_self_learning.py"),
                "archive": {"path": filename, "sha256": archive["sha256"], "bytes": archive["bytes"]}}
        (release / "preparation.json").write_bytes(encoded(spec))
        write_manifest(release, metadata={"experiment": VERSION})
        if output.exists():
            if verify_manifest(output) != verify_manifest(release):
                raise ValueError("Existing calibration holdout differs from this package")
        else:
            release.rename(output)
    return spec


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(output=args.output), indent=2))


if __name__ == "__main__":
    main()
