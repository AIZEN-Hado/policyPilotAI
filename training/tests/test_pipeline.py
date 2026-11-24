import copy
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from pilot.core import validate_output
from training.artifacts import MANIFEST, pack, safe_name, snapshot, verify, verify_archive
from training.common import records, supervised_tokens, validate_cuda_build
from training.data import build
from training.run import child_environment, monitor, seconds_allowed
from training.score import evaluate, score_case


class DatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.metadata = build(cls.root)
        cls.corpus = cls.root / 'data/synthetic/finetune-v1'
        cls.evaluation = cls.root / 'evaluation/finetune-v1'

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_family_splits_are_disjoint_and_match_counts(self):
        self.assertEqual(self.metadata['counts'], {'train': 144, 'validation': 72, 'test': 72})
        families = self.metadata['families']
        for a, b in (('train', 'validation'), ('train', 'test'), ('validation', 'test')):
            self.assertFalse(set(families[a]) & set(families[b]))

    def test_deterministic_generation_and_tamper_preservation(self):
        before = (self.corpus / 'train.jsonl').read_bytes()
        build(self.root)
        self.assertEqual(before, (self.corpus / 'train.jsonl').read_bytes())
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            build(root)
            path = root / 'data/synthetic/finetune-v1/train.jsonl'
            path.write_text('keep this changed data')
            with self.assertRaises(ValueError):
                build(root)
            self.assertEqual(path.read_text(), 'keep this changed data')

    def test_targets_have_valid_case_scoped_citations(self):
        for row in records(self.corpus / 'train.jsonl'):
            evidence = json.loads(row['messages'][1]['content'])['excerpts']
            target = json.loads(row['messages'][2]['content'])
            validate_output(target, evidence)
            self.assertTrue(all(chunk['document_id'].startswith(row['id']) for chunk in evidence))

    def test_prompt_only_splits_contain_no_answer_fields(self):
        for path in (self.corpus / 'validation-prompts.jsonl', self.evaluation / 'test-prompts.jsonl'):
            for row in records(path):
                self.assertEqual([m['role'] for m in row['messages']], ['system', 'user'])
                self.assertNotIn('expected', row)
                self.assertNotIn('checks', row)
        self.assertFalse((self.corpus / 'test-prompts.jsonl').exists())
        self.assertFalse(any('labels' in path.name for path in self.corpus.iterdir()))

    def test_non_synthetic_and_duplicate_rows_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / 'rows.jsonl'
            path.write_text(json.dumps({'id': 'x', 'synthetic': False}) + '\n')
            with self.assertRaises(ValueError): records(path)
            path.write_text((json.dumps({'id': 'x', 'synthetic': True}) + '\n') * 2)
            with self.assertRaises(ValueError): records(path)

    def test_oracle_checker_is_not_model_accuracy(self):
        labels = records(self.evaluation / 'validation-labels.jsonl')
        prompts = records(self.corpus / 'validation-prompts.jsonl')
        answers = [{'id': row['id'], 'output': row['expected']} for row in labels]
        result = evaluate(prompts, labels, answers)
        self.assertEqual(result['metrics']['passed'], 1)
        self.assertTrue(result['full_split_coverage'])
        self.assertFalse(result['model_quality_verified'])
        subset = evaluate(prompts, labels, answers[:3], first=3)
        self.assertFalse(subset['full_split_coverage'])

    def test_missing_extra_and_duplicate_predictions_rejected(self):
        labels = records(self.evaluation / 'validation-labels.jsonl')
        prompts = records(self.corpus / 'validation-prompts.jsonl')
        answers = [{'id': row['id'], 'output': row['expected']} for row in labels]
        for bad in (answers[:-1], answers + [{'id': 'extra', 'output': {}}], answers + answers[:1]):
            with self.assertRaises(ValueError): evaluate(prompts, labels, bad)

    def test_fabricated_citations_omissions_and_unsafe_decisions_fail(self):
        prompts = records(self.corpus / 'validation-prompts.jsonl')
        labels = records(self.evaluation / 'validation-labels.jsonl')
        target = copy.deepcopy(labels[0]['expected'])
        target['findings'][0]['quote'] = 'An invented quotation that never appeared.'
        self.assertFalse(score_case(prompts[0], labels[0], target)['citations_valid'])
        target = copy.deepcopy(labels[1]['expected'])
        target['questions'] = []
        self.assertFalse(score_case(prompts[1], labels[1], target)['questions_complete'])
        target = copy.deepcopy(labels[0]['expected'])
        target['summary'] = 'The payment is approved.'
        self.assertFalse(score_case(prompts[0], labels[0], target)['no_unsafe_decision'])
        self.assertFalse(score_case(prompts[0], labels[0], '```json\n{}\n```')['format_valid'])


