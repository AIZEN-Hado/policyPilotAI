"""Freeze research train/validation and separate holdout files without running models."""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import tarfile
import tempfile

from .artifacts import SOURCE_MAX_BYTES, package_directory, sha256_file, verify_archive, verify_manifest, write_manifest
from .contracts import SPLITS, TASKS, validate_corpus
from .features import encode_span
from .prepare import DATA_FILES, ROOT, RUNTIME_FILES, encoded
from .research_cases import generate_challenges
from .research_data import CMS_LIMITS, _jsonl
from .run import verify_data


VERSION = "specialists-research-v1"
SEED = 20261120
BASELINE_ARCHIVE = Path("artifacts/policypilot-specialists-v3-runtime.tar.gz")
BASELINE_ARCHIVE_SHA256 = "616df13b7dc1a2851bc64cf79343301d01fbd96f7237732dcc8ccd9132db06fa"
BASELINE_DATA = Path("data/synthetic/specialists-v1")
CMS_DATA = Path("data/outputs/research/cms-inpatient-sample1-v1")
CMS_MANIFEST_SHA256 = "f80e795fbc7703ba62f100be72e1bbd84d1762eed8089e62060c89367b9edb30"
FIELDBENCH_DATA = Path("data/outputs/research/fieldbench-v0.4.2")
FIELDBENCH_MANIFEST_SHA256 = "3f6219d3a7aee0ef6b665cbd61eb14a72fec2897ea8053ccfa8a4e4c6c7e1437"
LIMITATIONS = (
    "All examples are synthetic English text. CMS stays are rendered in fictional document layouts.",
    "Authored synthetic cases within a family are template variants, so row counts overstate independent wording diversity.",
    "The experiment evaluates text offsets and evidence relevance. PDFs, layout coordinates, OCR, and real claims are outside its scope.",
)


def _bytes_fingerprint(content):
    return {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}


def _source_manifest(directory, expected_sha256):
    if sha256_file(directory / "manifest.json") != expected_sha256:
        raise ValueError(f"{directory.name} manifest differs from the frozen research source")
    return verify_manifest(directory)


def _rows(content):
    return [json.loads(line) for line in content.decode("utf-8").splitlines()]


def _source_rows(directory, entries, name):
    content = (directory / name).read_bytes()
    if _bytes_fingerprint(content) != entries[name]:
        raise ValueError(f"Source file fingerprint changed: {directory.name}/{name}")
    return _rows(content)


def _baseline(root):
    path = root / BASELINE_ARCHIVE
    receipt = verify_archive(path, max_bytes=SOURCE_MAX_BYTES)
    if receipt["sha256"] != BASELINE_ARCHIVE_SHA256:
        raise ValueError("Training runtime differs from the frozen specialist v3 archive")
    entries = {item["path"]: {key: item[key] for key in ("bytes", "sha256")}
               for item in receipt["manifest"]["files"]}
    expected = {f"specialists/{name}" for name in RUNTIME_FILES}
    expected.update(f"{BASELINE_DATA}/{name}" for name in (*DATA_FILES, "manifest.json"))
    if entries.keys() != expected:
        raise ValueError("Frozen runtime inventory has unexpected members")
    source = {}
    with tarfile.open(path, "r:gz") as archive:
        for name in RUNTIME_FILES:
            member = f"specialists/{name}"
            with archive.extractfile(member) as payload:
                content = payload.read(entries[member]["bytes"] + 1)
            if _bytes_fingerprint(content) != entries[member]:
                raise ValueError(f"Frozen runtime file changed: {member}")
            source[name] = content
    dataset_entries = {name: entries[f"{BASELINE_DATA}/{name}"] for name in DATA_FILES}
    if verify_data(root / BASELINE_DATA) != entries[f"{BASELINE_DATA}/manifest.json"]["sha256"]:
        raise ValueError("Original dataset manifest differs from the frozen training runtime")
    return source, dataset_entries, entries[f"{BASELINE_DATA}/manifest.json"]["sha256"]


