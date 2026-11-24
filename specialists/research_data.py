"""Prepare separate specialist research inputs from local public dataset archives."""

import argparse
from collections import Counter
import csv
from datetime import date, timedelta
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile
import tempfile
from zipfile import BadZipFile, ZipFile, is_zipfile

from .artifacts import sha256_file, verify_manifest, write_manifest
from .contracts import SPLITS, validate_row
from .data import _format_date, _render_document


CMS_URL = (
    "https://www.cms.gov/research-statistics-data-and-systems/downloadable-public-use-files/"
    "synpufs/downloads/de1_0_2008_to_2010_inpatient_claims_sample_1.zip"
)
CMS_MEMBER = "DE1_0_2008_to_2010_Inpatient_Claims_Sample_1.csv"
CMS_ROWS = 66_773
CMS_COLUMNS = ("DESYNPUF_ID", "CLM_ID", "CLM_ADMSN_DT", "NCH_BENE_DSCHRG_DT")
CMS_LAYOUTS = {
    "train": ("iso", "Inpatient reimbursement\nReference: {ref}\nAdmission date: {ADMISSION_DATE}\n"
                    "Discharge date: {DISCHARGE_DATE}\nForm received: {notice}"),
    "validation": ("dmy", "Treatment stay record {ref}\nForm recorded {notice}\n"
                          "Entered the ward {ADMISSION_DATE} / left the ward {DISCHARGE_DATE}"),
    "test": ("written", "The applicant for reimbursement {ref} went home on {DISCHARGE_DATE}. "
                        "The ward had taken the applicant in on {ADMISSION_DATE}. "
                        "The claim office received the form on {notice}."),
}
CMS_LIMITS = {"train": 512, "validation": 128, "test": 128}
FIELDBENCH_URL = "https://zenodo.org/records/23065721"
FIELDBENCH_MD5 = "d4ceea03251584f0c8196472dd1efac6"
FIELDBENCH_CATEGORIES = {"insurance_claims", "insurance_policies"}
FIELDBENCH_SUFFIXES = {"manifests": ".json", "expected": ".expected.json", "documents": ".md"}
CC0_LICENSES = {"cc0", "cc0 1.0", "cc0-1.0", "cc0 1.0 universal"}


def _digest(*parts):
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def _cms_date(value):
    if not re.fullmatch(r"[0-9]{8}", value):
        raise ValueError("CMS date must be YYYYMMDD")
    return date.fromisoformat(value)


def _read_cms(archive):
    stats = Counter()
    stays = {}
    with ZipFile(archive) as bundle:
        entries = [member for member in bundle.infolist()
                   if member.filename.rsplit("/", 1)[-1].casefold() == CMS_MEMBER.casefold()]
        if len(entries) != 1 or entries[0].file_size > 64 * 1024**2:
            raise ValueError(f"Expected one bounded CMS CSV member named {CMS_MEMBER}")
        with bundle.open(entries[0]) as payload, io.TextIOWrapper(payload, encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream, strict=True)
            header = reader.fieldnames or []
            if len(header) != 81 or len(set(header)) != 81 or not set(CMS_COLUMNS) <= set(header):
                raise ValueError("CSV header differs from the published CMS inpatient schema")
            for row in reader:
                stats["source_rows"] += 1
                if stats["source_rows"] > CMS_ROWS or None in row or None in row.values():
                    raise ValueError("CMS CSV row count or field count differs from the published schema")
                beneficiary, claim, admitted, discharged = (row[column].strip() for column in CMS_COLUMNS)
                if not beneficiary or not claim:
                    raise ValueError("CMS beneficiary and claim identifiers are required")
                try:
                    admission, discharge = _cms_date(admitted), _cms_date(discharged)
                    if discharge < admission:
                        raise ValueError("discharge precedes admission")
                except ValueError:
                    stats["skipped_invalid_or_reversed_dates"] += 1
                    continue
                group = _digest("cms-beneficiary-v1", beneficiary)
                stay = (group, admission, discharge)
                if stay in stays:
                    stats["collapsed_repeat_stays"] += 1
                stays[stay] = min(stays.get(stay, claim), claim)
    if stats["source_rows"] != CMS_ROWS:
        raise ValueError(f"CMS Sample 1 must contain {CMS_ROWS:,} source rows")
    return stays, stats


