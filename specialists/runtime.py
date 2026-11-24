"""Run the bounded specialist stages in the guarded GPU pod child process."""

import argparse
import hashlib
import json
import math
import os
import random
import re
import resource
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

from .artifacts import SOURCE_MAX_BYTES, _open_regular, sha256_file, verify_manifest
from .contracts import SPAN_LABELS, TASKS, validate_row
from .execution import require_remote
from .features import (
    BIO_IDS, BIO_TAGS, PAD_ID, RANK_CUE_GROUPS, decode_spans, encode_span,
    feature_spec, lexical_terms, ranking_features,
)
from .models import MAX_WEIGHT_BYTES, build_models, parameter_estimate


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path("specialists/config.json")
DATA_PATH = Path("data/synthetic/specialists-v1")
DATA_FILES = {f"{split}-{task}.jsonl" for split in ("train", "validation") for task in TASKS}
CONFIG_FINGERPRINT_ENV = "POLICYPILOT_SPECIALIST_CONFIG_SHA256"
DATA_FINGERPRINT_ENV = "POLICYPILOT_SPECIALIST_DATA_MANIFEST_SHA256"
STAGES = ("baseline", "train", "reload")
RANK_THRESHOLD = 0.5
TAG_IGNORE = -100
ARCHITECTURES = {"span": "word-hash-char-cnn-bilstm-bio", "rank": "lexical-feature-mlp"}

IDENTIFIER = r"[A-Z0-9]+(?:[-/][A-Z0-9]+)+|[A-Z0-9]*[0-9][A-Z0-9]*"
DATE = (
    r"\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{4}"
    r"|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}"
)
AMOUNT = r"(?:₹\s*|(?:INR|Rs\.?)\s+)?\d+(?:,\d+)*(?:\.\d+)?(?:\s+INR)?"
BASELINE_PATTERNS = {
    "POLICY_ID": (r"policy\s+(?:number|no\.?|id|identifier)", IDENTIFIER),
    "MEMBER_ID": (r"(?:member|beneficiary)\s+(?:number|no\.?|id|identifier)", IDENTIFIER),
    "ADMISSION_DATE": (r"admission\s+date|date\s+of\s+admission", DATE),
    "DISCHARGE_DATE": (r"discharge\s+date|date\s+of\s+discharge", DATE),
    "ROOM_LIMIT": (r"maximum\s+room\s+and\s+board\s+per\s+day|room\s+(?:rent\s+)?limit", AMOUNT),
    "SUM_INSURED": (r"(?:base\s+)?sum\s+insured", AMOUNT),
}
BASELINE_SPAN_RULES = {
    label: re.compile(rf"\b(?:{hint})\s*[:=–—-]?\s*(?P<value>{value})(?!\w)", re.IGNORECASE)
    for label, (hint, value) in BASELINE_PATTERNS.items()
}


def _verified_bytes(path, expected):
    with _open_regular(path) as stream:
        content = stream.read(expected["bytes"] + 1)
    if len(content) != expected["bytes"] or hashlib.sha256(content).hexdigest() != expected["sha256"]:
        raise ValueError(f"Verified input fingerprint or size changed: {path.name}")
    return content


def _load_inputs(project_root, config_path, data_directory):
    if config_path != project_root / CONFIG_PATH or data_directory != project_root / DATA_PATH:
        raise ValueError("Use the configuration and dataset from the verified runtime source")
    config_hash = os.environ.get(CONFIG_FINGERPRINT_ENV, "")
    manifest_hash = os.environ.get(DATA_FINGERPRINT_ENV, "")
    if any(not re.fullmatch(r"[0-9a-f]{64}", value) for value in (config_hash, manifest_hash)):
        raise ValueError("The specialist launcher must provide the config and dataset manifest fingerprints")

    source_manifest = verify_manifest(project_root, max_bytes=SOURCE_MAX_BYTES)
    source_files = {entry["path"]: entry for entry in source_manifest["files"]}
    config_entry = source_files[CONFIG_PATH.as_posix()]
    manifest_entry = source_files[(DATA_PATH / "manifest.json").as_posix()]
    if config_hash != config_entry["sha256"] or manifest_hash != manifest_entry["sha256"]:
        raise ValueError("Runtime source inputs differ from the launcher fingerprints")
    config = json.loads(_verified_bytes(config_path, config_entry))
    manifest = json.loads(_verified_bytes(data_directory / "manifest.json", manifest_entry))
    if manifest.get("schema_version") != 1 or manifest.get("synthetic_only") is not True:
        raise ValueError("Require the version 1 synthetic dataset manifest")
    files = manifest["files"]
    if files.keys() != DATA_FILES:
        raise ValueError("Require exactly the prepared train and validation files")
    for name, entry in files.items():
        source_entry = source_files[(DATA_PATH / name).as_posix()]
        if any(entry[key] != source_entry[key] for key in ("sha256", "bytes")):
            raise ValueError(f"Prepared dataset and runtime source manifest disagree: {name}")
    fingerprints = {
        "config_sha256": config_hash,
        "dataset_manifest_sha256": manifest_hash,
        "files": {name: entry["sha256"] for name, entry in files.items()},
    }
    return config, files, fingerprints


