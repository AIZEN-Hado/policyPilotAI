"""Prepare and verify a small source/data bundle locally. No model/library downloads."""
import argparse
import json
from pathlib import Path

from .artifacts import pack, verify_archive
from .common import CORPUS, EVALUATION, ROOT, digest, records, save_json
from .data import build
from .score import evaluate

RUNTIME_FILES = ('__init__.py', 'common.py', 'artifacts.py', 'run.py', 'runtime.py',
                 'config.json', 'requirements.txt', 'requirements-cu128.txt', 'pod.sh', 'README.md')


def prepare(output):
    dataset = build()
    # Oracle targets exercise the checker only. They are never model predictions.
    checks = {}
    for split in ('validation', 'test'):
        prompts = CORPUS / 'validation-prompts.jsonl' if split == 'validation' else EVALUATION / 'test-prompts.jsonl'
        truth = records(EVALUATION / f'{split}-labels.jsonl')
        reference = [{'id': row['id'], 'synthetic': True, 'output': row['expected']} for row in truth]
        result = evaluate(records(prompts), truth, reference)
        if result['metrics']['passed'] != 1:
            raise ValueError('Generated references failed the offline checker')
        checks[split] = {'cases': result['cases_scored'], 'reference_checker_passed': True,
                         'model_was_run': False}
    files = {f'training/{name}': ROOT / 'training' / name for name in RUNTIME_FILES}
    files.update({f'pilot/{name}': ROOT / 'pilot' / name for name in ('__init__.py', 'core.py', 'review_prompt.py')})
    files.update({'data/synthetic/finetune-v1/' + path.name: path for path in CORPUS.iterdir() if path.is_file()})
    expected_data = {'train.jsonl', 'validation-prompts.jsonl', 'manifest.json'}
    if {path.name for path in CORPUS.iterdir() if path.is_file()} != expected_data:
        raise ValueError('Unexpected dataset files; do not bundle possible held-out labels')
    if output.exists():
        receipt = verify_archive(output)
        if receipt['files'] != {name: digest(path) for name, path in files.items()}:
            raise ValueError('Prepared bundle is from different source; choose a new --output name and preserve the old bundle')
    else:
        receipt = pack(files, output)
    report = {'kind': 'offline_preparation_not_training', 'synthetic_only': True,
              'dataset_counts': dataset['counts'], 'reference_checker': checks,
              'held_out_labels_bundled': False, 'test_prompts_bundled': False,
              'generator_and_scorer_bundled': False, 'model_downloaded': False,
              'gpu_used': False, 'provider_resources_changed': False,
              'trained_model_verified': False, 'model_ram_verified': False,
              'bundle_sha256': receipt['sha256'], 'bundle_files': len(receipt['files']),
              'limitations': dataset['limitations']}
    save_json(output.with_name(output.name + '.preparation.json'), report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/policypilot-training-v3.tar.gz')
    args = parser.parse_args()
    print(json.dumps(prepare(args.output), indent=2))
