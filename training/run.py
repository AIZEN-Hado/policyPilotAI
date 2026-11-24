"""Plan by default; explicitly execute one bounded experiment on an existing GPU Pod.

This controls child processes only. It does not provision, stop or terminate a Pod.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import math
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time
import uuid

from .artifacts import MANIFEST, pack, verify
from .common import CORPUS, ROOT, digest, read_json, save_json


def seconds_allowed(seconds, rate, allowance):
    try:
        rate, allowance = Decimal(rate), Decimal(allowance)
        if not rate.is_finite() or not allowance.is_finite() or rate <= 0 or not 0 < allowance <= Decimal('2.99'):
            raise ValueError('Invalid rate/remaining compute allowance')
        if not 30 <= seconds <= 900:
            raise ValueError('Execution duration must be 30-900 seconds')
        permitted = min(seconds, math.floor(allowance * 3600 / rate))
        if permitted < 30:
            raise ValueError('Remaining allowance is too small for this run')
        return permitted
    except InvalidOperation:
        raise ValueError('Rate and allowance must be finite decimal numbers') from None


def peak_rss(pid):
    try:
        for line in Path(f'/proc/{pid}/status').read_text().splitlines():
            if line.startswith('VmHWM:'):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError):
        pass
    return 0


def terminate(process):
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        except ProcessLookupError:
            process.wait()


def monitor(command, log, deadline, ram_limit, environment):
    start = time.monotonic()
    peak = 0
    stopped = None
    with Path(log).open('wb') as stream:
        process = subprocess.Popen(command, env=environment, stdout=stream, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        try:
            while process.poll() is None:
                peak = max(peak, peak_rss(process.pid))
                if ram_limit is not None and peak >= ram_limit:
                    stopped = 'model_process_ram_target_exceeded'
                    break
                if time.monotonic() >= deadline:
                    stopped = 'execution_deadline_reached'
                    break
                time.sleep(0.05)
        finally:
            terminate(process)
    # The child records its own Linux peak on normal/error exit. If killed before
    # that write, cumulative child accounting is a conservative fallback and may
    # overestimate a later phase's peak; it never turns an over-budget phase green.
    measurement = 'sampled VmHWM plus conservative cumulative child high-water mark'
    memory_receipt = Path(log).parent / 'model-memory.json'
    if memory_receipt.is_file():
        memory = read_json(memory_receipt)
        peak = max(peak, int(memory['process_peak_rss_bytes']))
        measurement = 'sampled VmHWM plus this model process Linux peak RSS receipt'
    else:
        peak = max(peak, resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss * 1024)
    if ram_limit is not None and peak >= ram_limit:
        stopped = 'model_process_ram_target_exceeded'
    return {'exit_code': process.returncode, 'peak_rss_bytes': peak,
            'measurement_scope': measurement,
            'wall_seconds': round(time.monotonic() - start, 3), 'stop_reason': stopped,
            'passed': process.returncode == 0 and stopped is None and peak > 0
                      and (ram_limit is None or peak < ram_limit)}


def child_environment(workspace):
    allowed = ('PATH', 'HOME', 'LANG', 'LC_ALL', 'LD_LIBRARY_PATH', 'CUDA_VISIBLE_DEVICES',
               'NVIDIA_VISIBLE_DEVICES', 'NVIDIA_DRIVER_CAPABILITIES', 'SSL_CERT_FILE',
               'SSL_CERT_DIR', 'CC', 'CXX', 'RUNPOD_POD_ID')
    return {**{key: os.environ[key] for key in allowed if key in os.environ},
            'PYTHONPATH': str(ROOT), 'PYTHONUNBUFFERED': '1',
            'HF_HOME': str(workspace / 'cache'), 'HF_HUB_DISABLE_IMPLICIT_TOKEN': '1',
            'HF_HUB_DISABLE_TELEMETRY': '1', 'DO_NOT_TRACK': '1',
            'TOKENIZERS_PARALLELISM': 'false', 'WANDB_DISABLED': 'true',
            'POLICYPILOT_BOUNDED_CHILD': '1'}


def corpus_verified():
    manifest = read_json(CORPUS / 'manifest.json')
    if manifest.get('synthetic_only') is not True or set(manifest['files']) != {'train.jsonl', 'validation-prompts.jsonl'}:
        raise ValueError('Expected the prepared synthetic corpus manifest')
    for name, expected in manifest['files'].items():
        if digest(CORPUS / name) != expected:
            raise ValueError('Prepared dataset hash mismatch')
    return digest(CORPUS / 'manifest.json')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('preflight', 'baseline', 'train', 'predict'), required=True)
    parser.add_argument('--workspace', type=Path, required=True, help='Existing network volume subdirectory under /workspace')
    parser.add_argument('--execute', action='store_true', help='Run GPU code; otherwise print the plan only')
    parser.add_argument('--max-seconds', type=int, default=300)
    parser.add_argument('--gpu-hourly-usd', required=True, help='Fresh provider quote, not an old catalog guess')
    parser.add_argument('--compute-budget-usd', required=True, help='Available amount after prior spend/holds and overhead; does not modify provider/DB budgets')
    parser.add_argument('--baseline-report', type=Path, help='Successful bounded baseline receipt required before training')
    parser.add_argument('--adapter', type=Path, help='Frozen adapter for prediction')
    parser.add_argument('--prompts', type=Path, default=CORPUS / 'validation-prompts.jsonl')
    parser.add_argument('--limit', type=int, default=9, help='First N cases; use --limit 0 for full selected split')
    args = parser.parse_args()
    seconds = seconds_allowed(args.max_seconds, args.gpu_hourly_usd, args.compute_budget_usd)
    if args.limit < 0:
        raise ValueError('Prediction case limit cannot be negative')
    config = read_json(ROOT / 'training/config.json')
    if config.get('model_execution_location') != 'remote_gpu_pod_only':
        raise ValueError('Model execution must remain restricted to the remote GPU Pod')
    ram_limit = config.get('model_process_ram_limit_bytes')
    if ram_limit is not None and (type(ram_limit) is not int or ram_limit <= 0):
        raise ValueError('Optional cloud RSS limit must be positive bytes or null')
    fingerprint = corpus_verified()
    report = {'mode': args.mode, 'model': config['model'], 'revision': config['revision'],
              'dataset_manifest_sha256': fingerprint, 'config_sha256': digest(ROOT / 'training/config.json'),
              'maximum_seconds': seconds, 'rss_limit_bytes': config['model_process_ram_limit_bytes'],
              'model_execution_location': config['model_execution_location'], 'local_model_execution_allowed': False,
              'gpu_hourly_usd': args.gpu_hourly_usd, 'caller_remaining_compute_allowance_usd': args.compute_budget_usd,
              'compute_only_estimate_usd': str(Decimal(args.gpu_hourly_usd) * seconds / 3600),
              'provider_resources_changed': False, 'provider_shutdown_verified': False,
              'billing_note': 'Process timeout only. Pod startup/idle, storage and tax are additional. This is not a provider-enforced dollar cap. Terminate the Pod separately.',
              'completed': False, 'model_quality_verified': False}
    if not args.execute:
        import json
        print(json.dumps({**report, 'plan_only': True, 'model_downloaded': False}, indent=2))
        return 0
    if sys.platform != 'linux':
        raise ValueError('GPU process measurement requires Linux')
    workspace = args.workspace.resolve()
    if (not os.environ.get('RUNPOD_POD_ID') or not workspace.is_relative_to(Path('/workspace'))
            or workspace == Path('/workspace') or not os.path.ismount('/workspace')):
        raise ValueError('Execute only on the existing Pod: require its provider Pod ID and a network volume mounted at /workspace')
    if args.mode == 'train':
        if args.baseline_report is None:
            raise ValueError('Run a bounded baseline and retain its receipt before training')
        baseline = read_json(args.baseline_report)
        if not (baseline.get('mode') == 'baseline' and baseline.get('completed') is True
                and baseline.get('revision') == config['revision']
                and baseline.get('dataset_manifest_sha256') == fingerprint
                and baseline.get('config_sha256') == report['config_sha256']):
            raise ValueError('Baseline receipt is missing, incomplete or uses different data/model/config')
        report['baseline_report_sha256'] = digest(args.baseline_report)
    if args.mode == 'predict':
        if args.adapter is None:
            raise ValueError('Prediction requires a frozen, hash-verified adapter')
        verify(args.adapter)
    workspace.mkdir(parents=True, exist_ok=True)
    run_dir = workspace / 'runs' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8])
    run_dir.mkdir(parents=True)
    destination = run_dir / 'run.json'
    save_json(destination, report)
    environment = child_environment(workspace)
    deadline = time.monotonic() + seconds
    command = [sys.executable, '-m', 'training.runtime', '--mode', args.mode,
               '--workspace', str(workspace), '--output', str(run_dir), '--prompts', str(args.prompts.resolve()),
               '--limit', str(args.limit)]
    if args.adapter:
        command += ['--adapter', str(args.adapter.resolve())]
    try:
        report['process'] = monitor(command, run_dir / 'model.log', deadline, report['rss_limit_bytes'], environment)
        if not report['process']['passed']:
            raise ValueError('Model process failed or exceeded its time/RAM target; inspect its local synthetic log. No automatic retry.')
        if args.mode == 'train':
            adapter = run_dir / 'adapter'
            verify(adapter)
            if time.monotonic() >= deadline:
                raise ValueError('No time remains for independent adapter reload; do not delete the Pod/artifacts')
            reload_dir = run_dir / 'independent-reload'
            reload_dir.mkdir()
            reload_command = [sys.executable, '-m', 'training.runtime', '--mode', 'reload',
                              '--workspace', str(workspace), '--output', str(reload_dir), '--adapter', str(adapter)]
            report['reload_process'] = monitor(reload_command, reload_dir / 'model.log', deadline,
                                                report['rss_limit_bytes'], environment)
            if not report['reload_process']['passed']:
                raise ValueError('Independent reload did not pass; retain artifacts and do not claim training verified')
            reload_receipt = read_json(reload_dir / 'reload.json')
            if not (reload_receipt.get('reload_and_generation_passed') is True
                    and reload_receipt.get('adapter_manifest_sha256') == digest(adapter / MANIFEST)):
                raise ValueError('Fresh-process reload receipt does not match adapter')
            verify(adapter)
            files = {'adapter/' + p.relative_to(adapter).as_posix(): p for p in adapter.rglob('*') if p.is_file()}
            files['reload.json'] = reload_dir / 'reload.json'
            receipt = pack(files, run_dir / 'verified-adapter.tar.gz')
            report['verified_adapter_archive_sha256'] = receipt['sha256']
            report['artifact_kind'] = 'adapter_only_requires_pinned_base_not_a_merged_model'
        report['completed'] = True
    finally:
        save_json(destination, report)
        print('Saved and read-back verified run receipt:', destination)
        print('The GPU Pod still needs provider-side termination. This script does not stop its billing.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError) as exc:
        raise SystemExit('CHECK: ' + str(exc)) from None
