# Document storage — implementation status

2026-11-10 update: `DOCUMENT_STORAGE=r2` now supports Cloudflare's standard account
endpoint, region `auto` and default at-rest encryption without AWS-only headers.
See [cloud setup](../deploy/CLOUD_SETUP.md). R2 unit tests pass; live access is not
yet configured. The AWS-only restrictions below apply to `DOCUMENT_STORAGE=s3`.

`DOCUMENT_STORAGE=local` (default) preserves existing UUID filenames under DATA_DIR.
`DOCUMENT_STORAGE=s3` uses the AWS SDK credential chain, AWS_REGION and S3_BUCKET.
Objects are stored at `documents/<uuid>.pdf` with AES256 server-side encryption.
No public ACL or browser-facing storage URL is created. The bucket still needs
Block Public Access, a TLS-only policy, scoped permissions and retention settings.
The SDK uses the official regional AWS endpoint; custom S3-compatible endpoints
are not implemented in this phase.

Configure the same backend/bucket on the API and worker. Changing backends does
not copy existing documents: use a fresh synthetic workspace or a separately
verified migration. Do not change the backend while cleanup jobs remain pending.
Run `python -m pilot.migrate` before running this version: migration 002 adds the
cleanup queue. No secrets should be committed or pasted into chat.

Uploads stream to temporary files with the existing size limit. Before storing
an object, the API commits a durable cleanup intent. The transaction that attaches
the document locks that intent, writes the object, inserts the document record and
removes the intent. On failure, the worker can remove the abandoned object after
one hour. Cleanup checks for a document reference before deleting, including when
the API could not determine whether its commit succeeded.

Case deletion revokes API access by deleting its database records and queues
object removal in the same transaction. The worker retries failed object deletion
after five minutes. If the worker is offline, physical removal remains pending.
API responses/UI explicitly describe queued removal. Bucket versions and backups
have separate retention; an ordinary S3 delete does not erase historical versions.

Worker extraction and downloads use bounded temporary copies, checking byte count
and SHA-256 against the database. Temporary copies are removed on processing
failure and after download responses, including response exceptions.

## Verification and remaining release gates

- 13 storage/cleanup tests cover local round trips, bounded reads, integrity,
  temporary cleanup, UUID validation, S3 call parameters, interrupted reads,
  referenced-object protection and cleanup retries.
- S3 calls and cleanup SQL interactions are mocked. These tests do not prove AWS
  policy correctness, PostgreSQL transaction/concurrency behavior or network recovery.
- Real S3/compatible-service integration, database crash tests and API transaction
  tests remain required. Existing API tests are skipped in this environment because
  dependencies are missing. No production readiness claim is made.
- Deployments using S3 need outbound access to S3; the old Compose internal-only
  network is intentionally unchanged and cannot serve as the S3 deployment manifest.
- Storage SDK dependencies are directly pinned, not transitively locked/audited yet.
- New hosted login and Render service configuration are not implemented here.
- The old archive in artifacts predates these changes; do not deploy that archive
  expecting this storage implementation.

SDK parameters checked against [AWS PutObject documentation](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/put_object.html).
