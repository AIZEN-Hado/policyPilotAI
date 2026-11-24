"""Fit small score corrections on development data after self-training."""

import argparse
from collections import defaultdict
from itertools import product
import io
import json
from pathlib import Path
import tarfile

from .artifacts import sha256_file
from .contracts import SPAN_LABELS, TASKS
from .diagnose_quality_validation import _score
from .evaluate import load_verified_checkpoint, restore_models
from .evaluate_quality_run import _read_holdout, _require_host, summarize
from .features import BIO_IDS, decode_spans, feature_spec
from .joint_selection import best_assignments
from .models import build_models
from .run import verify_data
from .runtime import DATA_PATH, _batch_span, _encode_rows, _predict_rank, _read_rows
from .self_learning import TEACHER_FILE
from .span_context import _candidate_tokens, _clause_roles, _cue_occurrences, _expanded_phrases
from .structured import value_candidates


TARGET = 0.95
BASE_SPAN = (1.0, 0.0, 0.0, 0.0, 0.0)
BASE_RANK = (1.0, 0.0, 0.0)
ROLES = dict(zip(SPAN_LABELS, ("policy", "member", "arrival", "departure", "room", "sum"), strict=True))


def _checkpoints(torch, archive, sha, dataset_sha, config_sha):
    config, weights = load_verified_checkpoint(archive, sha, dataset_sha, config_sha256=config_sha)
    with tarfile.open(archive, "r:gz") as bundle:
        reload = json.load(bundle.extractfile("reload.json"))
        if reload.get("teacher_predictions_match") is not True:
            raise ValueError("Calibrate only a verified teacher and student pair")
        teacher_state = torch.load(io.BytesIO(bundle.extractfile(TEACHER_FILE).read()), map_location="cpu", weights_only=True)
    teacher = build_models(torch, config)
    for task, model in teacher.items():
        model.load_state_dict(teacher_state[task], strict=True)
        model.eval()
    student = restore_models(torch, config, weights)
    for model in student.values():
        model.eval()
    return config, teacher, student


def _context(text, offsets):
    words = [text[a:b].casefold() for a, b in offsets]
    occurrences = _cue_occurrences(words, _expanded_phrases())
    lines, previous, line = [], 0, 0
    for left, right in offsets:
        line += text.count("\n", previous, left)
        lines.append(line)
        previous = right
    return words, occurrences, lines, _candidate_tokens(text, offsets)


def _span_records(torch, config, teacher, student, examples):
    result = {}
    size = config["training"]["batch_size"]
    with torch.inference_mode():
        for start in range(0, len(examples), size):
            batch = examples[start:start + size]
            args, _ = _batch_span(torch, batch, torch.device("cpu"))
            old_values, new_values = (model(*args).tolist() for model in (teacher, student))
            for (row, encoded), old, new in zip(batch, old_values, new_values, strict=True):
                offsets = encoded["offsets"]
                choices = value_candidates(row["text"], offsets)
                words, occurrences, lines, positions = _context(row["text"], offsets)
                fields = {}
                for label, intervals in choices.items():
                    kind = "date" if label.endswith("_DATE") else "identifier" if label.endswith("_ID") else "amount"
                    candidates = []
                    for left, right in intervals:
                        cues = _clause_roles(left, right, occurrences, words, lines, positions, kind)
                        roles = {entry.split(":")[1] for entry in cues}
                        candidates.append((left, right, _score(old, label, left, right), _score(new, label, left, right),
                                           ROLES[label] in roles, "current" in roles,
                                           bool(roles & {"administrative", "excluded", "reference"})))
                    fields[label] = candidates
                result[row["id"]] = (offsets, fields)
    return result


def _span_score(candidate, settings):
    _, _, teacher, student, role, current, competing = candidate
    mix, bias, role_weight, active_weight, competing_weight = settings
    return (1 - mix) * teacher + mix * student + bias + role_weight * role + active_weight * current + competing_weight * competing


