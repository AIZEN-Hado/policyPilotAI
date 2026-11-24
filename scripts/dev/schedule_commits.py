#!/usr/bin/env python3
"""Import a frozen project snapshot gradually. Standard library + local Git only.

No network, pushes, empty commits, fabricated development chronology or backdating.
The output is a separate bare repository, never the source checkout's .git.
"""
import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import fcntl
import hashlib
import heapq
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from zoneinfo import ZoneInfo

ROOT_FILES = {
    '.gitignore', '.dockerignore', '.env.example', 'README.md', 'requirements.txt',
    'pytest.ini', 'flake.nix', 'shell.nix', 'render.yaml', 'render-demo.yaml',
}
ROOT_DIRS = ('app', 'pilot', 'ui', 'deploy', 'docs', 'scripts', 'tests', 'training',
             'data/synthetic', 'evaluation', 'web-showcase')
SKIP_PARTS = {'.git', '.aws', '.agents', '.codex', '.claude', '.openai', '.venv',
              '__pycache__', '.pytest_cache', 'node_modules', 'backups', 'secrets', 'credentials'}
SUFFIXES = {'.py', '.md', '.txt', '.json', '.jsonl', '.sql', '.html', '.css',
            '.js', '.yaml', '.yml', '.sh', '.nix', '.ini', '.pdf', '.png', '.svg'}
SECRET_PATTERNS = (
    rb'\bgh[pousr]_[A-Za-z0-9]{20,}', rb'\bgithub_pat_[A-Za-z0-9_]{20,}',
    rb'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b', rb'\brpa_[A-Za-z0-9_-]{20,}',
    rb'\bhf_[A-Za-z0-9]{24,}',
    rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----',
    rb'(?i)postgres(?:ql)?://[^\s/:]+:[^\s/@]+@',
)
NOTE = '''# Retrospective source import

These commits import a frozen PolicyPilot snapshot in small pieces at their
actual commit times. They are not the original development commits, and do not
reconstruct earlier file versions or dates. Intermediate trees may be incomplete.

Documented work includes the local prototype, authenticated Render application,
synthetic document fixtures, the retired Serverless experiment, persistent cloud
storage planning, optional training preparation, and the pretrained-model/parser
review. See docs/IMPLEMENTATION_PLAN.md, docs/PERSISTENT_STORAGE_PLAN.md,
docs/FINETUNING_PREPARATION.md, docs/PRETRAINED_PARSER_PLAN.md and pilot/VERIFICATION.md.
These references describe work and pivots; they do not establish a successful
trained model, GPU inference deployment, or production accuracy.

Private environment files, operator caches and artifacts are not imported.
No automatic push is configured. Inspect the completed history before publishing.
'''


class ScheduleError(Exception):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save_json(path, value):
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w', encoding='utf-8') as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def clean_env(identity=None, read_identity_config=False):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update({'GIT_TERMINAL_PROMPT': '0', 'GIT_CONFIG_NOSYSTEM': '1'})
    if not read_identity_config:
        env['GIT_CONFIG_GLOBAL'] = os.devnull
    if identity:
        for role in ('AUTHOR', 'COMMITTER'):
            env[f'GIT_{role}_NAME'] = identity['name']
            env[f'GIT_{role}_EMAIL'] = identity['email']
    return env


def git(repo, *args, data=None, env=None, check=True):
    result = subprocess.run(['git', '-c', f'core.hooksPath={os.devnull}', '-C', str(repo), *args], input=data,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=env or clean_env(), check=False)
    if check and result.returncode:
        # Do not echo arbitrary configuration, filenames or remote credentials.
        raise ScheduleError(f'Local Git operation failed ({args[0]}). No push attempted.')
    return result


def safe_path(value):
    p = PurePosixPath(value)
    if (not value or p.is_absolute() or '..' in p.parts or '.git' in p.parts
            or '\x00' in value or '\\' in value):
        raise ScheduleError('Unsafe path in import plan')
    return p


def eligible(path):
    rel = path.as_posix()
    if rel in ROOT_FILES:
        return True
    if any(p in SKIP_PARTS for p in path.parts):
        return False
    if any(part.startswith('.') for part in path.parts[:-1]):
        return False
    if path.name != '.env.example' and ('.env' in path.name or path.name.startswith('.')):
        return False
    if any(word in path.name.lower() for word in ('credential', 'private_key', 'id_rsa')):
        return False
    return path.suffix.lower() in SUFFIXES or path.name in {'Dockerfile', 'Caddyfile'}


