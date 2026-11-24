"""Build a CPU-only joint selection experiment from the verified diagnostic inputs."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from .artifacts import SOURCE_MAX_BYTES, package_directory, verify_manifest, write_manifest
from .prepare import ROOT, encoded
from .prepare_quality_diagnostic import VERSION as DIAGNOSTIC_VERSION
from .prepare_quality_run import _unpack


VERSION = "specialists-joint-selection-v1"


def prepare(*, root=ROOT, output=None):
    root = Path(root)
    research = root / "artifacts/research"
    source = research / DIAGNOSTIC_VERSION
    verify_manifest(source)
    prior = json.loads((source / "preparation.json").read_bytes())
    parent_archive = prior["diagnostic"]
    output = Path(output) if output is not None else research / VERSION
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temp:
        stage = Path(temp)
        bundle = stage / "runtime"
        _unpack(source / parent_archive["path"], bundle, parent_archive["sha256"])
        validation = bundle / "validation"
        for name in ("validation-rank.jsonl", "rank-probe.jsonl"):
            (validation / name).unlink()
        shutil.copyfile(root / "specialists/joint_selection.py", bundle / "specialists/joint_selection.py")
        write_manifest(bundle, metadata={"experiment": VERSION,
                       "kind": "synthetic_development_joint_selection"})
        release = stage / VERSION
        release.mkdir()
        name = f"policypilot-{VERSION}.tar.gz"
        archive = package_directory(bundle, release / name, max_bytes=SOURCE_MAX_BYTES)
        report = {
            "experiment": VERSION,
            "training_manifest_sha256": prior["training_manifest_sha256"],
            "config_sha256": prior["config_sha256"],
            "source_diagnostic_sha256": parent_archive["sha256"],
            "validation_gold_span_count": sum(field["gold"] for field in prior["span_candidate_coverage"].values()),
            "diagnostic": {"path": name, "sha256": archive["sha256"], "bytes": archive["bytes"]},
            "model_execution_performed": False,
        }
        (release / "preparation.json").write_bytes(encoded(report))
        write_manifest(release, metadata={"experiment": VERSION})
        sealed = verify_manifest(release)
        if output.exists() or output.is_symlink():
            if verify_manifest(output) != sealed:
                raise ValueError("The existing joint selection bundle differs from this package")
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