def _read_rows(path, task, expected):
    content = _verified_bytes(path, expected)
    rows = []
    for line_number, line in enumerate(content.splitlines(), 1):
        try:
            row = json.loads(line)
            validate_row(row)
            if row["task"] != task:
                raise ValueError("Task fields do not match the file name")
        except ValueError as exc:
            raise ValueError(f"Invalid {path.name} row {line_number}: {exc}") from exc
        rows.append(row)
    if not rows or len(rows) != expected["rows"] or len({row["id"] for row in rows}) != len(rows):
        raise ValueError(f"{path.name} must contain the expected number of rows with unique IDs")
    return rows


def _read_split(data_directory, split, config, files):
    rows = {}
    for task in TASKS:
        name = f"{split}-{task}.jsonl"
        rows[task] = _read_rows(data_directory / name, task, files[name])
    return _encode_rows(rows, config)


def _encode_span(row, config):
    contextual_values = config.get("contextual_values", False)
    if type(contextual_values) is not bool:
        raise ValueError("Invalid contextual_values setting")
    if contextual_values:
        from .span_context import encode_contextual_span

        return encode_contextual_span(row, config)
    return encode_span(row, config)


def _feature_spec(config):
    features = feature_spec(config["rank"])
    if config["span"].get("contextual_values", False):
        from .span_context import CONTEXT_VERSION

        version = config["span"].get("context_feature_version", CONTEXT_VERSION)
        features = {**features, "span_context_version": version}
        if version == 2:
            from .semantic_cues import SPAN_CUES

            features["span_additional_cues"] = {role: list(phrases) for role, phrases in SPAN_CUES.items()}
    return features


def _encode_rows(rows, config):
    return {
        "span": [(row, _encode_span(row, config["span"])) for row in rows["span"]],
        "rank": [
            (row, ranking_features(row["query"], row["text"], row["kind"], config["rank"]))
            for row in rows["rank"]
        ],
    }


def _prf(correct, predicted, expected):
    precision = correct / predicted if predicted else 0.0
    recall = correct / expected if expected else 0.0
    f1 = 2 * correct / (predicted + expected) if predicted + expected else 0.0
    return {"precision": precision, "recall": recall, "f1": f1, "support": expected}


def _span_report(examples, predicted_tags):
    predictions = []
    exact_counts = {label: [0, 0, 0] for label in SPAN_LABELS}
    entity_tokens = [0, 0, 0]
    correct_tokens = 0
    token_count = 0
    for (row, encoded), tags in zip(examples, predicted_tags, strict=True):
        spans = decode_spans(row["text"], encoded["offsets"], tags)
        predictions.append({"id": row["id"], "tag_ids": tags, "spans": spans})
        expected = {(span["label"], span["start"], span["end"]) for span in row["spans"]}
        predicted = {(span["label"], span["start"], span["end"]) for span in spans}
        for label, *_ in expected & predicted:
            exact_counts[label][0] += 1
        for label, *_ in predicted:
            exact_counts[label][1] += 1
        for label, *_ in expected:
            exact_counts[label][2] += 1
        for gold_tag, predicted_tag in zip(encoded["tags"], tags, strict=True):
            correct_tokens += predicted_tag == gold_tag
            token_count += 1
            entity_tokens[0] += predicted_tag == gold_tag != BIO_IDS["O"]
            entity_tokens[1] += predicted_tag != BIO_IDS["O"]
            entity_tokens[2] += gold_tag != BIO_IDS["O"]

    metrics = {
        "exact_span": _prf(*(sum(counts) for counts in zip(*exact_counts.values()))),
        "exact_span_by_label": {label: _prf(*counts) for label, counts in exact_counts.items()},
        "entity_token": _prf(*entity_tokens),
        "token_accuracy": correct_tokens / token_count,
        "rows": len(examples),
        "tokens": token_count,
    }
    return {"metrics": metrics, "predictions": predictions}


