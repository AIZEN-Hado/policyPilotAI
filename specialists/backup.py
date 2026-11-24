"""Publish a verified training archive from the Pod to a dedicated R2 bucket."""

import argparse
from datetime import datetime, timezone
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import sys

from .artifacts import verify_archive
from .execution import require_remote


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data/synthetic/specialists-v1'
REQUIRED_MEMBERS = {'span.pt', 'rank.pt', 'run.json', 'baseline.json',
                    'metadata.json', 'validation.json', 'reload.json'}


def approved_archive(archive):
    if not re.fullmatch(r'run-[a-f0-9]{32}\.tar\.gz', archive.name):
        raise ValueError('Select a training archive produced by specialists.run')
    fingerprint = verify_archive(archive)
    receipt_path = archive.with_name(archive.name.removesuffix('.tar.gz') + '.receipt.json')
    receipt = json.loads(receipt_path.read_text())
    manifest = fingerprint['manifest']
    if (receipt.get('stage') != 'train' or receipt.get('completed') is not True
            or receipt.get('archive_verified') is not True
            or receipt.get('artifact') != archive.name
            or receipt.get('artifact_sha256') != fingerprint['sha256']
            or manifest['metadata'].get('kind') != 'remote_specialist_run'
            or manifest['metadata'].get('trained') is not True
            or not REQUIRED_MEMBERS <= {item['path'] for item in manifest['files']}):
        raise ValueError('The archive needs a matching completed training receipt and both verified checkpoints')
    return fingerprint


def publish(client, bucket, archive, fingerprint):
    checksum, size = fingerprint['sha256'], fingerprint['bytes']
    key = f'specialists/sha256/{checksum}.tar.gz'
    try:
        # Conditional creation prevents overwriting an earlier object.
        with archive.open('rb') as source:
            if hashlib.file_digest(source, 'sha256').hexdigest() != checksum:
                raise ValueError('The archive changed after verification')
            source.seek(0)
            client.put_object(Bucket=bucket, Key=key, Body=source, ContentLength=size,
                              ContentType='application/gzip', StorageClass='STANDARD',
                              IfNoneMatch='*')
    except Exception as exc:
        # An existing object can be reused only after the same full read-back.
        if getattr(exc, 'response', {}).get('ResponseMetadata', {}).get('HTTPStatusCode') != 412:
            raise

    reply = client.get_object(Bucket=bucket, Key=key)
    digest, read = hashlib.sha256(), 0
    body = reply['Body']
    try:
        if reply.get('ContentLength') != size:
            raise ValueError('R2 object size differs from the verified archive')
        while chunk := body.read(1024 * 1024):
            read += len(chunk)
            if read > size:
                raise ValueError('R2 object exceeded the expected size')
            digest.update(chunk)
    finally:
        body.close()
    if read != size or digest.hexdigest() != checksum:
        raise ValueError('R2 object failed SHA-256 read-back verification')
    return {'bucket': bucket, 'key': key, 'sha256': checksum, 'bytes': size,
            'r2_readback_verified': True, 'recorded_at': datetime.now(timezone.utc).isoformat()}


def client_for(account):
    # Import only after the remote guard and local archive validation.
    import boto3
    from botocore.config import Config

    access_key = os.environ.get('SPECIALIST_R2_ACCESS_KEY_ID')
    secret = os.environ.get('SPECIALIST_R2_SECRET_ACCESS_KEY')
    if not (access_key and secret):
        if not sys.stdin.isatty():
            raise ValueError('Supply dedicated model-bucket credentials in the remote terminal')
        access_key = getpass.getpass('Model bucket access key ID (hidden): ')
        secret = getpass.getpass('Model bucket secret access key (hidden): ')
    if not access_key or not secret:
        raise ValueError('Model bucket credentials are missing')
    return boto3.client(
        's3', endpoint_url=f'https://{account}.r2.cloudflarestorage.com', region_name='auto',
        aws_access_key_id=access_key, aws_secret_access_key=secret,
        config=Config(connect_timeout=5, read_timeout=20, retries={'total_max_attempts': 1},
                      request_checksum_calculation='when_required',
                      response_checksum_validation='when_required'),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--account-id', required=True)
    parser.add_argument('--bucket', required=True, help='Dedicated private model bucket')
    args = parser.parse_args()

    archive = args.archive.absolute()
    require_remote(ROOT, DATA, archive.parent)
    if not re.fullmatch(r'[a-fA-F0-9]{32}', args.account_id):
        raise ValueError('Enter the R2 account ID as 32 hexadecimal characters')
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,61}[a-z0-9]', args.bucket):
        raise ValueError('Enter the dedicated model bucket name')
    document_bucket = os.environ.get('S3_BUCKET')
    if document_bucket and args.bucket == document_bucket:
        raise ValueError('Select the model bucket instead of the claim document bucket')
    fingerprint = approved_archive(archive)
    result = publish(client_for(args.account_id.lower()), args.bucket, archive, fingerprint)
    receipt = archive.with_name(archive.name + '.r2.json')
    temporary = receipt.with_suffix('.tmp')
    with temporary.open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    temporary.replace(receipt)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        raise SystemExit(f'Backup did not complete ({type(exc).__name__}). Verify the R2 copy before deleting training storage.') from None