def _cms(root):
    directory = root / CMS_DATA
    manifest = _source_manifest(directory, CMS_MANIFEST_SHA256)
    entries = {item["path"]: {key: item[key] for key in ("bytes", "sha256")}
               for item in manifest["files"]}
    rows_by_split, seen_groups = {}, set()
    for split, count in CMS_LIMITS.items():
        rows = _source_rows(directory, entries, f"{split}-span.jsonl")
        lineage = _source_rows(directory, entries, f"{split}-lineage.jsonl")
        if len(rows) != count or len(lineage) != count:
            raise ValueError(f"CMS {split} does not have the expected number of stays")
        case_ids = {row["case_id"] for row in rows}
        if len(case_ids) != count or case_ids != {item["case_id"] for item in lineage}:
            raise ValueError(f"CMS {split} lineage does not match the span cases")
        groups = {item["synthetic_beneficiary_sha256"] for item in lineage}
        if (any(not re.fullmatch(r"[0-9a-f]{64}", group) for group in groups)
                or groups & seen_groups or len(groups) != manifest["metadata"]["split_counts"][split]["beneficiaries"]):
            raise ValueError(f"CMS {split} beneficiary lineage is invalid or crosses splits")
        seen_groups.update(groups)
        for row in rows:
            if (row["family"] != f"cms-inpatient-{split}-v1" or row["kind"] != "claim_form"
                    or {span["label"] for span in row["spans"]} != {"ADMISSION_DATE", "DISCHARGE_DATE"}):
                raise ValueError(f"CMS {split} row differs from its date-only claim form contract")
        rows_by_split[split] = rows
    return rows_by_split, manifest["metadata"]["sha256"]


def _verify_challenge_groups(challenges):
    for split in SPLITS:
        groups = defaultdict(list)
        for row in challenges[split]["rank"]:
            groups[row["case_id"], row["query"]].append(row)
        if len(groups) != (128 if split == "train" else 64):
            raise ValueError(f"Unexpected number of challenge groups in {split}")
        for rows in groups.values():
            if (len(rows) != 4 or len({row["kind"] for row in rows}) != 1
                    or len({row["text"] for row in rows}) != 4 or sum(row["relevant"] for row in rows) != 1):
                raise ValueError(f"Invalid ranking challenge candidates in {split}")


def _verify_text_isolation(corpus):
    seen_queries, seen_text = set(), set()
    for split in SPLITS:
        queries = {row["query"] for row in corpus[split]["rank"]}
        texts = {row["text"] for task in TASKS for row in corpus[split][task]}
        if queries & seen_queries or texts & seen_text:
            raise ValueError("Exact queries or documents were reused across splits")
        seen_queries.update(queries)
        seen_text.update(texts)


def _write_rows(directory, corpus, splits):
    directory.mkdir()
    files, counts = {}, {}
    for split in splits:
        counts[split] = {}
        for task in TASKS:
            rows = corpus[split][task]
            name = f"{split}-{task}.jsonl"
            content = _jsonl(rows).encode("utf-8")
            (directory / name).write_bytes(content)
            files[name] = {**_bytes_fingerprint(content), "rows": len(rows)}
            counts[split][task] = len(rows)
    return files, counts


