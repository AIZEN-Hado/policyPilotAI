"""Prepare additional examples from the pinned public research inputs."""

from datetime import timedelta
import json
from pathlib import Path

from .artifacts import sha256_file, verify_manifest
from .data import _format_date, _render_document
from .public_policy_data import SOURCE, _gold, _read_source, _sections, public_rank_rows
from .research_data import CMS_URL, _digest, _read_cms


CMS_PREPARED = Path("data/outputs/research/cms-inpatient-sample1-v1")
CMS_ARCHIVE = Path("data/outputs/research/sources/cms-inpatient-sample1.zip")
CMS_SHA256 = "ac25124184d22863aff538607097d2d0c880d19f7d58f882f9d31129c492d893"
CMS_COUNTS = {"train": 1440, "validation": 240, "test": 320}
CMS_LAYOUTS = {
    "train": (
        "Hospital encounter {ref}. Inpatient admission took place on {ADMISSION_DATE}. "
        "The inpatient stay ended on {DISCHARGE_DATE}. Intake processed the claim on {notice}.",
        "{ref} / stay reconciliation\n{DISCHARGE_DATE} | final release\n{ADMISSION_DATE} | first inpatient day\n"
        "{notice} | clerical date",
        "Date of admission: {ADMISSION_DATE}; scheduled follow-up: {notice}. "
        "Discharged from inpatient care: {DISCHARGE_DATE}. Authority record {ref}.",
        "Clerk's ledger {ref}\nEntry onto the inpatient ward: {ADMISSION_DATE}\n"
        "Disposition to home: {DISCHARGE_DATE}\nOriginal form generated {notice}",
        "The patient's stay started {ADMISSION_DATE} and went through {DISCHARGE_DATE}. "
        "The paperwork reached the billing office on {notice}. Case index {ref}.",
        "{ref} / completed inpatient treatment\nPrinted {notice}. Actual release occurred {DISCHARGE_DATE}. "
        "Received as an admitted patient {ADMISSION_DATE}.",
    ),
    "validation": (
        "Referral audit {ref}, stamped {notice}. Entry for a completed admission was {ADMISSION_DATE}. "
        "Completed ward departure took place {DISCHARGE_DATE}.",
        "{ADMISSION_DATE} | inpatient episode opened\n{DISCHARGE_DATE} | cleared for departure\n"
        "{notice} | registrar's processing date\nReference {ref}",
        "The file {ref} was processed {notice}. Inpatient care opened on {ADMISSION_DATE}; "
        "the patient returned home on {DISCHARGE_DATE}.",
    ),
    "test": (
        "Initial occupancy of the inpatient facility was dated {ADMISSION_DATE}. "
        "The last day of care at the unit was {DISCHARGE_DATE}. Accounting docket {ref} was assembled {notice}.",
        "{ref} | final stay certification\n{DISCHARGE_DATE} | hospital release went ahead\n"
        "{notice} | the claim record arrived\n{ADMISSION_DATE} | the hospital first admitted the patient",
        "Case register {ref}. Patient taken into admitted care {ADMISSION_DATE}. "
        "Ward handed the patient over for home care {DISCHARGE_DATE}. Printed by registrar {notice}.",
        "This record {ref} fixes {ADMISSION_DATE} as the day admitted care began, and {DISCHARGE_DATE} "
        "as the day the patient left inpatient treatment. Retain the copy marked {notice}.",
    ),
}

PUBLIC_QUESTIONS = {
    "Cover Levels": ("Find the schedule of treatment benefits in {plan}.",
                     "What does the {plan} confirm about paid treatment and limits by benefit?"),
    "Exclusions": ("Locate the text on excluded treatment in {plan}.",
                   "Which kinds of treatment in the {plan} text are ineligible for payment?"),
    "Waiting Periods": ("Find the timing restrictions before benefits are active in {plan}.",
                        "Which passage in {plan} specifies the waiting intervals for relevant benefits?"),
    "Claims Procedure": ("Point to the filing instructions and submission deadlines in {plan}.",
                         "Which {plan} passage explains how a policyholder requests reimbursement?"),
    "Geographic Scope": ("What territory is covered by {plan}?", "Find where {plan} allows the member to receive treatment."),
    "Additional Terms": ("Find the supplemental policy conditions in {plan}.",
                         "Locate the extra contract terms applicable under {plan}."),
}