class SupervisionTests(unittest.TestCase):
    def test_only_assistant_tokens_receive_training_labels(self):
        class Tokenizer:
            def apply_chat_template(self, messages, **kwargs):
                return [10, 11, 12] if len(messages) == 2 else [10, 11, 12, 20, 21]
        ids, labels = supervised_tokens(Tokenizer(), [{}, {}, {}], 10)
        self.assertEqual(ids, [10, 11, 12, 20, 21])
        self.assertEqual(labels, [-100, -100, -100, 20, 21])

    def test_overlong_and_misaligned_examples_fail_without_truncation(self):
        class Tokenizer:
            def apply_chat_template(self, messages, **kwargs):
                return [1, 2] if len(messages) == 2 else [1, 2, 3, 4]
        with self.assertRaises(ValueError): supervised_tokens(Tokenizer(), [{}, {}, {}], 3)
        class Misaligned(Tokenizer):
            def apply_chat_template(self, messages, **kwargs):
                return [1, 9] if len(messages) == 2 else [1, 2, 3, 4]
        with self.assertRaises(ValueError): supervised_tokens(Misaligned(), [{}, {}, {}], 10)


class CudaBuildTests(unittest.TestCase):
    def test_existing_ampere_candidate_remains_supported(self):
        validate_cuda_build((8, 6), '12.6', ['sm_86'])

    def test_blackwell_requires_matching_cuda_build_and_architecture(self):
        for build, architectures in (('12.6', ['sm_86']), (None, []), ('12.8', ['sm_90']), ('12', [])):
            with self.assertRaises(ValueError):
                validate_cuda_build((12, 0), build, architectures)

    def test_blackwell_cuda128_wheel_metadata_passes_before_native_probe(self):
        validate_cuda_build((12, 0), '12.8', ['sm_86', 'sm_120'])
        validate_cuda_build((12, 0), '12.8', ['compute_120'])


class ArtifactTests(unittest.TestCase):
    def test_manifest_and_archive_reject_tampering(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            artifact = root / 'adapter'; artifact.mkdir()
            file = artifact / 'adapter_model.safetensors'; file.write_bytes(b'synthetic-fixture-not-a-model')
            snapshot(artifact, {'base_revision': 'a' * 40})
            verify(artifact)
            archive = root / 'bundle.tar.gz'
            pack({'adapter/' + p.name: p for p in artifact.iterdir()}, archive)
            verify_archive(archive)
            with self.assertRaises(ValueError): pack({'file': file}, archive)
            file.write_bytes(b'corrupt')
            with self.assertRaises(ValueError): verify(artifact)
            archive.write_bytes(archive.read_bytes() + b'corrupt')
            with self.assertRaises(ValueError): verify_archive(archive)

    def test_untracked_files_links_and_unsafe_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / 'adapter.json').write_text('{}')
            snapshot(root, {})
            (root / 'extra').write_text('not tracked')
            with self.assertRaises(ValueError): verify(root)
            (root / 'extra').unlink()
            (root / 'link').symlink_to(root / 'adapter.json')
            with self.assertRaises(ValueError): snapshot(root, {})
        for name in ('../file', '/file', './file', 'a//file', 'a\\file', '.env', 'x\x00'):
            with self.assertRaises(ValueError): safe_name(name)


