"""Private document adapters. Keys contain UUIDs, never uploaded filenames."""
from contextlib import contextmanager
import hashlib
import os
import re
from pathlib import Path
import shutil
import tempfile
import uuid


def key(document_id):
    return str(uuid.UUID(str(document_id))) + '.pdf'


class LocalStorage:
    def __init__(self, root):
        self.root = Path(root)

    def put(self, document_id, source):
        self.root.mkdir(parents=True, exist_ok=True)
        destination = self.root / key(document_id)
        with tempfile.NamedTemporaryFile(dir=self.root, delete=False) as output:
            temp = Path(output.name)
            try:
                with open(source, 'rb') as stream:
                    shutil.copyfileobj(stream, output)
                output.flush()
                os.fsync(output.fileno())
                os.replace(temp, destination)
            finally:
                temp.unlink(missing_ok=True)

    def read_into(self, document_id, output, limit):
        with (self.root / key(document_id)).open('rb') as source:
            copy_bounded(source, output, limit)

    def delete(self, document_id):
        (self.root / key(document_id)).unlink(missing_ok=True)


def copy_bounded(source, output, limit):
    total = 0
    while chunk := source.read(65536):
        total += len(chunk)
        if total > limit:
            raise ValueError('Stored document exceeds size limit')
        output.write(chunk)


class S3Storage:
    def __init__(self, client, bucket, prefix='documents/', aws_encryption=True):
        self.client, self.bucket, self.prefix = client, bucket, prefix
        self.aws_encryption = aws_encryption

    def put(self, document_id, source):
        with open(source, 'rb') as stream:
            self.client.put_object(Bucket=self.bucket, Key=self.prefix + key(document_id),
                                   Body=stream, ContentType='application/pdf',
                                   **({'ServerSideEncryption':'AES256'} if self.aws_encryption else {}))

    def read_into(self, document_id, output, limit):
        response = self.client.get_object(Bucket=self.bucket, Key=self.prefix + key(document_id))
        body = response['Body']
        try:
            if response['ContentLength'] > limit:
                raise ValueError('Stored document exceeds size limit')
            copy_bounded(body, output, limit)
        finally:
            body.close()

    def delete(self, document_id):
        self.client.delete_object(Bucket=self.bucket, Key=self.prefix + key(document_id))


def r2_endpoint(account_id):
    if not re.fullmatch(r'[a-fA-F0-9]{32}', account_id):
        raise ValueError('R2 account ID must contain 32 hexadecimal characters')
    return f'https://{account_id.lower()}.r2.cloudflarestorage.com'


def get_storage():
    backend = os.environ.get('DOCUMENT_STORAGE', 'local')
    if backend == 'local':
        from . import config
        return LocalStorage(config.DATA_DIR)
    if backend not in {'s3', 'r2'}:
        raise ValueError('Unsupported document storage')
    # AWS SDK credential chain: environment or workload credentials, never browser input.
    import boto3
    from botocore.config import Config
    options = {}
    if backend == 'r2':
        options = {'endpoint_url':r2_endpoint(os.environ['R2_ACCOUNT_ID'])}
    client = boto3.client('s3', region_name='auto' if backend == 'r2' else os.environ['AWS_REGION'],
                          **options,
                          config=Config(connect_timeout=5, read_timeout=30,
                                        request_checksum_calculation='when_required',
                                        response_checksum_validation='when_required',
                                        retries={'mode': 'standard', 'max_attempts': 2}))
    return S3Storage(client, os.environ['S3_BUCKET'], aws_encryption=backend != 'r2')


@contextmanager
def materialize(storage, document_id, expected_size, expected_hash, limit):
    """Verify bytes before exposing them to the parser or browser; always clean up."""
    with tempfile.TemporaryDirectory(prefix='claim-document-') as directory:
        path = Path(directory) / 'document.pdf'
        with path.open('xb') as output:
            os.chmod(path, 0o600)
            storage.read_into(document_id, output, limit)
        if path.stat().st_size != expected_size:
            raise ValueError('Stored document size mismatch')
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
            raise ValueError('Stored document checksum mismatch')
        yield path
