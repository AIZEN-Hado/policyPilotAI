"""Build a CPU diagnostic bundle containing validation inputs only."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from .artifacts import SOURCE_MAX_BYTES, package_directory, sha256_file, verify_manifest, write_manifest
from .contracts import validate_row
from .diagnose_quality_validation import span_candidate_coverage
from .prepare import ROOT, encoded
from .prepare_quality_run import VERSION as TRAINING_VERSION, _unpack
from .runtime import DATA_PATH, _encode_span, _read_rows
from .validation_rank_probe import rank_probe_rows


VERSION = "specialists-quality-v1-diagnostic"
PRIOR = Path("artifacts/research") / TRAINING_VERSION
VALIDATION_FILES = ("validation-span.jsonl", "validation-rank.jsonl")


def prepare(*, root=ROOT, output=None):
    root = Path(root)
    output = Path(output) if output is not None else root / "artifacts/research" / VERSION
    output.parent.mkdir(parents=True, exist_ok=True)
    source = root / PRIOR
    verify_manifest(source)
    experiment = json.loads((source / "preparation.json").read_bytes())
    runtime = experiment["runtime"]
    with tempfile.TemporaryDirectory(dir=output.parent) as temp:
        staging = Path(temp)
        frozen = staging / "training"
        _unpack(source / runtime["path"], frozen, runtime["sha256"])
        data = frozen / DATA_PATH
        stamp = data / "manifest.json"
        config_path = frozen / "specialists/config.json"
        if (sha256_file(stamp) != experiment["training_manifest_sha256"]
                or sha256_file(config_path) != experiment["config_sha256"]):
            raise ValueError("Frozen source fingerprints differ from the preparation receipt")
        manifest = json.loads(stamp.read_bytes())
        config = json.loads(config_path.read_bytes())
        rows = _read_rows(data / VALIDATION_FILES[0], "span", manifest["files"][VALIDATION_FILES[0]])
        coverage = span_candidate_coverage([(row, _encode_span(row, config["span"])) for row in rows])
        probe = rank_probe_rows()
        for row in probe:
            validate_row(row)
        existing_rank_files = ("train-rank.jsonl", VALIDATION_FILES[1])
        existing_rank = [row for name in existing_rank_files
                         for row in _read_rows(data / name, "rank", manifest["files"][name])]
        for key in ("id", "case_id", "family", "query", "text"):
            if {row[key] for row in probe} & {row[key] for row in existing_rank}:
                raise ValueError(f"Development probe reuses a ranking {key}")

        diagnostic = staging / "diagnostic"
        sources = diagnostic / "specialists"
        shutil.copytree(frozen / "specialists", sources)
        for name in ("diagnose_quality_validation.py", "evaluate.py", "evaluate_quality_run.py"):
            shutil.copyfile(root / "specialists" / name, sources / name)
        validation = diagnostic / "validation"
        validation.mkdir()
        shutil.copyfile(stamp, validation / "manifest.json")
        for name in VALIDATION_FILES:
            shutil.copyfile(data / name, validation / name)
        probe_path = validation / "rank-probe.jsonl"
        probe_path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in probe), encoding="utf-8")
        probe_sha256 = sha256_file(probe_path)
        write_manifest(diagnostic, metadata={"kind": "synthetic_development_diagnostic",
                       "experiment": VERSION, "rank_probe_sha256": probe_sha256})
        release = staging / VERSION
        release.mkdir()
        archive_path = release / f"policypilot-{VERSION}.tar.gz"
        archive = package_directory(diagnostic, archive_path, max_bytes=SOURCE_MAX_BYTES)
        report = {"experiment": VERSION,
                  "source_runtime_sha256": runtime["sha256"],
                  "training_manifest_sha256": experiment["training_manifest_sha256"],
                  "config_sha256": experiment["config_sha256"],
                  "rank_probe_sha256": probe_sha256,
                  "rank_probe_groups": len({(row["case_id"], row["query"]) for row in probe}),
                  "span_candidate_coverage": coverage,
                  "diagnostic": {"path": archive_path.name, "sha256": archive["sha256"], "bytes": archive["bytes"]},
                  "model_execution_performed": False}
        (release / "preparation.json").write_bytes(encoded(report))
        write_manifest(release, metadata={"experiment": VERSION})
        sealed = verify_manifest(release)
        if output.exists() or output.is_symlink():
            if verify_manifest(output) != sealed:
                raise ValueError("The existing diagnostic bundle differs from this package")
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