def _rank_report(examples, scores):
    groups = defaultdict(list)
    predictions = []
    positives = [0, 0, 0]
    correct = 0
    for (row, _), score in zip(examples, scores, strict=True):
        predicted = score >= RANK_THRESHOLD
        relevant = row["relevant"]
        groups[row["case_id"], row["query"]].append((score, relevant))
        predictions.append({"id": row["id"], "score": score, "predicted_relevant": predicted})
        correct += predicted == relevant
        positives[0] += predicted and relevant
        positives[1] += predicted
        positives[2] += relevant

    top1 = 0.0
    strict_top1 = 0
    pairwise_total = 0.0
    pairs = 0
    for group in groups.values():
        best = max(score for score, _ in group)
        tied = [relevant for score, relevant in group if score == best]
        top1 += sum(tied) / len(tied)
        strict_top1 += len(tied) == 1 and tied[0]
        for high, relevant in group:
            if relevant:
                for low, other_relevant in group:
                    if not other_relevant:
                        pairwise_total += 1 if high > low else 0.5 if high == low else 0
                        pairs += 1

    metrics = {
        "classification": _prf(*positives),
        "accuracy": correct / len(examples),
        "threshold": RANK_THRESHOLD,
        "group_top1_accuracy": top1 / len(groups),
        "strict_group_top1_accuracy": strict_top1 / len(groups),
        "pairwise_accuracy": pairwise_total / pairs if pairs else None,
        "groups": len(groups),
        "rows": len(examples),
    }
    return {"metrics": metrics, "predictions": predictions}


def _baseline_tags(row, encoded):
    tags = [BIO_IDS["O"]] * len(encoded["offsets"])
    starts = {start: index for index, (start, _) in enumerate(encoded["offsets"])}
    ends = {end: index for index, (_, end) in enumerate(encoded["offsets"])}
    for label, rule in BASELINE_SPAN_RULES.items():
        for match in rule.finditer(row["text"]):
            start = starts.get(match.start("value"))
            end = ends.get(match.end("value"))
            if start is None or end is None or any(tags[start:end + 1]):
                continue
            tags[start] = BIO_IDS[f"B-{label}"]
            for index in range(start + 1, end + 1):
                tags[index] = BIO_IDS[f"I-{label}"]
    return tags


def _baseline_score(row):
    query = set(lexical_terms(row["query"]))
    text = set(lexical_terms(row["text"]))
    relevant_cues = [terms for name, terms in RANK_CUE_GROUPS.items() if name != "excluded" and query & terms]
    overlap = len(query & text) / max(1, len(query))
    cue_overlap = sum(bool(terms & text) for terms in relevant_cues) / max(1, len(relevant_cues))
    score = 0.5 * (overlap + cue_overlap) - 0.25 * bool(text & RANK_CUE_GROUPS["excluded"])
    return max(0.0, min(1.0, score))


def _run_baseline(validation):
    span_tags = [_baseline_tags(row, encoded) for row, encoded in validation["span"]]
    rank_scores = [_baseline_score(row) for row, _ in validation["rank"]]
    return {
        "split": "validation",
        "method": "rules_and_lexical_overlap",
        "span": _span_report(validation["span"], span_tags),
        "rank": _rank_report(validation["rank"], rank_scores),
    }


def _batch_span(torch, examples, device):
    lengths = [len(encoded["word_ids"]) for _, encoded in examples]
    n_tokens = max(lengths)
    n_chars = max(len(chars) for _, encoded in examples for chars in encoded["char_ids"])
    words, characters, tags = [], [], []
    for (_, encoded), length in zip(examples, lengths, strict=True):
        token_padding = n_tokens - length
        words.append(encoded["word_ids"] + [PAD_ID] * token_padding)
        characters.append(
            [chars + [PAD_ID] * (n_chars - len(chars)) for chars in encoded["char_ids"]]
            + [[PAD_ID] * n_chars] * token_padding
        )
        tags.append(encoded["tags"] + [TAG_IGNORE] * token_padding)
    return (
        torch.tensor(words, dtype=torch.long, device=device),
        torch.tensor(characters, dtype=torch.long, device=device),
        lengths,
    ), torch.tensor(tags, dtype=torch.long, device=device)