def collect(source):
    candidates = [source / p for p in ROOT_FILES if (source / p).is_file()]
    for directory in ROOT_DIRS:
        root = source / directory
        if root.is_dir():
            candidates.extend(root.rglob('*'))
    result = {}
    for path in sorted(set(candidates)):
        rel = path.relative_to(source)
        if not path.is_file() or not eligible(rel):
            continue
        if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != source.parent):
            raise ScheduleError('Symlink found in export candidates; review source paths')
        if path.stat().st_size > 16 * 1024 * 1024:
            raise ScheduleError(f'Export candidate exceeds 16 MiB: {rel.as_posix()}')
        data = path.read_bytes()
        if not data:  # Empty files do not furnish non-empty line chunks.
            result[rel.as_posix()] = (data, 0o100755 if path.stat().st_mode & 0o111 else 0o100644)
            continue
        if any(re.search(pattern, data) for pattern in SECRET_PATTERNS):
            raise ScheduleError(f'Possible credential in {rel.as_posix()}; contents withheld. Review before export.')
        result[rel.as_posix()] = (data, 0o100755 if path.stat().st_mode & 0o111 else 0o100644)
    result['HISTORY_IMPORT.md'] = (NOTE.encode(), 0o100644)
    return result


def partition(files, total):
    """Exactly total non-empty tree changes, splitting UTF-8 text at line ends."""
    if len(files) > total:
        raise ScheduleError(f'{len(files)} files exceed {total} commits; choose a larger total or narrow the export')
    boundaries, parts, queue = {}, {}, []
    for path, (data, mode) in sorted(files.items()):
        ends = [0]
        try:
            if ('\x00' in data.decode('utf-8') or path == 'HISTORY_IMPORT.md'
                    or PurePosixPath(path).suffix.lower() in {'.pdf', '.png'}):
                raise ValueError()
            for line in data.splitlines(keepends=True):
                ends.append(ends[-1] + len(line))
        except (UnicodeError, ValueError):
            ends = [0, len(data)]
        if len(ends) == 1:
            ends.append(0)  # Creating an empty file is still a real tree change.
        boundaries[path] = ends
        parts[path] = {(0, len(ends) - 1)}
        if len(ends) > 2:
            heapq.heappush(queue, (-(ends[-1] - ends[0]), path, 0, len(ends) - 1))
    count = len(files)
    while count < total:
        if not queue:
            raise ScheduleError(f'Only {count} line-safe changes available; refusing empty padding')
        _, path, first, last = heapq.heappop(queue)
        middle = (first + last) // 2
        parts[path].remove((first, last))
        for a, b in ((first, middle), (middle, last)):
            parts[path].add((a, b))
            if b - a > 1:
                heapq.heappush(queue, (-(boundaries[path][b] - boundaries[path][a]), path, a, b))
        count += 1
    entries = []
    paths = sorted(files, key=lambda p: (p != 'HISTORY_IMPORT.md', p))
    for path in paths:
        pieces = sorted(parts[path])
        data, mode = files[path]
        for number, (a, b) in enumerate(pieces, 1):
            entries.append({'path': path, 'start': boundaries[path][a],
                            'end': boundaries[path][b], 'mode': mode,
                            'message': f'import(snapshot): {path} (part {number}/{len(pieces)})'})
    return entries


def default_identity(field, source):
    result = subprocess.run(['git', '-C', str(source), 'config', '--get', f'user.{field}'],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            env=clean_env(read_identity_config=True))
    return result.stdout.decode().strip() if result.returncode == 0 else ''


