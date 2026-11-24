"""Collect staging credentials locally, without printing them or contacting providers."""
import getpass
import os
from pathlib import Path
import re
import shlex


def main():
    destination = Path(__file__).resolve().parent / 'cloud.env'
    if destination.exists():
        raise SystemExit('deploy/cloud.env exists; refusing to overwrite credentials.')
    account = input('Cloudflare account ID: ').strip()
    if not re.fullmatch(r'[a-fA-F0-9]{32}', account):
        raise SystemExit('Expected a 32-character hexadecimal Cloudflare account ID.')
    bucket = input('Private staging R2 bucket name: ').strip()
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,61}[a-z0-9]', bucket):
        raise SystemExit('Use a 3–63 character bucket name with lowercase letters, digits and hyphens.')
    access = getpass.getpass('R2 Access Key ID (hidden): ').strip()
    secret = getpass.getpass('R2 Secret Access Key (hidden): ').strip()
    runpod = getpass.getpass('Runpod API key (hidden; Enter to configure later): ').strip()
    if not access or not secret:
        raise SystemExit('R2 credentials cannot be empty.')
    values = {'DOCUMENT_STORAGE':'r2', 'R2_ACCOUNT_ID':account,
              'S3_BUCKET':bucket, 'AWS_ACCESS_KEY_ID':access,
              'AWS_SECRET_ACCESS_KEY':secret, 'AWS_EC2_METADATA_DISABLED':'true'}
    if runpod:
        values['RUNPOD_API_KEY'] = runpod
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as output:
        output.write('# Private local credentials. Do not commit or share.\n')
        for name, value in values.items():
            output.write(f'export {name}={shlex.quote(value)}\n')
    print('Saved deploy/cloud.env with owner-only permissions. No provider resources were created.')


if __name__ == '__main__':
    main()
