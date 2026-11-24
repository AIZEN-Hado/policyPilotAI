# Hostinger live pilot: operator runbook

Status: source prepared, not deployed. Docker/image build, full API integration, browser
QA and real model inference must pass on the target VPS before calling this live-ready.

## Deployment scope

A single password-protected workspace, suitable initially for synthetic-data testing.
All authenticated users share every case. This is not multi-tenant enterprise SaaS.
It uses FastAPI, PostgreSQL, a durable DB-backed single-worker queue, Poppler, local
Tesseract OCR, lexical excerpt retrieval and Ollama. No frontend database/API keys.
The new `pilot/` application is separate from the legacy Streamlit/global-FAISS app.

The first frontend uses dependency-free HTML/CSS/JS served by FastAPI. This avoids a
separate Node runtime and cross-origin API configuration on the pilot VPS. The planned
Next.js migration is deferred; the UI has actual upload and assessment behavior.

## Needed from the owner

- Hostinger **VPS** plan, RAM/CPU, region and Linux version.
- Server hostname/IP and configured SSH username/access method (no private key in chat).
- Domain/subdomain whose DNS can point to the VPS.

No separate database subscription is required. `configure.py` generates PostgreSQL and
internal proxy credentials on the server. It prompts for a login password without echo.
No Runpod or frontier-model key is needed for CPU inference on this VPS.

The default model is a small quantized `qwen2.5:3b` pilot baseline, not a fine-tuned
insurance model. Model context is 8K and generation bounded. The proposed 6 GB model
container limit is a test starting point, not measured capacity. Allow additional RAM
for OCR/API/database and the OS. Benchmark the actual VPS; do not promise production
latency or concurrency. A 16 GB VPS is a reasonable *test candidate*, not a guarantee.

## Install and configure

Use a fresh supported Linux VPS with Docker Engine and Compose installed through their
official instructions. Do not reimage a server that contains existing workloads.
Copy this repository to a dedicated directory on the server, excluding real data,
local secrets, `.git`, and evaluation ground truth. Include synthetic PDFs for smoke tests.

Point the domain's A record at the VPS. Remove/fix an incorrect AAAA record. Allow 80/443
and restrict SSH to the operator's IP. Never publish 5432, 8000 or 11434. Retain access to
the provider console while changing firewall rules.

From the repository root:

```sh
python3 deploy/configure.py
bash deploy/start.sh
```

The script builds the app, downloads model files in a separate provisioning container,
and starts the private runtime. Only provisioning and the HTTPS proxy have external
network access. Model/API/worker/database services use an internal Compose network.
Model initialization shares only the model volume, not claim documents. `start.sh`
stops a running worker/model before provisioning; use a maintenance window for updates.

Check status from `deploy/`:

```sh
docker compose ps
docker compose logs --tail=40 api worker
```

Do not post raw logs or environment dumps publicly. Open your HTTPS domain and enter the
pilot credentials. Test with synthetic documents first. A Sites address was reserved in
a prior step but is not required for this Hostinger deployment and was never published.

## Required live verification

```sh
python3 deploy/smoke.py https://YOUR-ACTUAL-DOMAIN --case SYN-C001
python3 deploy/smoke.py https://YOUR-ACTUAL-DOMAIN --case SYN-C003
```

Each test uses real uploads and inference, prompts securely for the password, checks
unauthenticated rejection and Origin enforcement, and retains a case for visual review.
The scan test requires at least one actual OCR page. No prepared answers are substituted.
A citation-valid draft is not proof of correct policy interpretation; inspect the results.

Also verify:
- Restart worker during extraction: the interrupted case is requeued after restart.
- Restart the stack: uploaded documents and review events persist.
- Invalid/oversized PDFs and duplicate uploads are rejected.
- Model unavailable: case fails clearly, no cloud fallback or fabricated outcome.
- Browser mobile/desktop layout, keyboard access, upload/retry/delete and source links.
- No public database/model ports; worker/model containers lack external routing.
- Dependency/image vulnerability scans and transitive dependency lock/digest capture.
- OCR and model speed/memory on the selected VPS; set usage expectations accordingly.

If any gate fails, keep the site restricted and fix it before sharing it as working.

## Backup, restore and deletion

`bash deploy/backup.sh` pauses the app during a consistent database/file snapshot and
restarts it on exit. Backup files are mode-restricted but **not encrypted by the script**.
Encrypt and copy them to approved off-host storage. Also protect `deploy/.env` and
record deployed source commit, image digests and model digest. Do not commit backups.

Restore into an isolated empty staging stack first. Start only its database, restore
with `pg_restore -U pilot -d pilot --clean --if-exists`, then restore the document archive
through an app container mounted on the documents volume. Never point this rehearsal
at the running pilot. Apply migrations, start the stack and verify records, original
files and OCR results. Record recovery time. Old backups can contain deleted cases;
record deletions operationally and reapply them after a restore. Backup expiry and
legal holds require an explicit policy before real personal data is accepted.

For rollback, retain the previous source/image IDs, stop processing, back up, deploy the
prior compatible image and run a verification request. Do not roll back across an
incompatible schema change without the rehearsed database/files recovery procedure.

## Known limitations / production follow-up

- Shared Basic Auth, no per-user RBAC, SSO, tenant isolation, session revocation UI or
  persistent login throttling. Limit pilot access; add identity infrastructure before
  onboarding multiple organizations or real customer claims.
- App DB role owns its schema (not superuser); full migration/runtime role separation
  and an independently protected audit store remain outstanding.
- PDF signature/size limits are not malware scanning. Parsing is resource-bounded and
  container-isolated, but specialist scanning/sandbox hardening remains necessary.
- OCR uses English/Hindi language packs; neither medical nor Hindi accuracy is validated.
- Keyword retrieval can omit governing clauses. Context truncation is explicit. No
  authoritative policy registry, rule engine, embeddings, reranker or payout computation.
- Citation quotes are checked against supplied text, not for semantic entailment.
- Fixed model tags can change; capture the downloaded digest before release.
- Volumes are not application-encrypted. Verify hosting storage encryption, backup
  encryption, access and residency before sensitive data. No compliance claim is made.
- API/Docker/browser tests could not execute in the authoring sandbox; see verification
  record. Image tags and direct dependency versions are pinned, but transitive hashes
  and vulnerability validation are still a deployment gate.
