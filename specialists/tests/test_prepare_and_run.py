"""Local source preparation checks. No neural runtime is imported or executed."""
import argparse
import builtins
from contextlib import redirect_stdout
from decimal import Decimal
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from specialists import prepare, run
from specialists.artifacts import verify_archive
from specialists.execution import require_remote


class BudgetAndGuardTests(unittest.TestCase):
    def test_finite_rate_ceiling_and_duration(self):
        self.assertEqual(run.allowed_seconds(300, '.75', '.1'), 300)
        self.assertEqual(run.allowed_seconds(900, '.75', '.1'), 477)
        for rate, remaining in [('1', '.5'), ('0', '.5'), ('NaN', '1'), ('.75', 'Infinity'),
                                ('.75', '3'), ('.75', '0'), ('.75', '.000001')]:
            with self.subTest(rate=rate, remaining=remaining), self.assertRaises(ValueError):
                run.allowed_seconds(300, rate, remaining)

    def test_child_environment_excludes_credentials(self):
        with patch.dict(os.environ, {'RUNPOD_API_KEY': 'private', 'RUNPOD_POD_ID': 'pod-fixture',
                                     'AWS_SECRET_ACCESS_KEY': 'private', 'DATABASE_URL': 'private',
                                     'GH_TOKEN': 'private', 'HF_TOKEN': 'private'}):
            env = run.child_environment(Path('/workspace/project'))
        self.assertEqual(env['RUNPOD_POD_ID'], 'pod-fixture')
        for key in ('RUNPOD_API_KEY', 'AWS_SECRET_ACCESS_KEY', 'DATABASE_URL', 'GH_TOKEN', 'HF_TOKEN'):
            self.assertNotIn(key, env)

    def test_local_execute_rejected_before_data_or_model_import(self):
        real_import = builtins.__import__

        def protected(name, *args, **kwargs):
            if name.split('.')[0] in {'torch', 'transformers', 'onnxruntime'}:
                raise AssertionError('A neural runtime must not import on this machine')
            return real_import(name, *args, **kwargs)

        with patch('builtins.__import__', side_effect=protected), self.assertRaises(ValueError):
            run.main(['--execute', '--data-directory', '/missing-fixture-data'])

    def test_fake_mount_or_id_does_not_permit_local_project(self):
        with patch.dict(os.environ, {'RUNPOD_POD_ID': 'not-attestation'}), patch('os.path.ismount', return_value=True):
            with self.assertRaises(ValueError):
                require_remote(Path.cwd(), Path.cwd() / 'data', Path('/workspace/runs'))

    def test_monitor_stops_a_plain_non_model_process_on_deadline(self):
        with tempfile.TemporaryDirectory() as temp:
            result = run.monitor([sys.executable, '-c', 'import time; time.sleep(5)'],
                                 Path(temp) / 'child.log', time.monotonic() + .1,
                                 run.child_environment(Path.cwd()))
        self.assertFalse(result['passed'])
        self.assertTrue(result['deadline_reached'])
        self.assertLess(result['wall_seconds'], 3)

    def test_launcher_signal_cleans_up_its_plain_child(self):
        helper = '''
import os, signal, sys, threading, time
from pathlib import Path
from specialists.run import child_environment, monitor
root=Path(sys.argv[1]); pidfile=root/'pid'
def interrupt():
    until=time.monotonic()+3
    while not pidfile.exists() and time.monotonic()<until: time.sleep(.01)
    if pidfile.exists(): os.kill(os.getpid(), signal.SIGTERM)
threading.Thread(target=interrupt, daemon=True).start()
child="import os,time; from pathlib import Path; Path("+repr(str(pidfile))+").write_text(str(os.getpid())); time.sleep(5)"
try:
    monitor([sys.executable,'-c',child],root/'log',time.monotonic()+4,child_environment(Path.cwd()))
except InterruptedError:
    pid=int(pidfile.read_text())
    try: os.kill(pid,0)
    except ProcessLookupError: sys.exit(0)
    sys.exit(2)
sys.exit(3)
'''
        with tempfile.TemporaryDirectory() as temp:
            result = subprocess.run([sys.executable, '-B', '-c', helper, temp],
                                    env=run.child_environment(prepare.ROOT),
                                    capture_output=True, timeout=6)
        self.assertEqual(result.returncode, 0, result.stderr.decode())


class PreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        for name in prepare.RUNTIME_FILES:
            source = prepare.ROOT / 'specialists' / name
            target = cls.root / 'specialists' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        cls.report = prepare.prepare(cls.root)

    def test_runtime_bundle_excludes_heldout_and_generator(self):
        archive = self.root / 'artifacts' / self.report['artifact']
        verified = verify_archive(archive, max_bytes=16 * 1024 * 1024)
        paths = {entry['path'] for entry in verified['manifest']['files']}
        self.assertNotIn('specialists/data.py', paths)
        self.assertTrue(all('evaluation/' not in p and 'test-' not in p and '/tests/' not in p for p in paths))
        self.assertTrue(all(not p.startswith('training/') for p in paths))
        self.assertIn('specialists/runtime.py', paths)
        self.assertFalse(self.report['model_execution_performed'])
        self.assertFalse(self.report['trained_weights_created'])
        self.assertFalse(self.report['model_quality_verified'])
        self.assertLessEqual(self.report['parameter_estimate']['fp32_bytes'], 25000000)

    def test_data_hashes_and_split_sizes(self):
        data = self.root / 'data/synthetic/specialists-v1'
        fingerprint = run.verify_data(data)
        self.assertEqual(len(fingerprint), 64)
        self.assertEqual(self.report['counts']['train'], {'span': 768, 'rank': 512})
        self.assertEqual(self.report['counts']['test'], {'span': 384, 'rank': 256})

    def test_plan_only_has_no_neural_import_or_provider_action(self):
        real_import = builtins.__import__

        def protected(name, *args, **kwargs):
            if name.split('.')[0] in {'torch', 'transformers', 'onnxruntime', 'boto3'}:
                raise AssertionError('Preparation must not import a neural or cloud runtime')
            return real_import(name, *args, **kwargs)

        with patch('builtins.__import__', side_effect=protected), redirect_stdout(io.StringIO()) as stream:
            code = run.main(['--config', str(self.root / 'specialists/config.json'),
                             '--data-directory', str(self.root / 'data/synthetic/specialists-v1')])
        plan = json.loads(stream.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(plan['plan_only'])
        self.assertFalse(plan['model_execution_performed'])
        self.assertFalse(plan['language_model_used'])
        self.assertFalse(plan['provider_resources_changed'])

    def test_tampered_data_or_unknown_training_files_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp) / 'data'
            shutil.copytree(self.root / 'data/synthetic/specialists-v1', data)
            (data / 'test-span.jsonl').write_text('do not train on held-out labels')
            with self.assertRaises(ValueError):
                run.verify_data(data)
            (data / 'test-span.jsonl').unlink()
            with (data / 'train-span.jsonl').open('ab') as stream:
                stream.write(b'changed')
            with self.assertRaises(ValueError):
                run.verify_data(data)

    def test_prepare_reuses_identical_bundle_and_preserves_changed_source(self):
        same = prepare.prepare(self.root)
        self.assertEqual(same['sha256'], self.report['sha256'])
        old = (self.root / 'specialists/README.md').read_bytes()
        (self.root / 'specialists/README.md').write_bytes(old + b'\nnew source\n')
        try:
            with self.assertRaises(ValueError):
                prepare.prepare(self.root)
        finally:
            (self.root / 'specialists/README.md').write_bytes(old)

    def test_export_failure_never_records_completed_training(self):
        data = self.root / 'data/synthetic/specialists-v1'
        config_path = self.root / 'specialists/config.json'
        config = json.loads(config_path.read_text())
        fingerprint = run.verify_data(data)
        source = {'files': [
            {'path': 'specialists/config.json', 'sha256': run.sha256_file(config_path)},
            {'path': 'data/synthetic/specialists-v1/manifest.json', 'sha256': fingerprint}]}
        expected = {'config_sha256': run.sha256_file(config_path),
                    'dataset_manifest_sha256': fingerprint,
                    'files': {name: run.sha256_file(data / name) for name in sorted(run.DATA_FILES)}}
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            args = argparse.Namespace(config=config_path, data_directory=data,
                output_directory=output, stage='baseline', hourly_rate_usd='.75', remaining_compute_usd='.1')

            def completed_stage(command, log, deadline, environment):
                (Path(log).parent / 'baseline.json').write_text(json.dumps({'input_fingerprints': expected}))
                return {'passed': True}

            with patch.object(run, 'ROOT', self.root), patch.object(run, 'require_remote', return_value=(self.root, data, output)), \
                    patch.object(run, 'verify_manifest', return_value=source), \
                    patch.object(run, 'monitor', side_effect=completed_stage), \
                    patch.object(run, 'write_manifest', side_effect=ValueError('fixture export failure')):
                with self.assertRaises(ValueError):
                    run.execute(args, config, fingerprint, 30)
            receipts = list(output.glob('*.receipt.json'))
            self.assertEqual(len(receipts), 1)
            receipt = json.loads(receipts[0].read_text())
            self.assertTrue(receipt['stages_completed'])
            self.assertFalse(receipt['completed'])
            self.assertFalse(receipt['archive_verified'])


if __name__ == '__main__':
    unittest.main()
