"""Generate synthetic labels and a verified runtime source bundle; no model calls."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile

from .artifacts import package_directory, sha256_file, verify_archive, write_manifest
from .contracts import validate_corpus
from .data import generate_corpus
from .models import parameter_estimate

ROOT = Path(__file__).resolve().parents[1]
DATA_FILES = ('train-span.jsonl', 'train-rank.jsonl', 'validation-span.jsonl', 'validation-rank.jsonl')
RUNTIME_FILES = ('__init__.py', 'config.json', 'contracts.py', 'features.py', 'models.py',
                 'runtime.py', 'execution.py', 'run.py', 'artifacts.py', 'backup.py',
                 'README.md', 'requirements-cu128.txt')


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + '\n').encode()


def write_once(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_symlink() or path.read_bytes() != content:
            raise ValueError('Prepared file differs; preserve it and choose a new output/version')
    else:
        with path.open('xb') as stream:
            stream.write(content)


def atomic_receipt(path, value):
    if path.is_symlink():
        raise ValueError('Refuse a receipt symlink')
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(encoded(value))
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def prepare(root=ROOT, *, version='v1'):
    root = Path(root).resolve()
    if not version or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in version):
        raise ValueError('Use a simple artifact version')
    config = json.loads((root / 'specialists/config.json').read_text())
    if (config.get('model_execution_location') != 'remote_gpu_pod_only'
            or config.get('generative_model') is not False
            or config.get('pretrained_language_backbone') is not None):
        raise ValueError('Require remote specialist task networks without a language-model backbone')
    estimate = parameter_estimate(config)
    corpus = generate_corpus(seed=config['training']['seed'])
    validate_corpus(corpus)
    data = root / 'data/synthetic/specialists-v1'
    evaluation = root / 'evaluation/specialists-v1'
    files, split_counts = {}, {}
    for split in ('train', 'validation', 'test'):
        split_counts[split] = {}
        for task in ('span', 'rank'):
            rows = corpus[split][task]
            content = b''.join((json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n').encode() for row in rows)
            name = f'{split}-{task}.jsonl'
            target = (evaluation if split == 'test' else data) / name
            write_once(target, content)
            split_counts[split][task] = len(rows)
            if split != 'test':
                files[name] = {'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content), 'rows': len(rows)}
    limitations = [
        'Original English synthetic text only; no PDF, layout-coordinate, OCR or real-world accuracy benchmark.',
        'Wording/layout families and cases are split, but synthetic generation semantics are shared.',
        'Oracle/source-label consistency is not trained model accuracy.',
        'Final test labels and their reconstructing generator are excluded from the training runtime archive.',
    ]
    manifest = {'schema_version': 1, 'synthetic_only': True, 'seed': config['training']['seed'],
                'files': files, 'splits': {k: split_counts[k] for k in ('train', 'validation')},
                'limitations': limitations}
    write_once(data / 'manifest.json', encoded(manifest))
    write_once(evaluation / 'manifest.json', encoded({
        'schema_version': 1, 'synthetic_only': True, 'split': 'test', 'counts': split_counts['test'],
        'files': {p.name: {'sha256': sha256_file(p), 'bytes': p.stat().st_size}
                  for p in (evaluation / 'test-span.jsonl', evaluation / 'test-rank.jsonl')},
        'limitations': limitations}))
    archive = root / f'artifacts/policypilot-specialists-{version}-runtime.tar.gz'
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='specialist-source-') as temp:
        staging = Path(temp)
        for name in RUNTIME_FILES:
            relative = Path('specialists') / name
            write_once(staging / relative, (root / relative).read_bytes())
        for name in DATA_FILES + ('manifest.json',):
            relative = Path('data/synthetic/specialists-v1') / name
            write_once(staging / relative, (data / name).read_bytes())
        write_manifest(staging, metadata={'kind': 'runtime_source_and_synthetic_train_validation',
            'no_language_model': True, 'weights_included': False, 'model_quality_verified': False},
            max_bytes=16 * 1024 * 1024)
        if archive.exists():
            receipt = verify_archive(archive, max_bytes=16 * 1024 * 1024)
            current = json.loads((staging / 'manifest.json').read_text())
            if receipt['manifest'] != current:
                raise ValueError('Existing runtime artifact uses different source/data; choose a new --version')
        else:
            receipt = package_directory(staging, archive, max_bytes=16 * 1024 * 1024)
    verified = verify_archive(archive, max_bytes=16 * 1024 * 1024)
    report = {'recorded_at': datetime.now(timezone.utc).isoformat(), 'source_preparation_verified': True,
              'counts': split_counts, 'parameter_estimate': estimate,
              'artifact': archive.name, 'sha256': verified['sha256'], 'archive_bytes': verified['bytes'],
              'member_hashes_verified': True, 'language_model_used': False, 'trained_weights_created': False,
              'model_execution_performed': False, 'model_quality_verified': False,
              'remote_resources_changed': False, 'render_fit_verified': False,
              'limitations': limitations}
    atomic_receipt(archive.with_suffix(archive.suffix + '.preparation.json'), report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--version', default='v1')
    args = parser.parse_args()
    print(json.dumps(prepare(args.root, version=args.version), indent=2))


if __name__ == '__main__':
    main()
