"""Write/read/delete a synthetic probe in the configured private staging bucket."""
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pilot.storage import get_storage, materialize


def safe_error(exc):
    # Do not print exception messages: SDK errors can contain URLs and account data.
    if isinstance(exc, ModuleNotFoundError):
        return 'Python dependency missing. Use a Python interpreter with boto3 installed.'
    if isinstance(exc, KeyError):
        return 'Required configuration variable missing. Reload deploy/cloud.env.'
    response = getattr(exc, 'response', {})
    if isinstance(response, dict):
        code = response.get('Error', {}).get('Code')
        hints = {
            'AccessDenied': 'AccessDenied: check bucket-scoped Object Read & Write permission and account.',
            'InvalidAccessKeyId': 'InvalidAccessKeyId: check the R2 Access Key ID.',
            'SignatureDoesNotMatch': 'SignatureDoesNotMatch: check the matching R2 secret/account and system clock.',
            'NoSuchBucket': 'NoSuchBucket: check the bucket name and account.',
            'RequestTimeTooSkewed': 'RequestTimeTooSkewed: synchronize the system clock.',
            'ExpiredToken': 'ExpiredToken: replace the expired credential.',
            'InvalidArgument': 'InvalidArgument: storage rejected a request parameter.',
            'NotImplemented': 'NotImplemented: storage does not support a request parameter.',
        }
        if code in hints:
            return hints[code]
        status = response.get('ResponseMetadata', {}).get('HTTPStatusCode')
        if isinstance(status, int) and 100 <= status <= 599:
            return f'Storage HTTP {status}; response details withheld.'
    name = type(exc).__name__
    if name == 'SSLError':
        # Classify locally; never emit raw TLS messages, URLs or credential data.
        detail = str(getattr(exc, 'kwargs', {}).get('error', exc)).upper()
        for marker, explanation in (
            ('CERTIFICATE_VERIFY_FAILED', 'certificate verification failed; check the CA bundle, system clock and any TLS-inspecting proxy'),
            ('NO_SUCH_FILE', 'certificate file unavailable; check AWS_CA_BUNDLE'),
            ('NO SUCH FILE', 'certificate file unavailable; check AWS_CA_BUNDLE'),
            ('HANDSHAKE_FAILURE', 'TLS handshake rejected; inspect endpoint and network/proxy compatibility'),
            ('WRONG_VERSION_NUMBER', 'TLS protocol mismatch; inspect proxy configuration'),
            ('UNEXPECTED_EOF', 'connection closed during TLS; inspect network/proxy behavior'),
        ):
            if marker in detail:
                return 'SSLError: ' + explanation + '.'
        return 'SSLError: unclassified TLS failure; certificate verification remains enabled.'
    if name in {'EndpointConnectionError','ConnectTimeoutError','ReadTimeoutError','SSLError','ProxyConnectionError'}:
        return f'{name}: check network, DNS, proxy and TLS configuration.'
    if name in {'NoCredentialsError','PartialCredentialsError'}:
        return 'Storage credentials missing or incomplete.'
    if isinstance(exc, ValueError):
        return 'Configuration or document-integrity validation failed.'
    return 'Local or SDK error; details withheld to protect credentials.'


def main():
    if os.environ.get('DOCUMENT_STORAGE') != 'r2':
        raise SystemExit('Load the R2 configuration first. This probe only supports R2.')
    try:
        storage = get_storage()
    except Exception as exc:
        raise SystemExit('R2 configuration failed: ' + safe_error(exc)) from None
    did = uuid.uuid4()
    data = b'%PDF-1.4\nPolicyPilot synthetic storage connectivity probe.\n'
    stage = 'upload'
    failure = None
    try:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'probe.pdf'
            source.write_bytes(data)
            storage.put(did, source)
            stage = 'download/integrity'
            with materialize(storage, did, len(data), hashlib.sha256(data).hexdigest(), 1024):
                pass
    except Exception as exc:
        failure = f'R2 {stage} failed: {safe_error(exc)}'
    finally:
        try:
            storage.delete(did)
        except Exception as exc:
            print('R2 cleanup failed: ' + safe_error(exc), file=sys.stderr)
            print(f'If present, remove documents/{did}.pdf from the staging bucket.', file=sys.stderr)
            if failure is None:
                failure = 'R2 probe did not complete cleanup.'
    if failure:
        raise SystemExit(failure)
    print('PASS: R2 write, verified read and delete request. Bucket privacy/policies need separate review.')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('R2 probe failed. Check credentials, bucket and network; secrets were not printed.')
