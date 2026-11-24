"""Compare the frozen specialist research run and first checkpoint on hosted Colab."""

import argparse
from collections import Counter
import json
from pathlib import Path
import resource
import time

from pilot.field_rules import extract_review_fields

from .artifacts import sha256_file, verify_manifest
from .evaluate import (
    ARCHIVE_BYTES, ARCHIVE_SHA256, TRAIN_MANIFEST_SHA256,
    load_verified_checkpoint, require_hosted_colab, restore_models,
)
from .features import decode_spans, encode_span, tokenize_with_offsets
from .runtime import _batch_span, _evaluate, _read_split, _run_baseline, _span_report


RESEARCH_TRAIN_SHA256 = '3a44bf598e8190bb4e81f972f2891c5fd688d1334b60196f9e72258ca6329dc3'
RESEARCH_TEST_SHA256 = 'bf3e352334d01f05461a39931fce2ee932f7924505ae9a866fd64d38173f949f'
FIELDBENCH_MANIFEST_SHA256 = '3f6219d3a7aee0ef6b665cbd61eb14a72fec2897ea8053ccfa8a4e4c6c7e1437'
POLICY_LABEL = 'POLICY_ID'


def read_holdouts(holdout, fieldbench):
    if sha256_file(holdout / 'manifest.json') != RESEARCH_TEST_SHA256:
        raise ValueError('Research test manifest differs from the frozen copy.')
    test = json.loads((holdout / 'manifest.json').read_text())
    if (test.get('split') != 'test' or test.get('synthetic_only') is not True
            or test.get('training_manifest_sha256') != RESEARCH_TRAIN_SHA256):
        raise ValueError('Research test split does not match the prepared experiment.')
    if sha256_file(fieldbench / 'manifest.json') != FIELDBENCH_MANIFEST_SHA256:
        raise ValueError('FieldBench manifest differs from the frozen copy.')
    verify_manifest(fieldbench)
    rows = [json.loads(line) for line in (fieldbench / 'value-only-holdout.jsonl').read_text().splitlines()]
    if Counter(row['category'] for row in rows) != {'insurance_claims': 140, 'insurance_policies': 80}:
        raise ValueError('Expected exactly the verified FieldBench claims and policies.')
    return test['files'], rows


def document_windows(text, config):
    """Keep original token boundaries and overlap windows by half their length."""
    tokens = tokenize_with_offsets(text)
    length = config['max_tokens']
    boundary = 0
    for stop, (token, _, _) in enumerate([*tokens, ('', 0, 0)]):
        if stop < len(tokens) and len(token) <= config['max_chars_per_token']:
            continue
        for start in range(boundary, stop, max(1, length // 2)):
            end = min(start + length, stop)
            yield text[tokens[start][1]:tokens[end - 1][2]]
            if end == stop:
                break
        boundary = stop + 1


def normalized(value):
    return value.strip().casefold()


def fieldbench_rule(row):
    document = {
        'id': row['doc_id'], 'filename': 'benchmark.md',
        'kind': 'policy' if row['category'] == 'insurance_policies' else 'claim_form',
        'pages': [{'page': 1, 'text': row['text']}],
    }
    value = extract_review_fields([document])['fields'][POLICY_LABEL]['value']
    return {normalized(value)} if value is not None else set(), 1


def fieldbench_network(torch, model, row, config, device):
    values = set()
    evaluated = 0
    for text in document_windows(row['text'], config):
        example = {'text': text, 'spans': []}
        encoded = encode_span(example, config)
        inputs, _ = _batch_span(torch, [(example, encoded)], device)
        logits = model(*inputs)
        if not torch.isfinite(logits).all().item():
            raise ValueError('FieldBench logits contain a non-finite value.')
        tags = logits.argmax(dim=-1)[0, :len(encoded['offsets'])].tolist()
        for span in decode_spans(text, encoded['offsets'], tags):
            if span['label'] == POLICY_LABEL:
                values.add(normalized(span['value']))
        evaluated += 1
    return values, evaluated


def score_fieldbench(rows, predict):
    counts = Counter(documents=len(rows), correct=0, resolved=0, ambiguous=0, documents_with_windows=0)
    for row in rows:
        expected = normalized(row['expected']['policy_number'])
        values, evaluated = predict(row)
        counts['documents_with_windows'] += evaluated > 0
        counts['ambiguous'] += len(values) > 1
        counts['resolved'] += len(values) == 1
        counts['correct'] += values == {expected}
    return {**counts, 'value_accuracy': counts['correct'] / len(rows)}


def summarize(scores, data):
    per_family = {}
    predictions = scores['span']['predictions']
    for family in sorted({row['family'] for row, _ in data['span']}):
        selected = [(example, pred['tag_ids']) for example, pred in zip(data['span'], predictions, strict=True)
                    if example[0]['family'] == family]
        rows, tags = zip(*selected, strict=True)
        per_family[family] = _span_report(rows, tags)['metrics']['exact_span']
    return {task: scores[task]['metrics'] for task in ('span', 'rank')} | {'span_by_family': per_family}


def compare(first, candidate, candidate_sha256, holdout, fieldbench):
    require_hosted_colab()
    started = time.monotonic()
    files, fieldbench_rows = read_holdouts(holdout, fieldbench)
    first_config, first_weights = load_verified_checkpoint(first, ARCHIVE_SHA256, TRAIN_MANIFEST_SHA256, ARCHIVE_BYTES)
    config, candidate_weights = load_verified_checkpoint(candidate, candidate_sha256, RESEARCH_TRAIN_SHA256)
    if first_config != config:
        raise ValueError('The two checkpoints must use the same frozen configuration.')
    data = _read_split(holdout, 'test', config, files)
    reports = {'rules': summarize(_run_baseline(data), data)}
    reports['rules']['fieldbench_policy_id'] = score_fieldbench(fieldbench_rows, fieldbench_rule)

    import torch

    torch.set_num_threads(1)
    device = torch.device('cpu')
    for name, weights in (('first_checkpoint', first_weights), ('candidate', candidate_weights)):
        models = restore_models(torch, config, weights)
        reports[name] = summarize(_evaluate(torch, models, data, config['training']['batch_size'], device), data)
        with torch.inference_mode():
            reports[name]['fieldbench_policy_id'] = score_fieldbench(
                fieldbench_rows, lambda row: fieldbench_network(torch, models['span'], row, config['span'], device),
            )
        del models
    return {
        'dataset': 'specialists-research-v1',
        'first_checkpoint_sha256': ARCHIVE_SHA256,
        'candidate_sha256': candidate_sha256,
        'test_manifest_sha256': RESEARCH_TEST_SHA256,
        'fieldbench_manifest_sha256': FIELDBENCH_MANIFEST_SHA256,
        'reports': reports,
        'runtime': {'device': 'cpu', 'torch': torch.__version__,
                    'elapsed_seconds': round(time.monotonic() - started, 3),
                    'process_peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024},
        'fieldbench_method': 'Policy number only. Half-overlapping windows stop at oversized tokens. '
                             'Conflicting visible candidates abstain. Missing and ambiguous predictions count as misses.',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--first', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--candidate-sha256', required=True, help='Use the verified candidate archive receipt.')
    parser.add_argument('--holdout', type=Path, required=True)
    parser.add_argument('--fieldbench', type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.first, args.candidate, args.candidate_sha256, args.holdout, args.fieldbench)
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
