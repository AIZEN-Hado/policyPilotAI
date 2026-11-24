"""Plan-only by default. Execute bounded specialist stages on an existing remote Pod."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import threading
import uuid

from .artifacts import package_directory, sha256_file, verify_archive, verify_manifest, write_manifest
from .contracts import validate_row
from .execution import require_remote
from .models import parameter_estimate

ROOT = Path(__file__).resolve().parents[1]
DATA_FILES = {'train-span.jsonl', 'train-rank.jsonl', 'validation-span.jsonl', 'validation-rank.jsonl'}
STOP_GRACE_SECONDS = 3


def allowed_seconds(seconds, rate, remaining):
    if type(seconds) is not int or not 30 <= seconds <= 900:
        raise ValueError('Choose 30-900 seconds')
    try:
        rate, remaining = Decimal(str(rate)), Decimal(str(remaining))
    except InvalidOperation:
        raise ValueError('Use finite decimal rate and remaining allowance') from None
    if (not rate.is_finite() or not remaining.is_finite() or not 0 < rate < 1
            or not 0 < remaining <= Decimal('2.99')):
        raise ValueError('Require a fresh GPU rate strictly below $1/hour and remaining allowance within $2.99')
    duration = min(seconds, math.floor(remaining * 3600 / rate) - STOP_GRACE_SECONDS)
    if duration < 30:
        raise ValueError('Insufficient compute-only allowance for a 30-second stage')
    return duration


def verify_data(directory):
    directory = Path(directory).resolve()
    manifest_path = directory / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('synthetic_only') is not True or set(manifest['files']) != DATA_FILES:
        raise ValueError('Require the prepared synthetic train/validation manifest')
    if any(p.is_symlink() for p in directory.iterdir()) or {p.name for p in directory.iterdir()} != DATA_FILES | {'manifest.json'}:
        raise ValueError('Training data directory has unexpected files or links')
    families, cases, ids = {'train': set(), 'validation': set()}, {'train': set(), 'validation': set()}, set()
    for name, expected in manifest['files'].items():
        path = directory / name
        if sha256_file(path) != expected['sha256'] or path.stat().st_size != expected['bytes']:
            raise ValueError('Prepared synthetic data hash or size changed')
        count = 0
        split, task = name.removesuffix('.jsonl').split('-', 1)
        for line in path.read_text().splitlines():
            row = json.loads(line)
            validate_row(row)
            if row['task'] != task or row['id'] in ids:
                raise ValueError('Dataset task mismatch or duplicate example')
            ids.add(row['id'])
            families[split].add(row['family'])
            cases[split].add(row['case_id'])
            count += 1
        if count != expected['rows']:
            raise ValueError('Prepared dataset row count changed')
    if families['train'] & families['validation'] or cases['train'] & cases['validation']:
        raise ValueError('Synthetic train and validation cases/families overlap')
    return sha256_file(manifest_path)


def child_environment(project_root):
    allowed = ('PATH', 'HOME', 'LANG', 'LC_ALL', 'LD_LIBRARY_PATH', 'CUDA_VISIBLE_DEVICES',
               'NVIDIA_VISIBLE_DEVICES', 'NVIDIA_DRIVER_CAPABILITIES', 'RUNPOD_POD_ID')
    return {**{k: os.environ[k] for k in allowed if k in os.environ},
            'PYTHONPATH': str(project_root), 'PYTHONUNBUFFERED': '1', 'PYTHONDONTWRITEBYTECODE': '1',
            'POLICYPILOT_SPECIALIST_CHILD': '1', 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'}


def stop_process(process):
    # Clear the entire owned process group, including descendants whose leader
    # exited. Always follow TERM with KILL for an ignoring descendant.
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=STOP_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        pass
    except ProcessLookupError:
        pass
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def monitor(command, log, deadline, environment):
    start, peak, stopped = time.monotonic(), 0, False
    with Path(log).open('wb') as stream:
        process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT,
                                   env=environment, start_new_session=True)
        handlers = {}

        def interrupted(signum, frame):
            raise InterruptedError('Launcher interrupted; stopping its owned child group')

        try:
            if threading.current_thread() is threading.main_thread():
                for signum in (signal.SIGTERM, signal.SIGHUP):
                    handlers[signum] = signal.signal(signum, interrupted)
            while process.poll() is None:
                try:
                    for line in Path(f'/proc/{process.pid}/status').read_text().splitlines():
                        if line.startswith('VmHWM:'):
                            peak = max(peak, int(line.split()[1]) * 1024)
                except (OSError, ValueError):
                    pass
                if time.monotonic() >= deadline:
                    stopped = True
                    break
                time.sleep(.05)
        finally:
            try:
                stop_process(process)
            finally:
                for signum, handler in handlers.items():
                    signal.signal(signum, handler)
    return {'exit_code': process.returncode, 'deadline_reached': stopped,
            'wall_seconds': round(time.monotonic() - start, 3),
            'sampled_peak_rss_bytes': peak, 'rss_scope': 'child VmHWM samples; short exits may not be sampled',
            'passed': process.returncode == 0 and not stopped}


def execute(args, config, fingerprint, duration, *, runtime_module='specialists.runtime'):
    project, data, output_root = require_remote(ROOT, args.data_directory, args.output_directory)
    if args.config.resolve() != project / 'specialists/config.json' or data != project / 'data/synthetic/specialists-v1':
        raise ValueError('Execute only the pinned runtime bundle configuration and data paths')
    pinned = verify_manifest(project, max_bytes=16 * 1024 * 1024)
    expected_source = {item['path']: item['sha256'] for item in pinned['files']}
    if (expected_source.get('specialists/config.json') != sha256_file(args.config)
            or expected_source.get('data/synthetic/specialists-v1/manifest.json') != fingerprint):
        raise ValueError('Configuration/data identity differs from the verified runtime bundle')
    expected_inputs = {'config_sha256': sha256_file(args.config),
                       'dataset_manifest_sha256': fingerprint,
                       'files': {name: sha256_file(data / name) for name in sorted(DATA_FILES)}}
    config_bytes = json.dumps(config, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    # Every run is retained separately. No resource create/start/stop API is used.
    output_root.mkdir(parents=True, exist_ok=True)
    directory = output_root / ('run-' + uuid.uuid4().hex)
    directory.mkdir()
    deadline = time.monotonic() + duration
    stages = ('baseline',) if args.stage == 'baseline' else ('baseline', 'train', 'reload')
    receipt = {'schema_version': 1, 'stage': args.stage, 'started_at': datetime.now(timezone.utc).isoformat(),
               'config_sha256': sha256_file(args.config), 'config_canonical_sha256': hashlib.sha256(config_bytes).hexdigest(),
               'dataset_manifest_sha256': fingerprint,
               'maximum_seconds': duration, 'gpu_hourly_usd': args.hourly_rate_usd,
               'caller_remaining_compute_usd': args.remaining_compute_usd,
               'compute_with_child_stop_grace_estimate_usd': str(Decimal(args.hourly_rate_usd) * (duration + STOP_GRACE_SECONDS) / 3600),
               'child_stop_grace_seconds': STOP_GRACE_SECONDS,
               'provider_resources_changed': False, 'provider_shutdown_verified': False,
               'stages_completed': False, 'model_quality_verified': False, 'stages': {}}
    receipt_path = directory / 'run.json'
    completion_path = output_root / (directory.name + '.receipt.json')
    completion = {**receipt, 'completed': False, 'archive_verified': False}
    try:
        for stage in stages:
            if time.monotonic() >= deadline:
                raise ValueError('Run deadline exhausted before next stage')
            # Detect changes between stages; each child also verifies the bytes
            # it consumes against this exact source/data identity.
            verify_manifest(project, max_bytes=16 * 1024 * 1024)
            environment = child_environment(project)
            environment['POLICYPILOT_SPECIALIST_CONFIG_SHA256'] = expected_inputs['config_sha256']
            environment['POLICYPILOT_SPECIALIST_DATA_MANIFEST_SHA256'] = fingerprint
            command = [sys.executable, '-B', '-m', runtime_module, '--stage', stage,
                       '--config', str(args.config.resolve()), '--data-directory', str(data),
                       '--output-directory', str(directory)]
            receipt['stages'][stage] = monitor(command, directory / (stage + '.log'), deadline, environment)
            receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
            if not receipt['stages'][stage]['passed']:
                raise ValueError('Remote stage failed or timed out; no automatic retry')
            stage_report = {'baseline': 'baseline.json', 'train': 'metadata.json', 'reload': 'reload.json'}[stage]
            actual = json.loads((directory / stage_report).read_text())
            if actual.get('input_fingerprints') != expected_inputs:
                raise ValueError('A child consumed different configuration or data than the launcher verified')
        if args.stage == 'train':
            reload = json.loads((directory / 'reload.json').read_text())
            if reload.get('passed') is not True or reload.get('predictions_match') is not True:
                raise ValueError('Independent checkpoint reload did not verify predictions')
            if sum((directory / name).stat().st_size for name in ('span.pt', 'rank.pt')) > config['max_weight_bytes']:
                raise ValueError('Trained weight files exceed the configured byte target')
        receipt['stages_completed'] = True
        receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
        write_manifest(directory, metadata={'kind': 'remote_specialist_run', 'trained': args.stage == 'train',
                       'model_quality_verified': False, 'dataset_manifest_sha256': fingerprint})
        verify_manifest(directory)
        archive = directory.with_suffix('.tar.gz')
        package_directory(directory, archive)
        artifact = verify_archive(archive)
        completion = {**receipt, 'completed': True, 'archive_verified': True,
                      'artifact': archive.name, 'artifact_sha256': artifact['sha256']}
    except BaseException as exc:
        completion = {**receipt, 'completed': False, 'archive_verified': False,
                      'failure_type': type(exc).__name__}
        if not (directory / 'manifest.json').exists():
            receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
        raise
    finally:
        completion_path.write_text(json.dumps(completion, indent=2) + '\n')
    print(json.dumps({'run_directory': str(directory), 'completed': True,
                      'verified_artifact_sha256': artifact['sha256'],
                      'provider_shutdown_verified': False, 'held_out_test_quality_verified': False}, indent=2))
    print('Stop/terminate dedicated training compute separately after verified remote backup; this launcher only stops child processes.')


def main(argv=None, *, runtime_module='specialists.runtime'):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=('baseline', 'train'), default='train')
    parser.add_argument('--config', type=Path, default=ROOT / 'specialists/config.json')
    parser.add_argument('--data-directory', type=Path, default=ROOT / 'data/synthetic/specialists-v1')
    parser.add_argument('--output-directory', type=Path, default=Path('/workspace/specialist-runs'))
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--max-seconds', type=int, default=300)
    parser.add_argument('--hourly-rate-usd')
    parser.add_argument('--remaining-compute-usd')
    args = parser.parse_args(argv)
    if args.execute:
        # Reject local execution before reading data or importing a neural runtime.
        require_remote(ROOT, args.data_directory, args.output_directory)
        if not sys.dont_write_bytecode:
            raise ValueError('Use python -B so the frozen runtime source remains unchanged')
    config = json.loads(args.config.read_text())
    if (config.get('model_execution_location') not in ('remote_gpu_pod_only', 'remote_runpod_cpu_only')
            or config.get('generative_model') is not False
            or config.get('pretrained_language_backbone') is not None):
        raise ValueError('Require remote task networks without a language-model backbone')
    estimate = parameter_estimate(config)
    fingerprint = verify_data(args.data_directory)
    duration = None
    if args.execute or args.hourly_rate_usd is not None or args.remaining_compute_usd is not None:
        duration = allowed_seconds(args.max_seconds, args.hourly_rate_usd, args.remaining_compute_usd)
    if not args.execute:
        print(json.dumps({'plan_only': True, 'stage': args.stage, 'architecture': estimate,
            'language_model_used': False, 'model_execution_performed': False,
            'dataset_manifest_sha256': fingerprint, 'maximum_seconds_if_quoted': duration,
            'render_fit_verified': False, 'provider_resources_changed': False,
            'billing_note': 'Fresh quote/remaining allowance required for execute. Startup, idle, storage/tax and post-exit Pod time are additional; this is not a provider dollar cap.'}, indent=2))
        return 0
    execute(args, config, fingerprint, duration, runtime_module=runtime_module)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, KeyError, RuntimeError):
        raise SystemExit('CHECK: Specialist preparation/execution failed; retain receipts. No automatic retry or provider shutdown is claimed.') from None