def _batch_rank(torch, examples, device):
    features = torch.tensor([values for _, values in examples], dtype=torch.float32, device=device)
    targets = torch.tensor([row["relevant"] for row, _ in examples], dtype=torch.float32, device=device)
    return (features,), targets


BATCHERS = {"span": _batch_span, "rank": _batch_rank}


def _train_model(torch, model, task, examples, training, device):
    model.train()
    optimizer = torch.optim.AdamW(model.parameters(), lr=training["learning_rate"])
    batcher = BATCHERS[task]
    order = list(range(len(examples)))
    rng = random.Random(training["seed"])
    result = {}
    if task == "span":
        # Train targets alone determine the weights for rare entity tokens.
        frequencies = Counter(tag for _, encoded in examples for tag in encoded["tags"])
        largest = max(frequencies.values())
        weights = [math.sqrt(largest / frequencies[tag]) if frequencies[tag] else 1.0 for tag in range(len(BIO_TAGS))]
        loss_fn = torch.nn.CrossEntropyLoss(
            weight=torch.tensor(weights, dtype=torch.float32, device=device), ignore_index=TAG_IGNORE,
        )
        result["class_weights"] = dict(zip(BIO_TAGS, weights, strict=True))
    else:
        loss_fn = torch.nn.BCEWithLogitsLoss()
    total_loss = 0.0
    steps = 0
    for _ in range(training["epochs"]):
        rng.shuffle(order)
        for start in range(0, len(order), training["batch_size"]):
            indices = order[start:start + training["batch_size"]]
            inputs, target = batcher(torch, [examples[index] for index in indices], device)
            optimizer.zero_grad(set_to_none=True)
            logits = model(*inputs)
            if task == "span":
                logits = logits.transpose(1, 2)
            loss = loss_fn(logits, target)
            value = loss.item()
            if not math.isfinite(value):
                raise RuntimeError(f"{task} training loss is not finite")
            loss.backward()
            optimizer.step()
            steps += 1
            total_loss += value
            if steps == training["max_steps"]:
                return {**result, "steps": steps, "mean_batch_loss": total_loss / steps}
    return {**result, "steps": steps, "mean_batch_loss": total_loss / steps}


def _predict_spans(torch, model, examples, batch_size, device, structured):
    if structured:
        from .structured import select_tags, value_candidates

    model.eval()
    paths = []
    with torch.inference_mode():
        for start in range(0, len(examples), batch_size):
            batch = examples[start:start + batch_size]
            inputs, _ = _batch_span(torch, batch, device)
            logits = model(*inputs)
            if not torch.isfinite(logits).all().item():
                raise RuntimeError("Span validation logits are not finite")
            if structured:
                for (row, encoded), values, size in zip(batch, logits.cpu().tolist(), inputs[-1], strict=True):
                    choices = value_candidates(row["text"], encoded["offsets"])
                    paths.append(select_tags(values[:size], choices))
            else:
                tags = logits.argmax(dim=-1).cpu().tolist()
                paths.extend(path[:size] for path, size in zip(tags, inputs[-1], strict=True))
    return paths


def _predict_rank(torch, model, examples, batch_size, device, structured):
    model.eval()
    scores = []
    with torch.inference_mode():
        for start in range(0, len(examples), batch_size):
            inputs, _ = _batch_rank(torch, examples[start:start + batch_size], device)
            logits = model(*inputs)
            if not torch.isfinite(logits).all().item():
                raise RuntimeError("Rank validation logits are not finite")
            # Listwise scores are for ordering and have no calibrated 0.5 threshold.
            scores.extend((logits if structured else logits.sigmoid()).cpu().tolist())
    return scores


def _evaluate(torch, models, validation, batch_size, device, *, structured=False):
    span_tags = _predict_spans(torch, models["span"], validation["span"], batch_size, device, structured)
    scores = _predict_rank(torch, models["rank"], validation["rank"], batch_size, device, structured)
    rank = _rank_report(validation["rank"], scores)
    if structured:
        for prediction in rank["predictions"]:
            prediction.pop("predicted_relevant")
        for key in ("accuracy", "classification", "threshold"):
            rank["metrics"].pop(key)
    return {
        "split": "validation",
        "method": "neural_specialists",
        "span": _span_report(validation["span"], span_tags),
        "rank": rank,
    }


