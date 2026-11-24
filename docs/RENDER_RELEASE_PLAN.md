# Managed hosting release plan — 2026-11-09

## Agreed direction and scope

Build an access-restricted side-project showcase with live PDF uploads, local
OCR and open-weight inference. Start with synthetic documents, no frontier-model
API fallback, no fine-tuning and no paid provisioning in this phase. NixOS is the
development host; Render is the proposed runtime. Keep the company domain separate
initially. This pilot is one shared workspace, not tenant-isolated B2B SaaS.

Alternatives considered: Vercel for the UI plus Render for processing adds an
origin and another deployment; a VPS gives more network control but the user has
set it aside. Prefer one Render web origin for the current UI and API.

## Phase 1 — local development and honest checks (current)

- Add revision-pinned Nix shell definition, with channel fallback documented.
- Include Python API dependencies, PDF tools and English/Hindi OCR data.
- Add a readiness command that treats skipped tests as failure.
- Record dependency/network/daemon restrictions rather than treating syntax checks
  as evidence that the entire application works.
- Exit: resolve the shell, retain its lock file, run all existing tests without
  skips and verify real OCR language availability. Container release checks follow.

## Phase 2 — storage and Render compatibility

2026-11-10: local/AWS S3 adapters, API/worker integration, checksum verification and
durable cleanup implemented. See `pilot/STORAGE.md`. Real storage/database integration
tests remain outstanding; phase 2 is not yet accepted as complete.

API and worker currently share a local Docker volume. Render disks cannot be
mounted by multiple services. Introduce an object-storage interface with a local
adapter for development and an S3-compatible adapter for hosting. Proposed hosted
storage: a private AWS S3 bucket; choose region after agreeing data location and
Render region. Do not silently imply that all processing happens in India.

- Keep UUID object keys and document hashes; never use filenames as storage paths.
- Authenticate downloads through the API; do not expose a public bucket or durable
  public links. Enforce limits while streaming uploads, before model processing.
- API writes objects; worker fetches into bounded temporary files and cleans up on
  success and failure. No policy text, filenames or signed URLs in application logs.
- Handle database/object-write partial failures and abandoned upload cleanup.
- Delete active files and records together with retryable cleanup; document how
  versions and backups expire rather than promising instant erasure everywhere.
- Scope bucket credentials to the project prefix; enable encryption at rest,
  block public access, require TLS and define retention/lifecycle rules.
- Test upload/download/delete, duplicate uploads, storage outages, partial writes,
  worker retries, object authorization and size limits against a local S3 test service.

Exit: API and worker work without a shared filesystem, including failure paths.

## Phase 3 — authentication and managed deployment

The current API trusts a secret header injected by Caddy. Render does not provide
that Caddy login automatically. Do not deploy the API directly and weaken its
middleware to make it work.

- Replace proxy-dependent browser identity with application-managed, invite-only
  pilot login: password hashes, secure HttpOnly host-only session cookie, CSRF/origin
  checks, logout, session expiry, login throttling and no public registration.
- Use server-side reviewer identity for audit events. A shared pilot login must
  remain explicitly labeled; customer SaaS needs per-user and tenant authorization.
- Supply Render configuration for a public UI/API, background worker, managed
  PostgreSQL and private Ollama service. Run migrations as a controlled release step.
- Use Render's port and health-check conventions without exposing private records.
- Extend model configuration to allow only the explicitly configured private
  service hostname; do not accept arbitrary model URLs from browser requests.
- Keep model weights on the model service's persistent disk. Provision weights
  separately from claim processing; disable Ollama cloud features and tools.
- Set resource/concurrency/page limits, model digest, readiness and queue recovery.
- Review private-network access and outbound traffic. Render private networking is
  not equivalent to the current Compose network with `internal: true`; do not claim
  infrastructure-enforced no-egress until an enforceable control is verified.

Exit: deployable configuration validated, login bypass checks pass, and a measured
instance/cost proposal is ready. No account keys or spending required before that.

## Phase 4 — end-to-end evidence and security review

Run in disposable staging using all three synthetic bundles:

1. Browser login, create case, upload, queue, OCR, inference, citations, review and
   deletion. Verify readable native PDFs and the actual scanned page.
2. Reject unauthenticated and cross-origin actions, forged identity, invalid object
   IDs, oversized/corrupt/encrypted PDFs and unauthorized document downloads.
3. Test document prompt injection; no tool execution or external model fallback.
   Exact quotes alone do not prove the finding is supported; review entailment.
4. Stop worker/model/storage mid-job; verify bounded retries, useful error states,
   restart recovery and no duplicate review events or stranded documents.
5. Inspect logs and browser requests for claim text/secrets; verify deletion and
   retention; rehearse database/object backup restoration together.
6. Lock dependencies, scan application/container dependencies and inspect resource
   exhaustion behavior. Record unresolved findings and severity.
7. Measure cold/warm latency, OCR accuracy, queue capacity and peak memory. Select
   paid compute only from these measurements. CPU feasibility is not guaranteed.

Exit: no unresolved critical/high findings for the pilot scope; evidence report
includes failures and limitations. Tests reduce risk, never certify zero vulnerabilities.

## Phase 5 — restricted hosted showcase

Confirm provider budget and regions, then configure provider secrets and deploy.
Start on an available `onrender.com` name with synthetic documents and invited
reviewers. Verify HTTPS, health, login, live processing and restore on the target.
Add a custom domain later if desired. Real claims require a separate privacy,
retention, consent, contractual and access-control review before onboarding.

## Configuration inventory (do not paste values into chat)

| Setting | Source / purpose |
| --- | --- |
| DATABASE_URL | Render internal PostgreSQL connection, server-side only |
| APP_ORIGIN | Exact HTTPS address for session/origin checks |
| Session secret and initial reviewer credential | Generated secrets; hash passwords |
| S3 bucket, region, endpoint | Private storage configuration; endpoint not browser-controlled |
| Storage access credentials | Scoped service credentials in provider secret settings |
| OLLAMA_BASE_URL | Explicit private model service address |
| OLLAMA_MODEL / model digest | Validated open-weight model artifact |

These are target settings; S3 is implemented but not integration-tested, and sessions
are not yet implemented. No OpenAI or other frontier-model API key is required. Hosting providers still
process/store data: open-weight inference does not make hosted deployment fully local.

## Reference constraints

- [Render disks](https://render.com/docs/disks): ephemeral filesystem by default;
  persistent disks have service attachment and deployment limitations.
- [Render private networking](https://render.com/docs/private-network): same-region,
  same-workspace services; review environment isolation for the chosen plan.
- [Render Blueprint specification](https://render.com/docs/blueprint-spec): validate
  final service configuration before provisioning.
- [NixOS Docker](https://wiki.nixos.org/wiki/Docker): host daemon configuration.