def _cms_splits(stays):
    candidates = {split: [] for split in SPLITS}
    for (group, admission, discharge), claim in stays.items():
        bucket = int(group[:8], 16) % 100
        split = "train" if bucket < 70 else "validation" if bucket < 85 else "test"
        reference = _digest("cms-stay-v1", group, claim, admission.isoformat(), discharge.isoformat())
        candidates[split].append((reference, group, admission, discharge))
    for split in SPLITS:
        style, template = CMS_LAYOUTS[split]
        rows, groups = [], {}
        for reference, group, admission, discharge in sorted(candidates[split])[:CMS_LIMITS[split]]:
            case_id = f"CMS-IP-{reference[:20]}"
            text, spans = _render_document(template, {
                "ref": case_id,
                "notice": _format_date(discharge + timedelta(days=1 + int(reference[:4], 16) % 30), style),
                "ADMISSION_DATE": _format_date(admission, style),
                "DISCHARGE_DATE": _format_date(discharge, style),
            })
            row = {"id": f"{case_id}-span-claim_form", "case_id": case_id, "family": f"cms-inpatient-{split}-v1",
                   "kind": "claim_form", "task": "span", "synthetic": True, "text": text, "spans": spans}
            validate_row(row)
            groups[case_id] = group
            rows.append(row)
        if not rows:
            raise ValueError(f"CMS source does not populate the {split} split")
        yield split, rows, groups


