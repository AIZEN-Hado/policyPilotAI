"""Small fixture repositories only; never commits to the project repository."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.dev import schedule_commits as s


class PartitionTests(unittest.TestCase):
    def test_exactly_500_real_line_changes_reconstruct_all_files(self):
        files = {'app/main.py': (b''.join(f'line {i}\n'.encode() for i in range(1200)), 0o100644),
                 'data/synthetic/scan.pdf': (b'%PDF\nfixture\n', 0o100644),
                 'app/__init__.py': (b'', 0o100644)}
        entries = s.partition(files, 500)
        self.assertEqual(len(entries), 500)
        prefixes = {}
        for entry in entries:
            path, start, end = entry['path'], entry['start'], entry['end']
            self.assertEqual(len(prefixes.get(path, b'')), start)
            self.assertTrue(path not in prefixes or end > start)
            prefixes[path] = files[path][0][:end]
        self.assertEqual(prefixes, {path: value[0] for path, value in files.items()})
        self.assertEqual(sum(e['path'].endswith('.pdf') for e in entries), 1)

    def test_no_empty_padding(self):
        with self.assertRaises(s.ScheduleError):
            s.partition({'app.py': (b'only line\n', 0o100644)}, 2)

    def test_allowlist_filters_private_and_includes_build_files(self):
        for path in ['deploy/cloud.env', 'pilot/.env.production', 'app/.hidden/token.json',
                     '.aws/config.json', 'pilot/private_key.txt']:
            self.assertFalse(s.eligible(Path(path)), path)
        for path in ['.gitignore', '.dockerignore', '.env.example', 'pilot/Dockerfile', 'deploy/Caddyfile']:
            self.assertTrue(s.eligible(Path(path)), path)

    def test_secrets_stop_export_without_echoing_secret(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            (source / 'app').mkdir()
            secret = 'gh' + 'p_' + 'a' * 40
            (source / 'app/config.py').write_text('TOKEN = "' + secret + '"')
            with self.assertRaises(s.ScheduleError) as caught:
                s.collect(source)
            self.assertNotIn(secret, str(caught.exception))

    def test_dates_and_external_git_settings_not_inherited(self):
        with patch.dict(os.environ, {'GIT_AUTHOR_DATE': '2000-01-01',
                                     'GIT_COMMITTER_DATE': '2000-01-01',
                                     'GIT_CONFIG_COUNT': '1', 'GIT_DIR': '/unexpected'}):
            env = s.clean_env({'name': 'Fixture Person', 'email': 'fixture@example.invalid'})
        self.assertNotIn('GIT_AUTHOR_DATE', env)
        self.assertNotIn('GIT_COMMITTER_DATE', env)
        self.assertNotIn('GIT_DIR', env)
        self.assertNotIn('GIT_CONFIG_COUNT', env)
        self.assertEqual(env['GIT_CONFIG_GLOBAL'], os.devnull)
        self.assertEqual(env['GIT_AUTHOR_NAME'], env['GIT_COMMITTER_NAME'])


class SlotTests(unittest.TestCase):
    def plan(self):
        return {'total': 500, 'per_day': 50, 'timezone': 'Asia/Kolkata', 'start_date': '2026-11-18'}

    def test_exactly_50_spread_across_each_full_online_day(self):
        plan = self.plan()
        state = {'next': 0, 'commits': []}
        start = datetime(2026, 11, 17, 18, 30, tzinfo=timezone.utc)
        times = []
        for minute in range(2 * 1440):
            now = start + timedelta(minutes=minute)
            if s.due(plan, state, now)[0]:
                state['next'] += 1
                state['commits'].append({'at': int(now.timestamp())})
                times.append(now)
        self.assertEqual(len(times), 100)
        self.assertTrue(all((b - a).total_seconds() >= 28 * 60 for a, b in zip(times, times[1:])))

    def test_no_catch_up_burst_after_downtime(self):
        plan = self.plan()
        now = datetime(2026, 11, 18, 17, tzinfo=timezone.utc)
        state = {'next': 0, 'commits': []}
        self.assertTrue(s.due(plan, state, now)[0])
        state['next'] = 1
        state['commits'].append({'at': int(now.timestamp())})
        self.assertFalse(s.due(plan, state, now + timedelta(seconds=1))[0])

    def test_daily_limit_and_completion(self):
        plan = self.plan()
        now = datetime(2026, 11, 18, 14, tzinfo=timezone.utc)
        state = {'next': 50, 'commits': [{'at': int(now.timestamp())}] * 50}
        self.assertFalse(s.due(plan, state, now + timedelta(hours=1))[0])
        state['next'] = 500
        self.assertFalse(s.due(plan, state, now + timedelta(days=1))[0])


class RepositoryTests(unittest.TestCase):
    def fixture(self, base):
        source, output = base / 'source', base / 'history'
        (source / 'app').mkdir(parents=True)
        (source / 'app/main.py').write_bytes(b'first\nsecond\nthird\nfourth\n')
        (source / 'app/main.py').chmod(0o755)
        args = SimpleNamespace(source=source, directory=output, total=4, per_day=50,
                               author_name='Fixture Person', author_email='fixture@example.invalid',
                               timezone='Asia/Kolkata', start_date='2026-11-18')
        s.prepare(args)
        plan, state = s.load(output)
        return output, plan, state

    def test_real_git_commits_identity_nonempty_final_tree_and_recovery(self):
        with tempfile.TemporaryDirectory() as temp:
            output, plan, state = self.fixture(Path(temp))
            repo = output / 'repository.git'
            self.assertIsNone(s.head(repo))
            s.commit_one(output, plan, state)
            # Simulate power loss after ref update but before scheduler state write.
            old = json.loads((output / 'state.json').read_text())
            self.assertTrue(s.recover(repo, plan, old))
            self.assertEqual(state, old)
            s.save_json(output / 'state.json', old)
            for _ in range(plan['total'] - 1):
                previous = s.git(repo, 'rev-parse', 'HEAD^{tree}').stdout
                s.commit_one(output, plan, state)
                self.assertNotEqual(previous, s.git(repo, 'rev-parse', 'HEAD^{tree}').stdout)
            s.verify(output, plan, state)
            identities = s.git(repo, 'log', '--format=%an|%ae|%cn|%ce').stdout.decode().splitlines()
            self.assertEqual(set(identities), {'Fixture Person|fixture@example.invalid|Fixture Person|fixture@example.invalid'})
            self.assertEqual(s.git(repo, 'remote').stdout, b'')
            self.assertEqual(s.git(repo, 'show', 'HEAD:app/main.py').stdout, b'first\nsecond\nthird\nfourth\n')
            self.assertTrue(s.git(repo, 'ls-tree', 'HEAD', 'app/main.py').stdout.startswith(b'100755'))

    def test_modified_frozen_snapshot_and_plan_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            output, plan, state = self.fixture(Path(temp))
            (output / 'snapshot/HISTORY_IMPORT.md').write_text('changed')
            with self.assertRaises(s.ScheduleError):
                s.commit_one(output, plan, state)
            (output / 'plan.json').write_text('{}')
            with self.assertRaises(s.ScheduleError):
                s.load(output)

    def test_timer_installer_writes_only_unit_files_without_starting(self):
        with tempfile.TemporaryDirectory() as temp:
            output, _, _ = self.fixture(Path(temp))
            units = Path(temp) / 'units'
            with patch.object(subprocess, 'run', side_effect=AssertionError('No systemctl calls allowed')):
                s.install_timer(SimpleNamespace(directory=output, unit_directory=units))
            self.assertEqual(len(list(units.iterdir())), 2)
            timer = (units / 'policypilot-history-commits.timer').read_text()
            self.assertIn('Persistent=false', timer)
            service = (units / 'policypilot-history-commits.service').read_text()
            self.assertIn('"tick"', service)
            self.assertNotIn('push', service.split('ExecStart=', 1)[1])

    def test_global_hook_never_runs(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            home = base / 'home'
            hooks = base / 'hooks'
            home.mkdir()
            hooks.mkdir()
            flag = base / 'HOOK_RAN'
            hook = hooks / 'reference-transaction'
            hook.write_text('#!/bin/sh\ntouch "' + str(flag) + '"\n')
            hook.chmod(0o755)
            (home / '.gitconfig').write_text('[core]\n hooksPath = ' + str(hooks) + '\n')
            with patch.dict(os.environ, {'HOME': str(home)}):
                output, plan, state = self.fixture(base)
                s.commit_one(output, plan, state)
            self.assertFalse(flag.exists())


if __name__ == '__main__':
    unittest.main()
