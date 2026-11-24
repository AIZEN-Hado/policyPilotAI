"""Score the research fine-tune and its reference with the same hosted parser."""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path

from .artifacts import sha256_file, verify_manifest
from .diagnose_quality_validation import _score
from .evaluate import load_verified_checkpoint, restore_models
from .evaluate_public_policy_run import score_models
from .evaluate_quality_run import _read_holdout, _require_host
from .features import tokenize_with_offsets
from .runtime import _batch_span, _encode_span
from .structured import value_candidates


TARGET = 0.95


def _windows(text, config):
    tokens = tokenize_with_offsets(text)
    limit = config["max_tokens"]
    begin = 0
    for stop, (token, _, _) in enumerate([*tokens, ("", 0, 0)]):
        if stop < len(tokens) and len(token) <= config["max_chars_per_token"]:
            continue
        for start in range(begin, stop, max(1, limit // 2)):
            end = min(start + limit, stop)
            yield text[tokens[start][1]:tokens[end - 1][2]]
            if end == stop:
                break
        begin = stop + 1


def _policy_values(torch, model, documents, config):
    scores = defaultdict(dict)
    windows = Counter()
    batch = []
    device = torch.device("cpu")

    def flush():
        if not batch:
            return
        args, _ = _batch_span(torch, batch, device)
        raw = model(*args)
        if not torch.isfinite(raw).all().item():
            raise ValueError("Policy-number scorer returned non-finite model output")
        for (row, encoded), logits in zip(batch, raw.tolist(), strict=True):
            offsets = encoded["offsets"]
            for left, right in value_candidates(row["text"], offsets)["POLICY_ID"]:
                value = row["text"][offsets[left][0]:offsets[right][1]].strip().casefold()
                score = _score(logits, "POLICY_ID", left, right)
                by_value = scores[row["id"]]
                by_value[value] = max(score, by_value.get(value, float("-inf")))
        batch.clear()

    model.eval()
    with torch.inference_mode():
        for doc in documents:
            kind = "policy" if doc["category"] == "insurance_policies" else "claim_form"
            for text in _windows(doc["text"], config["span"]):
                row = {"id": doc["doc_id"], "text": text, "kind": kind, "spans": []}
                batch.append((row, _encode_span(row, config["span"])))
                windows[row["id"]] += 1
                if len(batch) == config["training"]["batch_size"]:
                    flush()
        flush()

    groups = defaultdict(Counter)
    for doc in documents:
        key = doc["doc_id"]
        expected = doc["expected"]["policy_number"].strip().casefold()
        candidates = scores[key]
        maximum = max(candidates.values(), default=0.0)
        best = [value for value, score in candidates.items() if score > 0 and maximum - score <= 1e-6]
        for label in ("overall", doc["category"]):
            group = groups[label]
            group["documents"] += 1
            group["correct"] += best == [expected]
            group["resolved"] += len(best) == 1
            group["ambiguous"] += len(best) > 1
            group["gold_value_in_candidate_set"] += expected in candidates
            group["windows"] += windows[key]
    return {name: {**counts, "value_accuracy": counts["correct"] / counts["documents"]}
            for name, counts in sorted(groups.items())}


def evaluate(candidate, reference, evaluation, holdout_sha256, regression_sha256, fieldbench_sha256):
    _require_host("runpod-cpu", [candidate[0], reference[0]], evaluation)
    rows, sources = _read_holdout(evaluation / "holdout", holdout_sha256)
    regression, regression_sources = _read_holdout(evaluation / "regression", regression_sha256)
    fieldbench = evaluation / "fieldbench"
    if sha256_file(fieldbench / "manifest.json") != fieldbench_sha256:
        raise ValueError("FieldBench manifest does not match the benchmark receipt")
    verify_manifest(fieldbench)
    documents = [json.loads(line) for line in (fieldbench / "value-only-holdout.jsonl").read_bytes().splitlines()]
    if Counter(doc["category"] for doc in documents) != {"insurance_claims": 140, "insurance_policies": 80}:
        raise ValueError("Use the complete verified FieldBench benchmark")

    import torch

    if torch.cuda.is_available() or torch.cuda.device_count():
        raise RuntimeError("Use a hosted CPU Pod for evaluation")
    torch.set_num_threads(2)
    results = {}
    for name, (path, digest, dataset, config_sha) in (("fine_tuned", candidate), ("reference", reference)):
        config, weights = load_verified_checkpoint(path, digest, dataset, config_sha256=config_sha)
        models = restore_models(torch, config, weights)
        results[name] = {"checkpoint_sha256": digest,
                         "research": score_models(torch, rows, sources, config, models, target=TARGET),
                         "fieldbench": _policy_values(torch, models["span"], documents, config),
                         "prior_synthetic": score_models(torch, regression, regression_sources, config, models, target=TARGET)}
    return {"scope": "synthetic_research_and_prior_benchmark", "target": TARGET,
            "recorded_at": datetime.now(timezone.utc).isoformat(), "reports": results,
            "holdout_manifest_sha256": holdout_sha256, "regression_manifest_sha256": regression_sha256,
            "fieldbench_manifest_sha256": fieldbench_sha256, "production_accuracy_established": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation", required=True, type=Path)
    for name in ("candidate", "reference"):
        parser.add_argument(f"--{name}", nargs=4, required=True, metavar=("ARCHIVE", "SHA", "DATA_SHA", "CONFIG_SHA"))
    for name in ("holdout-sha256", "regression-sha256", "fieldbench-sha256"):
        parser.add_argument(f"--{name}", required=True)
    print(json.dumps(evaluate(**vars(parser.parse_args())), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
