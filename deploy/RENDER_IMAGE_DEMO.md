# Release the PDF field review to the existing Render application

Keep https://policypilot-demo.onrender.com, its existing PostgreSQL, private
document bucket, login and storage credentials. This release adds review of
labeled fields, exact source citations, and conflicting-date handling. Poppler
reads embedded text and Tesseract handles pages flagged as unreadable. OCR pages
carry a verification warning. Inference remains disconnected.

## Build, verify and publish

Run this in a terminal with Docker daemon access, buildx, Python 3, Node.js 18
or later, Poppler (`pdfinfo`, `pdftotext`) and `prlimit` on `PATH`:

```sh
cd /home/aizen/Downloads/PolicyPilotAI_ollama
sh deploy/release_web.sh AIZEN-Hado
```

The wrapper regenerates the offline preview, runs the deployment and workspace
tests, then builds a fresh linux/amd64 API image. It reruns the full app gate
inside that image with networking disabled before invoking the private GHCR
publisher with a fresh timestamp tag. A failed step stops the release. Apply the
resulting digest to the existing service as described below.

The authoring sandbox cannot access the Docker daemon or resolve GitHub, GHCR
and the public application. Local checks use recovered dependencies whose
versions differ from the pinned image requirements, with a 10 ms event-loop
polling workaround. They do not replace the image checks in the wrapper.
See `artifacts/pdf-review-release-verification-20261119.json` for the latest
local counts, exact versions, scope and release blockers.

Local in-process ASGI verification uploaded all synthetic PDFs in SYN-C001
(8 documents, 10 pages) and SYN-C003 (7 documents, 8 pages), ran the production
native parser and local storage, checked exact citation offsets and original
PDF download bytes, recorded the current review acknowledgement and revoked
case access on deletion. Admission dates were respectively found and conflicting;
the image-only page was flagged for manual review. This used an in-memory SQL
database double and mocked cleanup scheduling. PostgreSQL, R2, session persistence,
physical deletion and a live deployment were not exercised by that smoke.

The OCR follow-up passed all 122 application tests against the pinned Python
requirements in a temporary Debian Bookworm Pod. An in-process HTTP smoke also
uploaded the actual image-only SYN-C003 bill, ran Tesseract 5.3.0, and checked the
page warning, both identifier citations, and the original PDF bytes. It used
local file storage and the test database adapter. The Pod was removed after
verification.

## Update the existing service

Enter the existing GitHub token only at its hidden prompt. Keep the package
private. Copy the printed full ghcr.io/.../policypilot-api@sha256:... reference.
In the existing Render service, open Settings -> Image Source -> Edit, replace
only the image reference, retain its GHCR credential, then deploy. Keep Docker
Command `sh /srv/deploy/render-start.sh web` and configure health path `/healthz`.
The read-back on 2026-11-19 found the health path empty, so verify this setting
when applying the release.
Do not create new services or databases.

Set `INFERENCE_BACKEND=disabled` and `PROCESSING_ENABLED=0`. Retain the existing
`DATABASE_URL`, `AUTH_MODE=session`, `APP_ORIGIN`, `PILOT_USER`,
`PILOT_PASSWORD_HASH`, `MODEL_OPERATOR`, `DOCUMENT_STORAGE`, `R2_ACCOUNT_ID`,
`S3_BUCKET`, `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` settings.
`MODEL_OPERATOR` remains the storage cleanup role.

Read-only provider verification on 2026-11-19 found the existing free Singapore
service running deployment `dep-dbuemn8m7kps73c6dn40`, created 2026-11-18, with
image digest `fcc8eca8bd074c0514afb3c547aebfac43bcf4c11d956a75cbe3ce2c32ca36a8`.
That deployment predates this PDF field release. No image was published and no
deployment was triggered during this verification.

## Verify the deployed release

Check that `/healthz` returns `status: ok` and `deployment_mode: pdf-field-review`,
then run both authenticated synthetic field reviews:

```sh
python deploy/smoke.py https://policypilot-demo.onrender.com --review-fields --case SYN-C001
python deploy/smoke.py https://policypilot-demo.onrender.com --review-fields --case SYN-C003
```

Each smoke verifies authentication, origin rejection, PDF upload, field review,
citation offsets, current-revision acknowledgement, original PDF download, case
deletion, and logout. SYN-C003 also checks real OCR, the original-document warning,
and citations for the scanned identifiers. Verify storage cleanup separately after
the smoke deletes each case.
Use the browser to check the source citations and conflicting admission dates.
A successful upload-only smoke without `--review-fields` does not establish that
the new field-review route is deployed.

To process up to 20 eligible deletion entries in one operator session, run:

```sh
python deploy/smoke.py https://policypilot-demo.onrender.com --cleanup-only
```

The command signs out and reports success when the queue is empty. Failed
deletions remain queued. Direct bucket verification is a separate check.

The historical compute retirement procedure below is retained for its audit
record; consult artifacts/render-storage-transition-access.json and
artifacts/serverless-retirement.json before repeating any removal.

## Remove the dedicated provider resources

Before updating the old application, set ENABLE_MODEL_CONTROL=0 if it is still
running, to disable its old browser button. Then, after the new deployment, run:

```sh
python deploy/remove_serverless.py --apply
```

This reads the locally recorded owned endpoint tjkkm5pkp7lrej, disables it if
necessary, verifies zero workers, deletes it and verifies absence. It removes
only templates with recorded project names. The dedicated registry credential is
removed only when no account resources remain that might reference it; otherwise
it is retained and the report says PARTIAL. There is no forced detach/cascade.
No model/data volumes, document buckets, database, unrelated resources or financial
records are deleted. Credentials come from owner-only deploy/cloud.env and are
never printed. Preview without --apply. Report: artifacts/serverless-retirement.json.
The saved owner-terminal report at 2026-11-15T16:47:34Z now records PASS: endpoint
absence and zero workers verified; endpoint tjkkm5pkp7lrej and its dedicated
registry credential cmwbwglxi000mqnesh01w6j76 deleted. No storage was deleted.
Retain this report; that successful endpoint cleanup does not need repeating.
It does not verify a new app deployment or deletion of runtime API keys/images.

After source backup and cloud cleanup are verified, remove only the known local
GPU tags (no force or global prune):

```sh
docker image rm policypilot-gpu:demo ghcr.io/aizen-hado/policypilot-gpu:v0.1.0-demo.20261110T202218Z
```

If another container/tag still references an image, keep it and inspect the
reference; never force removal or prune unrelated Docker images. The API image
and its shared layers must remain available. In GitHub profile Packages, the
retired policypilot-gpu package can be deleted through its Package settings;
retain policypilot-api and its registry credential. Provider Credentials can
revoke only the dedicated policypilot-demo-control and policypilot-demo-inference
keys after retirement. Keep the local setup key for the later Pod/storage setup.
These external package/key/image removals have not been performed by the
cloud endpoint cleanup command and must not be claimed complete.
The replacement persistent-volume/Pod plan is docs/PERSISTENT_STORAGE_PLAN.md;
no new volume, Pod, training job or recurring storage subscription is created here.