def _train_structured(torch, model, task, examples, validation, training, device, *, macro_span=False):
    from .structured import candidate_loss, candidate_supervision, rank_group_loss, rank_groups

    if task == "span":
        units = []
        for row, encoded in examples:
            choices, targets = candidate_supervision(row, encoded)
            units.append((row, {**encoded, "choices": choices, "targets": targets}))
    else:
        units = rank_groups(examples)
    batch_size = training["batch_size"]
    steps_per_epoch = math.ceil(len(units) / batch_size)
    if steps_per_epoch * training["epochs"] > training["max_steps"]:
        raise ValueError(f"{task} max_steps cannot cover the configured complete epochs")

    optimizer = torch.optim.AdamW(model.parameters(), lr=training["learning_rate"])
    rng = random.Random(training["seed"])
    history = []
    best_score, best_state, best_epoch = -1, None, None
    for epoch in range(1, training["epochs"] + 1):
        model.train()
        rng.shuffle(units)
        total_loss = 0.0
        for start in range(0, len(units), batch_size):
            batch = units[start:start + batch_size]
            optimizer.zero_grad(set_to_none=True)
            if task == "span":
                inputs, _ = _batch_span(torch, batch, device)
                loss = candidate_loss(torch, model(*inputs), batch)
            else:
                inputs, targets = _batch_rank(torch, [example for group in batch for example in group], device)
                loss = rank_group_loss(torch, model(*inputs), targets, [len(group) for group in batch])
            value = loss.item()
            if not math.isfinite(value):
                raise RuntimeError(f"{task} training loss is not finite")
            loss.backward()
            optimizer.step()
            total_loss += value

        if task == "span":
            predictions = _predict_spans(torch, model, validation, batch_size, device, structured=True)
            metrics = _span_report(validation, predictions)["metrics"]
            if macro_span:
                field_scores = [entry["f1"] for entry in metrics["exact_span_by_label"].values() if entry["support"]]
                score = sum(field_scores) / len(field_scores) if field_scores else 0.0
            else:
                score = metrics["exact_span"]["f1"]
        else:
            predictions = _predict_rank(torch, model, validation, batch_size, device, structured=True)
            metrics = _rank_report(validation, predictions)["metrics"]
            score = metrics["strict_group_top1_accuracy"]
        history.append({"epoch": epoch, "loss": total_loss / steps_per_epoch, "validation_score": score})
        if score > best_score:
            best_score, best_epoch = score, epoch
            best_state = {name: tensor.detach().cpu().clone() for name, tensor in model.state_dict().items()}

    model.load_state_dict(best_state)
    result = {"steps": steps_per_epoch * len(history), "selected_epoch": best_epoch, "epochs": history}
    if task == "span" and macro_span:
        result["selection_metric"] = "macro_exact_span_f1"
    return result


def _save(path, writer):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            writer(stream)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _save_json(path, value):
    payload = json.dumps(value, indent=2, sort_keys=True, allow_nan=False).encode() + b"\n"
    _save(path, lambda stream: stream.write(payload))