def prepare(root=ROOT, *, output=None):
    root = Path(root).resolve()
    output = Path(output) if output is not None else root / "artifacts/research" / VERSION
    source, original, original_manifest_sha256 = _baseline(root)
    config = json.loads(source["config.json"])
    cms, cms_archive_sha256 = _cms(root)
    fieldbench = _source_manifest(root / FIELDBENCH_DATA, FIELDBENCH_MANIFEST_SHA256)
    challenges = generate_challenges(SEED)
    _verify_challenge_groups(challenges)

    corpus = {split: {task: [] for task in TASKS} for split in SPLITS}
    for split in ("train", "validation"):
        for task in TASKS:
            name = f"{split}-{task}.jsonl"
            corpus[split][task].extend(_source_rows(root / BASELINE_DATA, original, name))
    for split in SPLITS:
        corpus[split]["span"].extend(cms[split])
        for task in TASKS:
            corpus[split][task].extend(challenges[split][task])
    validate_corpus(corpus)
    _verify_text_isolation(corpus)
    for split in SPLITS:
        for row in corpus[split]["span"]:
            encode_span(row, config["span"])

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        staging = Path(temporary)
        release = staging / VERSION
        release.mkdir()
        train_validation = release / "train-validation"
        files, counts = _write_rows(train_validation, corpus, ("train", "validation"))
        source_ids = {
            "original_training_manifest_sha256": original_manifest_sha256,
            "cms_source_archive_sha256": cms_archive_sha256,
            "challenge_seed": SEED,
        }
        (train_validation / "manifest.json").write_bytes(encoded({
            "schema_version": 1,
            "dataset_version": VERSION,
            "synthetic_only": True,
            "files": files,
            "splits": counts,
            "sources": source_ids,
            "limitations": LIMITATIONS,
        }))
        training_sha256 = verify_data(train_validation)

        holdout = release / "holdout"
        test_files, test_counts = _write_rows(holdout, corpus, ("test",))
        (holdout / "manifest.json").write_bytes(encoded({
            "schema_version": 1,
            "dataset_version": VERSION,
            "split": "test",
            "synthetic_only": True,
            "counts": test_counts["test"],
            "files": test_files,
            "families": {task: dict(Counter(row["family"] for row in corpus["test"][task])) for task in TASKS},
            "training_manifest_sha256": training_sha256,
            "sources": {"cms_manifest_sha256": CMS_MANIFEST_SHA256, "challenge_seed": SEED},
            "limitations": LIMITATIONS,
        }))

        runtime = staging / "runtime"
        (runtime / "specialists").mkdir(parents=True)
        for name, content in source.items():
            (runtime / "specialists" / name).write_bytes(content)
        archive_data = runtime / BASELINE_DATA
        archive_data.mkdir(parents=True)
        for path in train_validation.iterdir():
            (archive_data / path.name).write_bytes(path.read_bytes())
        write_manifest(runtime, metadata={
            "kind": "runtime_source_and_synthetic_train_validation",
            "dataset_version": VERSION,
            "dataset_manifest_sha256": training_sha256,
            "model_quality_verified": False,
            "no_language_model": True,
            "weights_included": False,
        }, max_bytes=SOURCE_MAX_BYTES)
        archive_path = release / f"policypilot-{VERSION}-runtime.tar.gz"
        archive = package_directory(runtime, archive_path, max_bytes=SOURCE_MAX_BYTES)

        report = {
            "dataset_version": VERSION,
            "counts": {**counts, **test_counts},
            "archive": {"path": archive_path.name, "sha256": archive["sha256"], "bytes": archive["bytes"]},
            "training_manifest_sha256": training_sha256,
            "test_manifest_sha256": sha256_file(holdout / "manifest.json"),
            "config_sha256": _bytes_fingerprint(source["config.json"])["sha256"],
            "baseline_runtime_sha256": BASELINE_ARCHIVE_SHA256,
            "cms_manifest_sha256": CMS_MANIFEST_SHA256,
            "cms_beneficiaries_disjoint": True,
            "cases_and_families_disjoint": True,
            "fieldbench_value_only": {
                "path": str(FIELDBENCH_DATA / "value-only-holdout.jsonl"),
                "manifest_sha256": FIELDBENCH_MANIFEST_SHA256,
                "counts": fieldbench["metadata"]["document_counts"],
            },
            "runtime_members_verified": True,
            "model_execution_performed": False,
            "trained_weights_created": False,
        }
        (release / "preparation.json").write_bytes(encoded(report))
        write_manifest(release, metadata={"dataset_version": VERSION, "kind": "local_research_preparation"})
        inventory = verify_manifest(release)
        if output.exists() or output.is_symlink():
            if verify_manifest(output) != inventory:
                raise ValueError("Existing research experiment differs from the frozen preparation")
        else:
            release.rename(output)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(prepare(args.root, output=args.output), indent=2))
    except (OSError, ValueError, KeyError, tarfile.TarError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
