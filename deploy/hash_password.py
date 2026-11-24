"""Generate a pilot password hash with a hidden prompt; never store the password."""
import getpass
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pilot.auth import password_hash


def main():
    password=getpass.getpass('New shared pilot password (16+ characters): ')
    if password != getpass.getpass('Confirm password: '):
        raise SystemExit('Passwords differ. Nothing saved.')
    try:
        encoded=password_hash(password)
    except ValueError as exc:
        raise SystemExit(str(exc))
    print('Set PILOT_PASSWORD_HASH in the hosting provider secret settings:')
    print(encoded)
    print('This is a password hash. Keep it private. No files changed.')


if __name__ == '__main__':
    main()