def _fit_span(rows, records):
    profiles = ((1, 0, 0, 0), (.75, 0, 0, 0), (.5, 0, 0, 0), (1, 3, 1.5, -3),
                (.75, 4, 2, -4), (1, 6, 3, -6), (.75, 8, 4, -8))
    grid = [BASE_SPAN] + [(mix, bias, role, active, competing) for (mix, role, active, competing), bias
                          in product(profiles, (-6, -3, -1, 0, 1, 2.5, 4, 6))]
    fitted = {}
    for label in SPAN_LABELS:
        examples = []
        for row in rows:
            offsets, fields = records[row["id"]]
            gold = next(((p["start"], p["end"]) for p in row["spans"] if p["label"] == label), None)
            examples.append((gold, [(candidate, (offsets[candidate[0]][0], offsets[candidate[1]][1]))
                                    for candidate in fields[label]]))
        expected = sum(gold is not None for gold, _ in examples)
        if not expected:
            raise ValueError("Calibration samples must support every field")

        def quality(settings):
            correct = predicted = 0
            for gold, candidates in examples:
                winner = max(((_span_score(candidate, settings), offset) for candidate, offset in candidates),
                             default=(0, None))
                if winner[0] > 0:
                    correct += winner[1] == gold
                    predicted += 1
            return (min(correct / max(1, predicted), correct / expected), 2 * correct / (expected + predicted))

        fitted[label] = max(grid, key=quality)
    return fitted


def _rank_records(torch, config, teacher, student, examples):
    batch_size = config["training"]["batch_size"]
    left = _predict_rank(torch, teacher, examples, batch_size, torch.device("cpu"), structured=True)
    right = _predict_rank(torch, student, examples, batch_size, torch.device("cpu"), structured=True)
    names = feature_spec(config["rank"])["rank_scalar_features"]
    positions = [names.index(key) for key in ("authority_overlap", "different_authority", "purpose_overlap", "different_purpose")]
    grouped = defaultdict(list)
    for (row, features), old, new in zip(examples, left, right, strict=True):
        hit, conflict, purpose, wrong_purpose = (features[index] for index in positions)
        grouped[row["case_id"], row["query"]].append((row, old, new, hit - conflict, purpose - wrong_purpose))
    result = []
    for group in grouped.values():
        old, new = ([entry[index] for entry in group] for index in (1, 2))
        old_range, new_range = max(old) - min(old), max(new) - min(new)
        result.append([(row, (old_score - min(old)) / max(1e-6, old_range),
                        (new_score - min(new)) / max(1e-6, new_range), authority, purpose)
                       for row, old_score, new_score, authority, purpose in group])
    return result


def _rank_score(record, settings):
    _, teacher, student, authority, purpose = record
    mix, authority_weight, purpose_weight = settings
    return (1 - mix) * teacher + mix * student + authority_weight * authority + purpose_weight * purpose


def _fit_rank(groups):
    grid = [BASE_RANK] + list(product((1, .75, .5, .25, 0), (0, .1, .25, .5, 1), (0, .1, .25, .5, 1)))

    def accuracy(settings):
        correct = 0
        for group in groups:
            scores = [_rank_score(record, settings) for record in group]
            maximum = max(scores)
            best = [record[0]["relevant"] for record, score in zip(group, scores, strict=True) if score == maximum]
            correct += best == [True]
        return correct

    return max(grid, key=accuracy)


def _report(rows, sources, spans, rank, span_settings, rank_settings):
    span_predictions = []
    for row in rows["span"]:
        offsets, fields = spans[row["id"]]
        scores = [(candidate[0], candidate[1], label, _span_score(candidate, span_settings[label]))
                  for label, candidates in fields.items() for candidate in candidates]
        _, assignments = best_assignments(scores)
        tags = [BIO_IDS["O"]] * len(offsets)
        for left, right, label in assignments:
            tags[left] = BIO_IDS[f"B-{label}"]
            tags[left + 1:right + 1] = [BIO_IDS[f"I-{label}"]] * (right - left)
        span_predictions.append({"id": row["id"], "spans": decode_spans(row["text"], offsets, tags)})
    rank_predictions = [{"id": record[0]["id"], "score": _rank_score(record, rank_settings)}
                        for group in rank for record in group]
    return summarize(rows, {"span": {"predictions": span_predictions}, "rank": {"predictions": rank_predictions}},
                     sources, target=TARGET)