def _jsonl(rows):
    return "".join(json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n" for row in rows)


def prepare_cms(archive, staging, expected_sha256=None):
    digest = sha256_file(archive)
    if expected_sha256 is not None and digest != expected_sha256.lower():
        raise ValueError("CMS archive SHA-256 does not match the supplied digest")
    stays, stats = _read_cms(archive)
    counts, assigned_groups = {}, set()
    for split, rows, groups in _cms_splits(stays):
        group_ids = set(groups.values())
        if group_ids & assigned_groups or len(groups) != len(rows):
            raise ValueError("CMS split leaked beneficiary groups or repeated case IDs")
        assigned_groups.update(group_ids)
        (staging / f"{split}-span.jsonl").write_text(_jsonl(rows), encoding="utf-8")
        (staging / f"{split}-lineage.jsonl").write_text(_jsonl(
            {"case_id": case, "synthetic_beneficiary_sha256": group} for case, group in groups.items()
        ), encoding="utf-8")
        counts[split] = {"span_rows": len(rows), "beneficiaries": len(group_ids)}
    return {"dataset": "cms-de-synpuf-inpatient-sample1", "source_url": CMS_URL, "sha256": digest,
            "source_sha256_supplied": expected_sha256 is not None, "license": "US public domain",
            "scope": "fictional claim text with rendered source-date spans", "source_counts": dict(stats),
            "source_columns": {"ADMISSION_DATE": "CLM_ADMSN_DT", "DISCHARGE_DATE": "NCH_BENE_DSCHRG_DT"},
            "split_counts": counts, "baseline_runtime_integration": False}


def _fieldbench_members(archive):
    if is_zipfile(archive):
        with ZipFile(archive) as bundle:
            for member in bundle.infolist():
                if not member.is_dir():
                    yield member.filename, member.file_size, lambda member=member: bundle.read(member)
    else:
        with tarfile.open(archive, "r|*") as bundle:
            for member in bundle:
                if member.isfile():
                    yield member.name, member.size, lambda member=member: bundle.extractfile(member).read()


def _unique_json_object(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("FieldBench JSON contains a duplicate key")
    return result


def _fieldbench_json(raw):
    value = json.loads(raw, object_pairs_hook=_unique_json_object)
    if not isinstance(value, dict) or not value:
        raise ValueError("Expected a nonempty FieldBench JSON object")
    return value


def _fieldbench_rows(archive):
    entries = {}
    for name, size, read in _fieldbench_members(archive):
        parts = name.removeprefix("./").split("/")
        if len(parts) < 3:
            continue
        category, kind, filename = parts[-3:]
        suffix = FIELDBENCH_SUFFIXES.get(kind)
        if category not in FIELDBENCH_CATEGORIES or not suffix or not filename.endswith(suffix):
            continue
        doc_id = filename[:-len(suffix)]
        if (not doc_id or any(part in {"", ".", ".."} or "\\" in part for part in parts)
                or not 0 < size <= 1024**2):
            raise ValueError(f"Invalid FieldBench archive member {name}")
        triplet = entries.setdefault((category, doc_id), {})
        if kind in triplet:
            raise ValueError(f"Duplicate FieldBench archive member {name}")
        triplet[kind] = read()

    for (category, doc_id), triplet in sorted(entries.items()):
        if "manifests" not in triplet:
            continue
        provenance = _fieldbench_json(triplet["manifests"])
        license_name = provenance.get("license")
        if (provenance.get("source") != "synthetic" or not isinstance(license_name, str)
                or license_name.strip().casefold() not in CC0_LICENSES):
            continue
        if provenance.get("doc_id", doc_id) != doc_id or provenance.get("category", category) != category:
            raise ValueError(f"FieldBench manifest does not match its path for {doc_id}")
        if triplet.keys() != FIELDBENCH_SUFFIXES.keys():
            raise ValueError(f"Missing FieldBench text or expected values for {doc_id}")
        markdown = triplet["documents"].decode("utf-8")
        expected = _fieldbench_json(triplet["expected"])
        if not markdown.strip() or any(not field.strip() for field in expected):
            raise ValueError(f"Empty FieldBench text or field name for {doc_id}")
        yield {"category": category, "doc_id": doc_id, "text": markdown, "expected": expected,
               "provenance": provenance}


def prepare_fieldbench(archive, staging):
    sha256 = sha256_file(archive)
    with archive.open("rb") as payload:
        # MD5 is the archive identifier published by Zenodo. Inventory output uses SHA-256.
        md5 = hashlib.file_digest(payload, lambda: hashlib.md5(usedforsecurity=False)).hexdigest()
    if md5 != FIELDBENCH_MD5:
        raise ValueError("FieldBench archive checksum does not match the pinned v0.4.2 release")
    rows = list(_fieldbench_rows(archive))
    counts = Counter(row["category"] for row in rows)
    if counts.keys() != FIELDBENCH_CATEGORIES:
        raise ValueError("Expected eligible FieldBench documents in both insurance categories")
    (staging / "value-only-holdout.jsonl").write_text(_jsonl(rows), encoding="utf-8")
    return {"dataset": "fieldbench-v0.4.2", "source_url": FIELDBENCH_URL,
            "md5": md5, "sha256": sha256, "license": "CC0 1.0",
            "scope": "held-out Markdown extraction values in the original FieldBench schema",
            "document_counts": dict(counts), "baseline_runtime_integration": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="dataset", required=True)
    cms = subcommands.add_parser("cms", help="Render exact date spans from CMS inpatient Sample 1")
    fieldbench = subcommands.add_parser("fieldbench", help="Prepare the independent FieldBench value holdout")
    for command in (cms, fieldbench):
        command.add_argument("archive", type=Path)
        command.add_argument("output", type=Path, help="Use a new research output directory")
    cms.add_argument("--sha256", help="Check the CMS archive against a recorded SHA-256")
    args = parser.parse_args(argv)

    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=args.output.parent) as temporary:
            staging = Path(temporary) / "prepared"
            staging.mkdir()
            if args.dataset == "cms":
                metadata = prepare_cms(args.archive, staging, args.sha256)
            else:
                metadata = prepare_fieldbench(args.archive, staging)
            write_manifest(staging, metadata=metadata)
            manifest = verify_manifest(staging)
            if args.output.exists() or args.output.is_symlink():
                if verify_manifest(args.output) != manifest:
                    raise ValueError("Existing research output differs. Choose a new output directory.")
            else:
                staging.rename(args.output)
    except (OSError, ValueError, BadZipFile, csv.Error, tarfile.TarError) as error:
        parser.error(str(error))
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
