"""Read-only local readiness checks. Never reads or prints deployment secrets."""
import argparse
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def command_ok(args):
    try:
        return subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                              timeout=20, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-docker', action='store_true',
                        help='Also require a reachable Docker daemon and Compose')
    args = parser.parse_args()
    failures = []

    def report(name, passed):
        print(f'{"PASS" if passed else "FAIL"}: {name}', flush=True)
        if not passed:
            failures.append(name)

    for name in ('fastapi', 'httpx', 'psycopg', 'uvicorn', 'boto3'):
        report(f'Python dependency {name}', importlib.util.find_spec(name) is not None)
    for name in ('pdfinfo', 'pdftotext', 'pdftoppm', 'tesseract', 'node'):
        report(f'Executable {name}', shutil.which(name) is not None)
    langs = command_ok(['tesseract', '--list-langs'])
    report('OCR language data: English and Hindi',
           langs is not None and {'eng', 'hin'} <= set(langs.splitlines()))
    report('Browser JavaScript syntax', command_ok(['node', '--check', 'pilot/static/app.js']) is not None)
    if args.require_docker:
        report('Docker daemon accessible', command_ok(['docker', 'info', '--format', '{{.ServerVersion}}']) is not None)
        report('Docker Compose available', command_ok(['docker', 'compose', 'version']) is not None)

    suite = unittest.defaultTestLoader.discover(str(ROOT / 'pilot/tests'))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report('Pilot tests pass with zero skips', result.wasSuccessful() and not result.skipped)
    print('Local prerequisites only; this does not certify deployment or model quality.')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
