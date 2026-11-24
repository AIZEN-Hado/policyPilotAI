 Live hosted release requirements

Use the existing Render application, PostgreSQL database and private document
bucket. Confirm the fresh API image passes the release gates. After deployment,
verify reviewer sign-in, synthetic PDF upload, embedded-text field review,
citations, original downloads, acknowledgement and deletion. The current pilot
uses disabled inference and flags image-only pages for manual inspection. Follow
the [PDF field review release guide](RENDER_IMAGE_DEMO.md) for the build, existing
service settings and authenticated smoke checks.

## Historical infrastructure decision, 2026-11-09

The [managed hosting plan](../docs/RENDER_RELEASE_PLAN.md) records the move from
the original VPS proposal to Render. The original hosting and inference proposal
below predates the current PDF field review release.

The user explicitly requires live uploads and private AI, not prepared demo results.
Provider preference: Hostinger for hosting, with Runpod considered for a later one-time fine-tuning job. Hostinger plan, region, domain and server access remain unknown. No Runpod workload or recurring inference expense has been authorized.
The existing application has not been deployed. A Sites project has been reserved,
but no version has been published. Reuse its identity in web-showcase/.openai/hosting.json;
do not create a second Site. Sites cannot host the Python/Ollama workload itself.

## Target flow

HTTPS web application -> authenticated Python API -> bounded document processing worker
-> local PDF extraction/OCR -> policy-scoped retrieval -> private Ollama inference
-> persistent records/files -> source-linked result in browser.

Never treat a model outage as permission to call a frontier cloud API. No real customer
claim processing until the required access, isolation and data-handling controls pass.

## Hosting decision needed

An always-on Linux server with persistent storage is required for the live Python/model
workload. GPU hosting is preferred for responsiveness; CPU-only feasibility and latency
must be measured with the chosen model. Do not promise a GPU size or monthly cost without
workload/model benchmarks and a current provider quote.

For Hostinger, target a VPS with administrative access, not an ordinary website-only plan.
Initially assess whether a small quantized model can meet pilot latency on the selected
VPS alongside OCR/database services. Fine-tuning on Runpod produces model artifacts; it
does not remove the need for ongoing inference compute. If CPU inference is inadequate,
present the separate recurring GPU option and its data-location/cost implications before
provisioning it. Three synthetic exemplar cases are not a sufficient basis for claiming
a properly fine-tuned insurance model.

The user needs to supply either:
- An existing server accessible through an already-configured SSH identity or provider
  connection, plus hostname and deployment domain; or
- A hosting budget and required region so an appropriate paid instance can be selected.

Do not request private SSH keys or provider tokens in chat. Use a connector or configure
credentials in the approved local/provider secret mechanism. Do not provision paid
resources until provider, cost and region are authorized.

## Credentials by deployment type

| Resource | Bundled on one private server | Managed service |
|---|---|---|
| PostgreSQL | Generate unique password and DATABASE_URL server-side | Secret PostgreSQL connection URL and required TLS settings |
| Documents | Private persistent volume; provider encryption and backup settings | Private bucket, region, endpoint; workload identity or scoped storage credentials |
| Ollama models | No inference API key; private network only | Private authenticated endpoint if separately hosted |
| Authentication | Configure selected identity provider and session secret | Issuer/client configuration and server-side secret as applicable |
| HTTPS | Domain/DNS access; certificate flow depends on network/provider | Provider domain configuration |
| Deployment | Authorized server/provider access | Hosting account connection |

A database URL alone cannot provide OCR or model inference. No OpenAI/Anthropic key is
needed or requested. Do not put database, storage or model-server credentials in the
browser or NEXT_PUBLIC/VITE-exposed environment variables.

## Known local constraints

- Docker CLI is installed, but this session cannot access the Docker daemon.
- Python application/rendering dependencies are not available in the active runtime.
- Earlier package installation failed because the environment could not resolve PyPI.
- The standalone synthetic PDF generator and its checks worked using local tools.
- No live backend address, deployment domain, hosting budget or server access is known.

These prevent an honest live end-to-end deployment claim today from this environment
without a hosting decision and access. They do not require switching to cloud inference.

## Minimum live release gates

1. Build and start on the target host; resolve supported dependency versions.
2. Authentication protects upload, records, source files and inference routes.
3. Upload limits, safe file identifiers, isolated parsing/OCR and per-case policy scope.
4. Persistent records/files and recoverable bounded jobs; no global shared-policy mixing.
5. HTTPS; database/model ports inaccessible from the public network.
6. Real test upload of a text PDF and an image-only PDF; confirm OCR/inference actually run.
7. Validate citation sources and explicit missing-evidence behavior; display human-review status.
8. Restart and retention tests; safe errors; no raw claim content in operational logs.
9. Verify no external model requests; record observed latency and resource usage.
10. Verify the live URL and report any remaining production limitations explicitly.

The larger production master plan remains applicable. A same-day restricted pilot is
not a certification of enterprise readiness or permission for anonymous sensitive uploads.