def prepare(args):
    source, output = args.source.resolve(), args.directory.resolve()
    if source == output or source in output.parents and 'artifacts' not in output.relative_to(source).parts:
        raise ScheduleError('Place output outside the source or inside artifacts/')
    if output.exists():
        raise ScheduleError('Output already exists; use status or choose a fresh directory')
    if not 1 <= args.per_day <= 50 or not 1 <= args.total <= 500:
        raise ScheduleError('This scheduler permits at most 500 commits and 50 per day')
    identity = {'name': args.author_name or default_identity('name', source),
                'email': args.author_email or default_identity('email', source)}
    if any(not value or any(c in value for c in '\r\n<>') for value in identity.values()):
        raise ScheduleError('Set --author-name and --author-email to valid Git identity values')
    tz = ZoneInfo(args.timezone)
    start = date.fromisoformat(args.start_date) if args.start_date else datetime.now(tz).date() + timedelta(days=1)
    files = collect(source)
    entries = partition(files, args.total)
    output.mkdir(parents=True, mode=0o700)
    snapshot = output / 'snapshot'
    snapshot.mkdir()
    metadata = {}
    for path, (data, mode) in files.items():
        dest = snapshot.joinpath(*safe_path(path).parts)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        metadata[path] = {'sha256': digest(data), 'size': len(data), 'mode': mode}
    plan = {'version': 1, 'id': uuid.uuid4().hex, 'source': str(source),
            'created_at': datetime.now(timezone.utc).isoformat(), 'identity': identity,
            'timezone': args.timezone, 'start_date': start.isoformat(),
            'per_day': args.per_day, 'total': args.total, 'files': metadata, 'entries': entries}
    save_json(output / 'plan.json', plan)
    (output / 'plan.sha256').write_text(digest((output / 'plan.json').read_bytes()) + '\n')
    save_json(output / 'state.json', {'next': 0, 'head': None, 'commits': []})
    repo = output / 'repository.git'
    (output / 'empty-hooks').mkdir()
    subprocess.run(['git', 'init', '--bare', '--initial-branch=main',
                    '--template=' + str(output / 'empty-hooks'), str(repo)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, env=clean_env())
    git(repo, 'config', 'user.name', identity['name'])
    git(repo, 'config', 'user.email', identity['email'])
    git(repo, 'config', 'commit.gpgsign', 'false')
    git(repo, 'config', 'core.hooksPath', str(output / 'empty-hooks'))
    print(f'Prepared {len(entries)} non-empty snapshot imports from {len(files)} files.')
    print(f'Identity: {identity["name"]} <{identity["email"]}>')
    print(f'Start: {start.isoformat()} ({args.timezone}); at most {args.per_day}/day.')
    print(f'Review {output / "plan.json"} and snapshot/ before starting the timer.')
    print('Credential scanning is a safeguard, not proof of absence; review the export.')
    print('No commits made; no remote configured; no timer enabled; no push attempted.')


def load(directory):
    if digest((directory / 'plan.json').read_bytes()) != (directory / 'plan.sha256').read_text().strip():
        raise ScheduleError('Plan changed after preparation; refusing to run')
    plan = json.loads((directory / 'plan.json').read_text())
    state = json.loads((directory / 'state.json').read_text())
    if plan['total'] != len(plan['entries']) or not 1 <= plan['per_day'] <= 50 or plan['total'] > 500:
        raise ScheduleError('Invalid plan limits')
    if not 0 <= state['next'] <= plan['total'] or len(state['commits']) != state['next']:
        raise ScheduleError('Invalid scheduler state; retain files for inspection')
    return plan, state


def head(repo):
    result = git(repo, 'rev-parse', '--verify', 'HEAD', check=False)
    return result.stdout.decode().strip() if result.returncode == 0 else None


def marker(plan, index):
    return f'PolicyPilot-Import-ID: {plan["id"]}:{index + 1}'


def record(state, commit, timestamp):
    state['commits'].append({'sha': commit, 'at': timestamp})
    state['head'], state['next'] = commit, state['next'] + 1


def recover(repo, plan, state):
    current = head(repo)
    if current == state['head']:
        return False
    if current is None or state['next'] >= plan['total']:
        raise ScheduleError('Repository history differs from scheduler state')
    fields = git(repo, 'show', '-s', '--format=%P%x00%ct%x00%B', current).stdout.decode().split('\x00', 2)
    parents, stamp, message = fields
    if parents != (state['head'] or '') or marker(plan, state['next']) not in message.splitlines():
        raise ScheduleError('Unexpected commit found; refusing to overwrite user history')
    # A commit completed before the state write: retain it and count its real date.
    record(state, current, int(stamp))
    return True


def due(plan, state, now):
    tz = ZoneInfo(plan['timezone'])
    local = now.astimezone(tz)
    if state['next'] >= plan['total']:
        return False, 'Complete; timer may be disabled.'
    if local.date() < date.fromisoformat(plan['start_date']):
        return False, f'Waiting for {plan["start_date"]} ({plan["timezone"]}).'
    today = [datetime.fromtimestamp(c['at'], tz) for c in state['commits']
             if datetime.fromtimestamp(c['at'], tz).date() == local.date()]
    if len(today) >= plan['per_day']:
        return False, 'Daily quota reached.'
    slot = (local.hour * 3600 + local.minute * 60 + local.second) * plan['per_day'] // 86400
    if today:
        last = today[-1]
        last_slot = (last.hour * 3600 + last.minute * 60 + last.second) * plan['per_day'] // 86400
        if slot <= last_slot:
            return False, 'Waiting for the next daily slot.'
    if state['commits'] and now.timestamp() <= state['commits'][-1]['at']:
        return False, 'Clock precedes the last commit; waiting.'
    return True, 'Ready.'


def commit_one(directory, plan, state):
    repo = directory / 'repository.git'
    entry = plan['entries'][state['next']]
    path = safe_path(entry['path'])
    data = directory.joinpath('snapshot', *path.parts).read_bytes()
    metadata = plan['files'][entry['path']]
    if digest(data) != metadata['sha256'] or len(data) != metadata['size']:
        raise ScheduleError('Frozen source changed; refusing to commit')
    before = git(repo, 'show', f'{state["head"]}:{path}', check=False) if state['head'] else None
    if entry['start']:
        if before is None or before.returncode or before.stdout != data[:entry['start']]:
            raise ScheduleError('File prefix differs from its planned snapshot')
    elif before is not None and before.returncode == 0:
        raise ScheduleError('Unexpected existing path in import repository')
    env = clean_env(plan['identity'])
    # A temporary index builds a new tree without touching a source working tree.
    with tempfile.TemporaryDirectory(prefix='import-index-', dir=directory) as temp:
        env['GIT_INDEX_FILE'] = str(Path(temp) / 'index')
        git(repo, 'read-tree', state['head'] or '--empty', env=env)
        blob = git(repo, 'hash-object', '-w', '--stdin', data=data[:entry['end']], env=env).stdout.decode().strip()
        git(repo, 'update-index', '--add', '--cacheinfo', f'{entry["mode"]:o}', blob, str(path), env=env)
        tree = git(repo, 'write-tree', env=env).stdout.decode().strip()
        if state['head'] and tree == git(repo, 'rev-parse', f'{state["head"]}^{{tree}}').stdout.decode().strip():
            raise ScheduleError('Refusing an empty commit')
        message = f'{entry["message"]}\n\nRetrospective snapshot import; not original development chronology.\n\n{marker(plan, state["next"])}\n'
        args = ['commit-tree', tree]
        if state['head']:
            args += ['-p', state['head']]
        commit = git(repo, *args, data=message.encode(), env=env).stdout.decode().strip()
        git(repo, 'update-ref', 'refs/heads/main', commit, state['head'] or '0' * 40, env=env)
    stamp = int(git(repo, 'show', '-s', '--format=%ct', commit).stdout)
    record(state, commit, stamp)


def verify(directory, plan, state):
    if state['next'] != plan['total']:
        raise ScheduleError('Import is incomplete; final snapshot verification is not available yet')
    repo = directory / 'repository.git'
    tracked = {}
    for item in git(repo, 'ls-tree', '-r', '-z', 'HEAD').stdout.decode().split('\x00'):
        if item:
            properties, path = item.split('\t', 1)
            tracked[path] = int(properties.split()[0], 8)
    if set(tracked) != set(plan['files']):
        raise ScheduleError('Final tracked paths differ from the snapshot')
    for path, metadata in plan['files'].items():
        if (digest(git(repo, 'show', f'HEAD:{path}').stdout) != metadata['sha256']
                or tracked[path] != metadata['mode']):
            raise ScheduleError('Final file differs from the snapshot')
    if int(git(repo, 'rev-list', '--count', 'HEAD').stdout) != plan['total']:
        raise ScheduleError('Final commit count differs from the plan')
    identity = plan['identity']
    expected = f'{identity["name"]}\0{identity["email"]}\0{identity["name"]}\0{identity["email"]}'
    authors = git(repo, 'log', '--format=%an%x00%ae%x00%cn%x00%ce').stdout.decode().splitlines()
    if any(author != expected for author in authors):
        raise ScheduleError('Unexpected author or committer identity')
    git(repo, 'fsck', '--no-reflogs')
    print(f'PASS: {plan["total"]} commits; all {len(plan["files"])} final files match their hashes.')


def run(args):
    directory = args.directory.resolve()
    with (directory / 'lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        plan, state = load(directory)
        repo = directory / 'repository.git'
        if recover(repo, plan, state):
            save_json(directory / 'state.json', state)
        if args.command == 'verify':
            verify(directory, plan, state)
            return
        ready, detail = due(plan, state, datetime.now(timezone.utc))
        if args.command == 'tick' and ready:
            commit_one(directory, plan, state)
            save_json(directory / 'state.json', state)
            detail = f'Created {state["head"][:12]}; {plan["entries"][state["next"] - 1]["message"]}'
        counts = Counter(datetime.fromtimestamp(c['at'], ZoneInfo(plan['timezone'])).date().isoformat()
                         for c in state['commits'])
        if any(count > plan['per_day'] for count in counts.values()):
            raise ScheduleError('Recorded daily quota exceeded; stop and inspect history')
        print(f'{state["next"]}/{plan["total"]} committed. {detail}')
        if args.command == 'status':
            print(f'Author/committer: {plan["identity"]["name"]} <{plan["identity"]["email"]}>')
            print(f'Timezone: {plan["timezone"]}; per-day limit: {plan["per_day"]}; days: {dict(counts)}')
            print('No push or remote modification is performed by this script.')


def systemd_quote(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'


def install_timer(args):
    directory = args.directory.resolve()
    load(directory)  # Preparation and review come before installing anything.
    units = args.unit_directory or Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'systemd/user'
    units.mkdir(parents=True, exist_ok=True)
    base = 'policypilot-history-commits'
    command = ' '.join(systemd_quote(v) for v in
                       (sys.executable, Path(__file__).resolve(), 'tick', '--directory', directory))
    git_executable = shutil.which('git')
    if not git_executable:
        raise ScheduleError('Git is not available in the current environment')
    timer_path = ':'.join((str(Path(git_executable).parent), str(Path(sys.executable).parent),
                           '/run/current-system/sw/bin', '/usr/bin', '/bin'))
    contents = {
        'service': f'''[Unit]
Description=One scheduled PolicyPilot snapshot import (no push)

[Service]
Type=oneshot
ExecStart={command}
Environment={systemd_quote('PATH=' + timer_path)}
UMask=0077
TimeoutStartSec=120
''',
        'timer': f'''[Unit]
Description=Check PolicyPilot import slots once per minute

[Timer]
OnCalendar=*-*-* *:*:00
AccuracySec=1s
Persistent=false
Unit={base}.service

[Install]
WantedBy=timers.target
'''}
    if any((units / f'{base}.{suffix}').exists() for suffix in contents):
        raise ScheduleError('Timer unit already exists; inspect it instead of overwriting')
    for suffix, content in contents.items():
        (units / f'{base}.{suffix}').write_text(content)
    print(f'Wrote user unit files in {units}. Nothing enabled or started.')
    print(f'Run: systemctl --user daemon-reload')
    print(f'Run: systemctl --user enable --now {base}.timer')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'tick', 'status', 'verify', 'install-timer'))
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--directory', type=Path, default=Path(__file__).resolve().parents[2] / 'artifacts/commit-schedule')
    parser.add_argument('--total', type=int, default=500)
    parser.add_argument('--per-day', type=int, default=50)
    parser.add_argument('--timezone', default='Asia/Kolkata')
    parser.add_argument('--start-date', help='YYYY-MM-DD in schedule timezone; default tomorrow')
    parser.add_argument('--author-name')
    parser.add_argument('--author-email')
    parser.add_argument('--unit-directory', type=Path, help='Override user systemd unit destination')
    args = parser.parse_args()
    try:
        if args.command == 'prepare':
            prepare(args)
        elif args.command == 'install-timer':
            install_timer(args)
        else:
            run(args)
    except BlockingIOError:
        print('Another scheduler process holds the lock; skipped.')
    except (ScheduleError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        if isinstance(exc, ScheduleError):
            print(f'CHECK: {exc}', file=sys.stderr)
        else:
            print('CHECK: Local scheduler operation failed; inspect paths/configuration. Details withheld.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