def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _measurements(torch, device):
    if device.type == "cpu":
        return {"device": "cpu", "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024}
    return {
        "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "cuda_peak_allocated_bytes": torch.cuda.max_memory_allocated(device),
        "cuda_peak_reserved_bytes": torch.cuda.max_memory_reserved(device),
        "cuda_device_name": torch.cuda.get_device_name(device),
    }


def _train_and_export(torch, models, config, train, validation, output_directory, fingerprints, device, pool=None):
    training = config["training"]
    structured = training.get("structured_objectives", False)
    if structured:
        results = {
            task: _train_structured(torch, models[task], task, train[task], validation[task], training, device,
                                    macro_span=config["span"].get("contextual_values", False))
            for task in TASKS
        }
    else:
        results = {task: _train_model(torch, models[task], task, train[task], training, device) for task in TASKS}
    self_training = None
    if pool is not None:
        from .self_learning import learn

        self_training = learn(torch, models, config, train, validation, output_directory, device, pool)
    validation_path = output_directory / "validation.json"
    report = _evaluate(torch, models, validation, training["batch_size"], device, structured=structured)
    report["input_fingerprints"] = fingerprints
    _save_json(validation_path, report)
    weights = {}
    for task, model in models.items():
        state = {name: tensor.detach().cpu() for name, tensor in model.state_dict().items()}
        target = output_directory / f"{task}.pt"
        _save(target, lambda stream: torch.save(state, stream))
        weights[task] = {"path": target.name, "bytes": target.stat().st_size, "sha256": sha256_file(target)}
    if sum(item["bytes"] for item in weights.values()) > min(config["max_weight_bytes"], MAX_WEIGHT_BYTES):
        raise RuntimeError("Serialized state dictionaries exceed the combined weight budget")
    metadata = {
        "schema_version": 1,
        "architectures": ARCHITECTURES,
        "config": config,
        "input_fingerprints": fingerprints,
        "parameters": parameter_estimate(config),
        "features": _feature_spec(config),
        "training_updates": results,
        "weights": weights,
        "validation_sha256": sha256_file(validation_path),
        "remote_measurements": _measurements(torch, device),
    }
    if self_training is not None:
        metadata["self_training"] = self_training
    _save_json(output_directory / "metadata.json", metadata)
    return report


def _reload(torch, models, config, output_directory, validation, fingerprints, device):
    metadata = _read_json(output_directory / "metadata.json")
    if (
        metadata["schema_version"] != 1
        or metadata["config"] != config
        or metadata["input_fingerprints"] != fingerprints
        or metadata["architectures"] != ARCHITECTURES
        or metadata["parameters"] != parameter_estimate(config)
        or metadata["features"] != _feature_spec(config)
    ):
        raise ValueError("Saved specialist input fingerprints, configuration, or feature specification differ from runtime")
    size_total = 0
    verified_paths = {}
    for task in models:
        checkpoint = metadata["weights"][task]
        path = output_directory / f"{task}.pt"
        size = path.stat().st_size
        if (
            path.name != checkpoint["path"]
            or size != checkpoint["bytes"]
            or size > min(config["max_weight_bytes"], MAX_WEIGHT_BYTES)
            or sha256_file(path) != checkpoint["sha256"]
        ):
            raise ValueError(f"Checkpoint fingerprint or size mismatch for {task}")
        size_total += size
        verified_paths[task] = path
    if size_total > min(config["max_weight_bytes"], MAX_WEIGHT_BYTES):
        raise ValueError("Combined checkpoint size exceeds the weight budget")
    for task, model in models.items():
        state = torch.load(verified_paths[task], map_location="cpu", weights_only=True)
        model.load_state_dict(state, strict=True)

    validation_path = output_directory / "validation.json"
    if sha256_file(validation_path) != metadata["validation_sha256"]:
        raise ValueError("Frozen validation report fingerprint mismatch")
    expected = _read_json(validation_path)
    training = config["training"]
    actual = _evaluate(torch, models, validation, training["batch_size"], device,
                       structured=training.get("structured_objectives", False))
    spans_match = expected["span"]["predictions"] == actual["span"]["predictions"]
    before = expected["rank"]["predictions"]
    after = actual["rank"]["predictions"]
    tolerance = 1e-6
    rank_match = len(before) == len(after) and all(
        left["id"] == right["id"]
        and left.get("predicted_relevant") == right.get("predicted_relevant")
        and math.isclose(left["score"], right["score"], rel_tol=0, abs_tol=tolerance)
        for left, right in zip(before, after)
    )
    passed = spans_match and rank_match
    teacher_match = None
    if "self_training" in metadata:
        from .self_learning import TEACHER_FILE, prediction_fingerprint

        teacher_path = output_directory / TEACHER_FILE
        teacher_config = metadata["self_training"]
        if teacher_path.stat().st_size != teacher_config["teacher_bytes"] or teacher_path.stat().st_size > MAX_WEIGHT_BYTES:
            raise ValueError("Supervised checkpoint size differs from training metadata")
        teacher_state = torch.load(teacher_path, map_location="cpu", weights_only=True)
        teacher_models = build_models(torch, config)
        for task, model in teacher_models.items():
            model.load_state_dict(teacher_state[task], strict=True)
            model.to(device)
        teacher_report = _evaluate(torch, teacher_models, validation, training["batch_size"], device, structured=True)
        teacher_match = prediction_fingerprint(teacher_report) == teacher_config["teacher_validation_fingerprint"]
        passed &= teacher_match
    report = {
        "split": "validation",
        "input_fingerprints": fingerprints,
        "passed": passed,
        "predictions_match": passed,
        "span_predictions_match": spans_match,
        "rank_predictions_match": rank_match,
        "rank_score_absolute_tolerance": tolerance,
        "remote_measurements": _measurements(torch, device),
    }
    if teacher_match is not None:
        report["teacher_predictions_match"] = teacher_match
    _save_json(output_directory / "reload.json", report)
    if not passed:
        raise RuntimeError("Reloaded weights changed validation predictions")
    return report


def _validate_training(training):
    if type(training.get("structured_objectives", False)) is not bool:
        raise ValueError("Invalid structured_objectives setting")
    for key in ("seed", "epochs", "max_steps", "batch_size"):
        value = training.get(key)
        if type(value) is not int or value < (0 if key == "seed" else 1):
            raise ValueError(f"Invalid training {key}")
    rate = training.get("learning_rate")
    if type(rate) not in (int, float) or not math.isfinite(rate) or rate <= 0:
        raise ValueError("Invalid training learning_rate")


def _load_torch(training):
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("Specialist model stages require CUDA in the RunPod pod")
    # This is a new process, even if a separate Pod preflight used CUDA.
    # reset_peak_memory_stats accesses the allocator without initializing it.
    torch.cuda.init()
    torch.manual_seed(training["seed"])
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    device = torch.device("cuda:0")
    torch.cuda.reset_peak_memory_stats(device)
    return torch, device


def _load_cpu_torch(training):
    import torch

    if torch.cuda.is_available() or torch.cuda.device_count():
        raise RuntimeError("CPU training requires a CPU-only Runpod Pod")
    torch.manual_seed(training["seed"])
    torch.set_num_threads(2)
    return torch, torch.device("cpu")


def run_stage(stage, config_path, data_directory, output_directory):
    data_directory = Path(data_directory).resolve()
    output_directory = Path(output_directory).resolve()
    require_remote(PROJECT_ROOT, data_directory, output_directory, child=True)
    if stage not in STAGES:
        raise ValueError(f"Unknown specialist stage: {stage}")
    if os.environ.get("PYTHONDONTWRITEBYTECODE") != "1" or not sys.dont_write_bytecode:
        raise ValueError("Start the specialist child with bytecode writes disabled")
    if output_directory.is_relative_to(PROJECT_ROOT):
        raise ValueError("Specialist output must stay outside the verified runtime source")
    config, files, fingerprints = _load_inputs(PROJECT_ROOT, Path(config_path).resolve(), data_directory)
    execution_location = config.get("model_execution_location")
    if (
        config.get("schema_version") != 1
        or execution_location not in ("remote_gpu_pod_only", "remote_runpod_cpu_only")
        or config.get("generative_model") is not False
        or config.get("pretrained_language_backbone") is not None
    ):
        raise ValueError("Require the version 1 remote specialist configuration")
    parameter_estimate(config)
    _validate_training(config["training"])
    validation = _read_split(data_directory, "validation", config, files)
    train = _read_split(data_directory, "train", config, files) if stage == "train" else None
    output_directory.mkdir(parents=True, exist_ok=True)
    if stage == "baseline":
        report = _run_baseline(validation)
        report["input_fingerprints"] = fingerprints
        _save_json(output_directory / "baseline.json", report)
        return report

    if execution_location == "remote_runpod_cpu_only":
        torch, device = _load_cpu_torch(config["training"])
    else:
        torch, device = _load_torch(config["training"])
    models = build_models(torch, config)
    for model in models.values():
        model.to(device)
    if stage == "train":
        pool = None
        if "self_training" in config:
            from .self_learning import load_pool

            if not config["training"].get("structured_objectives") or execution_location != "remote_runpod_cpu_only":
                raise ValueError("Self-training requires the structured CPU training runtime")
            pool = load_pool(PROJECT_ROOT, config["self_training"], train, validation)
        return _train_and_export(torch, models, config, train, validation, output_directory, fingerprints, device, pool)
    return _reload(torch, models, config, output_directory, validation, fingerprints, device)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=STAGES, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--data-directory", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args(argv)
    run_stage(args.stage, args.config, args.data_directory, args.output_directory)


if __name__ == "__main__":
    main()