def _development(runtime, dataset_sha):
    data = runtime / DATA_PATH
    if verify_data(data) != dataset_sha:
        raise ValueError("Calibration development data does not match the trained archive")
    files = json.loads((data / "manifest.json").read_bytes())["files"]
    return {task: _read_rows(data / name, task, files[name]) for task in TASKS
            for name in [f"validation-{task}.jsonl"]}


def _records(torch, config, teacher, student, rows):
    encoded = _encode_rows(rows, config)
    return (_span_records(torch, config, teacher["span"], student["span"], encoded["span"]),
            _rank_records(torch, config, teacher["rank"], student["rank"], encoded["rank"]))


def _source_map(rows):
    return {row["family"]: "synthetic_development" for task in TASKS for row in rows[task]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("fit", "evaluate"))
    for name in ("archive", "runtime", "calibration"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    for name in ("archive-sha256", "dataset-sha256", "config-sha256"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--holdout", type=Path)
    parser.add_argument("--holdout-sha256")
    parser.add_argument("--calibration-sha256")
    args = parser.parse_args()
    _require_host("runpod-cpu", [args.archive, args.calibration], args.holdout or Path("/tmp"))

    import torch

    if torch.cuda.is_available() or torch.cuda.device_count():
        raise RuntimeError("Use a hosted CPU Pod")
    torch.set_num_threads(2)
    config, teacher, student = _checkpoints(torch, args.archive, args.archive_sha256, args.dataset_sha256, args.config_sha256)
    original = {field: BASE_SPAN for field in SPAN_LABELS}
    if args.mode == "fit":
        rows = _development(args.runtime, args.dataset_sha256)
        span, rank = _records(torch, config, teacher, student, rows)
        span_settings, rank_settings = _fit_span(rows["span"], span), _fit_rank(rank)
        sources = _source_map(rows)
        before = _report(rows, sources, span, rank, original, BASE_RANK)
        after = _report(rows, sources, span, rank, span_settings, rank_settings)
        if after["span"]["exact_span"]["f1"] < before["span"]["exact_span"]["f1"]:
            span_settings = original
        summary = {"before": {"span": before["span"]["exact_span"], "rank": before["rank"]},
                   "after": {"span": _report(rows, sources, span, rank, span_settings, rank_settings)["span"]["exact_span"],
                             "rank": after["rank"]}}
        with args.calibration.open("x") as stream:
            json.dump({"schema_version": 1, "checkpoint_sha256": args.archive_sha256, "dataset_sha256": args.dataset_sha256,
                       "span": span_settings, "rank": rank_settings}, stream, sort_keys=True, allow_nan=False)
        report = {"scope": "development_calibration", "calibration_sha256": sha256_file(args.calibration), "development": summary}
    else:
        if sha256_file(args.calibration) != args.calibration_sha256 or not args.holdout:
            raise ValueError("Supply the frozen calibration artifact and holdout")
        calibrated = json.loads(args.calibration.read_bytes())
        if (calibrated["checkpoint_sha256"], calibrated["dataset_sha256"]) != (args.archive_sha256, args.dataset_sha256):
            raise ValueError("Calibration artifact belongs to a different checkpoint")
        rows, sources = _read_holdout(args.holdout, args.holdout_sha256)
        span, rank = _records(torch, config, teacher, student, rows)
        report = {"scope": "new_synthetic_holdout", "target": TARGET, "holdout_manifest_sha256": args.holdout_sha256,
                  "checkpoint_sha256": args.archive_sha256, "calibration_sha256": args.calibration_sha256,
                  "reports": {"student": _report(rows, sources, span, rank, original, BASE_RANK),
                              "calibrated": _report(rows, sources, span, rank, calibrated["span"], calibrated["rank"])}}
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
