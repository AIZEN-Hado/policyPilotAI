"""Release test gate: missing dependencies and skipped tests fail the build."""
from pathlib import Path
import unittest


def main():
    suite=unittest.defaultTestLoader.discover(str(Path(__file__).parent/'tests'))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if result.skipped:
        print('Release blocked: skipped tests are not passing tests.')
    return 0 if result.wasSuccessful() and not result.skipped else 1


if __name__ == '__main__':
    raise SystemExit(main())