def cms_examples(root):
    prepared = root / CMS_PREPARED
    manifest = verify_manifest(prepared)
    if manifest["metadata"]["sha256"] != CMS_SHA256 or sha256_file(root / CMS_ARCHIVE) != CMS_SHA256:
        raise ValueError("CMS archive does not match the pinned acquisition")
    excluded = set()
    for split in CMS_COUNTS:
        for line in (prepared / f"{split}-lineage.jsonl").read_bytes().splitlines():
            excluded.add(json.loads(line)["synthetic_beneficiary_sha256"])
    stays, stats = _read_cms(root / CMS_ARCHIVE)
    by_beneficiary = {}
    for (group, admission, discharge), claim in stays.items():
        if group in excluded:
            continue
        reference = _digest("cms-transfer-v1", group, claim, admission.isoformat(), discharge.isoformat())
        item = (reference, admission, discharge)
        by_beneficiary[group] = min(item, by_beneficiary.get(group, item))
    groups = {split: [] for split in CMS_COUNTS}
    for group, (reference, admission, discharge) in by_beneficiary.items():
        bucket = int(group[:8], 16) % 100
        split = "train" if bucket < 70 else "validation" if bucket < 85 else "test"
        groups[split].append((reference, group, admission, discharge))
    output, fingerprints = {}, {}
    for split, count in CMS_COUNTS.items():
        output[split] = []
        selected = sorted(groups[split])[:count]
        if len(selected) != count:
            raise ValueError("CMS source has insufficient new beneficiaries")
        fingerprints[split] = _digest(*(group for _, group, _, _ in selected))
        for i, (reference, _, admission, discharge) in enumerate(selected):
            layout = i % len(CMS_LAYOUTS[split])
            style = ("iso", "dmy", "dotted", "written", "month-first")[i % 5]
            case_id = f"CMSX-{reference[:18]}"
            text, spans = _render_document(CMS_LAYOUTS[split][layout], {"ref": case_id,
                "ADMISSION_DATE": _format_date(admission, style), "DISCHARGE_DATE": _format_date(discharge, style),
                "notice": _format_date(discharge + timedelta(days=1 + i % 25), style)})
            output[split].append({"case_id": case_id, "id": case_id, "family": f"cms-transfer-{split}-{layout}",
                "task": "span", "kind": "claim_form", "synthetic": True, "text": text, "spans": spans})
    return output, {"sha256": CMS_SHA256, "source": CMS_URL, "license": "US public domain",
                    "source_counts": dict(stats), "new_beneficiaries": CMS_COUNTS,
                    "excluded_previous_beneficiaries": len(excluded), "lineage_digests": fingerprints}


def _public_group(split, ordinal, document, section, question, documents, partition):
    title, body = documents[document]
    other_sections = [heading for heading in body if heading != section]
    same_tier = [name for name in partition if name != document and name.split('_')[0] == document.split('_')[0]]
    different_plan = [name for name in partition if name != document and name not in same_tier]
    near_plans = (same_tier + different_plan)[:2]
    candidates = [(document, section), (document, other_sections[ordinal % len(other_sections)]),
                  *((name, section) for name in near_plans)]
    case = f"research-policy-{split}-{document[:-3]}-{ordinal:02d}"
    return [{"id": f"{case}-{i}", "case_id": case, "family": f"research-policy-{split}-{document[:-3]}",
             "task": "rank", "kind": "policy", "synthetic": True, "query": question,
             "text": f"{documents[name][0]}\n{heading}\n{documents[name][1][heading]}",
             "relevant": (name, heading) == (document, section)} for i, (name, heading) in enumerate(candidates)]


def policy_examples(root):
    source, fingerprint = _read_source(root / SOURCE)
    if fingerprint != "475035a7373f1f981cbfa7e1f958c6c224697554a48b77c4bf7552abc59ba50c":
        raise ValueError("Public policy snapshot differs from the recorded acquisition")
    documents = {name: (title, sections) for name, title, sections in map(_sections, source["policies"])}
    _, _, heldout, metadata = public_rank_rows(root / SOURCE)
    output = {"test": heldout}
    gold = _gold(source["evaluation_questions_yaml"])
    for split, key in (("train", "train_documents"), ("validation", "validation_documents")):
        partition = metadata[key]
        rows = []
        for document in partition:
            title = documents[document][0]
            questions = [(section, wording.format(plan=title)) for section, prompts in PUBLIC_QUESTIONS.items()
                         for wording in prompts]
            questions.extend((section, wording) for _, wording, doc, section in gold if doc == document)
            for number, (section, question) in enumerate(questions):
                rows.extend(_public_group(split, number, document, section, question, documents, partition))
        output[split] = rows
    return output, metadata
