"""Adapt a licensed synthetic policy snapshot without executing publisher code."""

from pathlib import Path
import hashlib
import json
import re


SOURCE = Path("data/outputs/research/sources/insurance-document-rag.json")
PUBLISHER = "https://github.com/ahmedabuzaid15-git/insurance-document-rag"
RESERVED = {"expatriate", "senior"}
QUESTIONS = {
    "Cover Levels": "Which inpatient and outpatient benefits does the {plan} cover?",
    "Exclusions": "Which services or circumstances are excluded by the {plan}?",
    "Waiting Periods": "When do consultation and maternity benefits start under the {plan}?",
    "Claims Procedure": "How and when must a treatment expense be filed under the {plan}?",
    "Geographic Scope": "Where does the {plan} provide coverage?",
    "Additional Terms": "What additional conditions apply to the {plan}?",
}


def _read_source(path):
    raw = Path(path).read_bytes()
    content = json.loads(raw)
    if (content["source"] != PUBLISHER or content["license"] != "MIT" or content["synthetic"] is not True
            or not content["license_text"].startswith("MIT License") or len(content["policies"]) != 20):
        raise ValueError("Expected the verified MIT synthetic insurance document corpus")
    return content, hashlib.sha256(raw).hexdigest()


def _sections(policy):
    path, text = Path(policy["path"]), policy["body"]
    if len(text.encode()) != policy["bytes"] or not re.fullmatch(r"[a-z]+_[a-z]+\.md", path.name):
        raise ValueError("Invalid source Markdown inventory")
    title = re.match(r"^# (.+)\n", text)
    if not title:
        raise ValueError("Invalid source document heading")
    parts = re.split(r"^## (.+)\n", text, flags=re.MULTILINE)
    sections = {name.strip(): " ".join(body.split()) for name, body in zip(parts[1::2], parts[2::2], strict=True)}
    if sections.keys() != QUESTIONS.keys() or not all(sections.values()):
        raise ValueError("Invalid source policy sections")
    return path.name, title[1], sections


def _gold(text):
    pattern = re.compile(
        r"^- id: (q\d+)\n  question: (\"[^\n]+\")\n  expected_doc: ([a-z]+_[a-z]+\.md)"
        r"\n  expected_section: (\"[^\n]+\")\n  unanswerable: false$",
        re.MULTILINE,
    )
    return [(item, json.loads(query), doc, json.loads(section))
            for item, query, doc, section in pattern.findall(text)]


def _rank_group(split, group_id, document, section, query, documents, filenames):
    title, parts = documents[document]
    other_doc = next(name for name in filenames if name != document)
    other_title, other_parts = documents[other_doc]
    other_sections = [name for name in parts if name != section]
    candidates = ((title, section, parts[section], True),
                  (title, other_sections[0], parts[other_sections[0]], False),
                  (title, other_sections[-1], parts[other_sections[-1]], False),
                  (other_title, section, other_parts[section], False))
    family = f"public-synthetic-{split}-{document.removesuffix('.md')}"
    return [{"id": f"{group_id}-{index}", "case_id": group_id, "family": family, "synthetic": True,
             "task": "rank", "kind": "policy", "query": query, "text": f"{plan}\n{heading}\n{passage}",
             "relevant": relevant}
            for index, (plan, heading, passage, relevant) in enumerate(candidates)]


def public_rank_rows(path):
    source, digest = _read_source(path)
    documents = {name: (title, sections) for name, title, sections in map(_sections, source["policies"])}
    if len(documents) != 20:
        raise ValueError("Source policy paths must be unique")
    train_docs, development_docs, test_docs = [], [], []
    for name in sorted(documents):
        variant = Path(name).stem.split("_")[1]
        (test_docs if variant in RESERVED else development_docs if variant == "family" else train_docs).append(name)
    training, development, heldout = [], [], []
    for split, files, rows in (("train", train_docs, training), ("validation", development_docs, development)):
        for name in files:
            for index, (section, template) in enumerate(QUESTIONS.items()):
                query = template.format(plan=documents[name][0])
                rows.extend(_rank_group(split, f"public-{split}-{name}-{index}", name, section, query,
                                        documents, files))
    gold = _gold(source["evaluation_questions_yaml"])
    if len(gold) != 15:
        raise ValueError("Publisher gold set changed or cannot be parsed")
    for key, query, doc, section in gold:
        if doc in test_docs:
            heldout.extend(_rank_group("test", f"public-heldout-{key}", doc, section, query, documents, test_docs))
    if not training or not heldout:
        raise ValueError("Public corpus needs usable secured splits")
    return training, development, heldout, {
        "source": PUBLISHER, "license": "MIT", "license_text": source["license_text"],
        "snapshot_sha256": digest, "train_documents": train_docs, "validation_documents": development_docs,
        "heldout_documents": test_docs,
        "unused_unanswerable_questions": 3,
    }