class BudgetAndProcessTests(unittest.TestCase):
    def test_duration_respects_caller_allowance_and_rejects_nonfinite_values(self):
        self.assertEqual(seconds_allowed(300, '0.75', '0.01'), 48)
        self.assertEqual(seconds_allowed(300, '0.75', '0.10'), 300)
        for rate, budget in (('NaN', '1'), ('0', '1'), ('-1', '1'), ('1', 'Infinity'), ('1', '3'), ('bad', '1')):
            with self.assertRaises(ValueError): seconds_allowed(300, rate, budget)
        with self.assertRaises(ValueError): seconds_allowed(10, '1', '1')

    def test_cloud_ram_has_no_artificial_cap_and_plan_cannot_start_model(self):
        from training import run
        output = io.StringIO()
        with patch('sys.argv', [
                'training.run', '--mode', 'preflight', '--workspace', '/workspace/models',
                '--gpu-hourly-usd', '0.27', '--compute-budget-usd', '0.05']),\
             patch.object(run.subprocess, 'Popen') as start, contextlib.redirect_stdout(output):
            self.assertEqual(run.main(), 0)
        report = json.loads(output.getvalue())
        self.assertIsNone(report['rss_limit_bytes'])
        self.assertFalse(report['local_model_execution_allowed'])
        self.assertEqual(report['model_execution_location'], 'remote_gpu_pod_only')
        start.assert_not_called()

    def test_local_execution_policy_and_invalid_cloud_caps_rejected(self):
        from training import run
        for config in ({'model_execution_location': 'local'},
                       {'model_execution_location': 'remote_gpu_pod_only', 'model_process_ram_limit_bytes': -1}):
            with patch.object(run, 'read_json', return_value=config), patch('sys.argv', [
                    'training.run', '--mode', 'preflight', '--workspace', '/workspace/models',
                    '--gpu-hourly-usd', '0.27', '--compute-budget-usd', '0.05']):
                with self.assertRaises(ValueError):
                    run.main()

    def test_execute_is_blocked_on_this_machine_before_model_imports(self):
        from training import run
        with tempfile.TemporaryDirectory() as name, patch('sys.argv', [
                'training.run', '--mode', 'preflight', '--workspace', name, '--execute',
                '--gpu-hourly-usd', '0.27', '--compute-budget-usd', '0.05']),\
             patch.object(run.subprocess, 'Popen') as start:
            with self.assertRaisesRegex(ValueError, 'Execute only on the existing Pod'):
                run.main()
            start.assert_not_called()

    def test_a_local_workspace_mount_alone_does_not_allow_model_execution(self):
        from training import run
        with patch.dict(os.environ, {}, clear=True), patch.object(run.os.path, 'ismount', return_value=True),\
             patch('sys.argv', ['training.run', '--mode', 'preflight', '--workspace', '/workspace/models',
                                '--execute', '--gpu-hourly-usd', '0.27', '--compute-budget-usd', '0.05']),\
             patch.object(run.subprocess, 'Popen') as start:
            with self.assertRaisesRegex(ValueError, 'provider Pod ID'):
                run.main()
            start.assert_not_called()

    def test_runtime_does_not_inherit_cloud_or_database_secrets(self):
        with patch.dict(os.environ, {'RUNPOD_API_KEY': 'synthetic-key', 'DATABASE_URL': 'synthetic-db',
                                     'AWS_SECRET_ACCESS_KEY': 'synthetic-secret', 'HF_TOKEN': 'synthetic-hf'}):
            env = child_environment(Path('/workspace/experiment'))
        for key in ('RUNPOD_API_KEY', 'DATABASE_URL', 'AWS_SECRET_ACCESS_KEY', 'HF_TOKEN'):
            self.assertNotIn(key, env)
        self.assertEqual(env['POLICYPILOT_BOUNDED_CHILD'], '1')

    def test_monitor_records_real_child_peak_and_deadline_termination(self):
        with tempfile.TemporaryDirectory() as name:
            log = Path(name) / 'child.log'
            ok = monitor([sys.executable, '-c', 'print("synthetic child")'], log,
                         time.monotonic() + 5, 256_000_000, os.environ.copy())
            self.assertTrue(ok['passed'])
            self.assertGreater(ok['peak_rss_bytes'], 0)
            timed = monitor([sys.executable, '-c', 'import time; time.sleep(30)'], log,
                            time.monotonic() + 0.1, 256_000_000, os.environ.copy())
            self.assertEqual(timed['stop_reason'], 'execution_deadline_reached')
            self.assertFalse(timed['passed'])
            self.assertLess(timed['wall_seconds'], 5)

    def test_monitor_rejects_process_exceeding_ram_target(self):
        with tempfile.TemporaryDirectory() as name:
            result = monitor([sys.executable, '-c', 'import time; x=bytearray(30_000_000); time.sleep(30)'],
                             Path(name) / 'child.log', time.monotonic() + 5, 20_000_000, os.environ.copy())
            self.assertEqual(result['stop_reason'], 'model_process_ram_target_exceeded')
            self.assertFalse(result['passed'])

    def test_cloud_process_peak_is_recorded_without_fixed_ram_cap(self):
        with tempfile.TemporaryDirectory() as name:
            result = monitor([sys.executable, '-c', 'print("small synthetic process")'],
                             Path(name) / 'child.log', time.monotonic() + 5, None, os.environ.copy())
            self.assertTrue(result['passed'])
            self.assertGreater(result['peak_rss_bytes'], 0)


if __name__ == '__main__':
    unittest.main()
