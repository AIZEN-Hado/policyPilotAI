# PolicyPilot: Indian B2B health-claims platform

Date: 2026-11-07. Status: proposed master plan, not an approved implementation specification. No production readiness or model accuracy is claimed. Estimates are planning ranges, not commitments.

## 1. Product vision

Build a private claims workspace that turns fragmented insurance documents into a verifiable case: the right policy, verified facts, reproducible calculations, evidence-backed recommendations, accountable human decisions, and understandable communication to the policyholder.

Interpretation of “vision beast”: ambitious product scope plus visual document intelligence. The initial scope is document understanding, not medical diagnosis from radiology images or autonomous fraud detection.

Initial buyer: one Indian TPA or insurer. Initial workflow: retrospective hospitalization reimbursement review for a small, named set of policy products. Cashless support follows after reliability, integration, and turnaround requirements are validated. A hospital-side preparation product would be a separate scope decision.

North-star metric: median reviewer time per completed case, subject to quality and consumer-outcome constraints. Track unsupported deductions, correction rates, complaints, and results by language alongside speed. Never optimize for rejection volume.

## 2. Release ladder

R0: polished synthetic showcase, no real customer data.
R1: secure internal case/document workspace, manual review authoritative.
R2: assisted assessments in shadow mode on authorized retrospective cases.
R3: paid production pilot for supported products, mandatory human authorization.
R4: enterprise integrations, cashless workflows, selected regional languages.
R5: larger-scale deployments and carefully scoped additional insurance lines.

The showcase uses separate storage and credentials. It must never be a public gateway into a customer's production environment.

## 3. Product surfaces

Public website: product story, synthetic walkthrough, deployment/privacy explanation, contact/demo request, truthful capability statements. No unsupported compliance badges or invented performance claims.

Staff workspace: role-aware work queue, assignments, deadlines, upload intake, document viewer, facts, assessments, reviews, exports, audit trail, organization settings.

Review screen: original document at left; extracted facts, rules, and findings in the centre; reviewer actions at right. Every extracted fact and finding opens a page/bounding box or structured source record. Show original and corrected values with provenance. Show uncertainty per field rather than a decorative overall confidence percentage.

Policyholder portal: status, next action, received documents, clear outcome explanations, secure clarification channel, authorized caregiver access. English/Hindi first; one additional pilot language after evaluation. INR, lakh/crore formatting, explicit date formats, IST display with UTC storage. Keyboard navigation, readable contrast, responsive layouts, low-bandwidth states.

Administration: SSO, roles, access review, supported policy products, approved rules, retention, exports, deployment health. Business reviewers cannot edit system security settings; system administrators do not receive routine claim access merely by holding that role.

## 4. Architecture and technology decisions

Use a modular FastAPI backend and separate worker processes, not a large microservice estate. Keep business rules independent of model and storage adapters.

| Layer | Proposed baseline | Boundary |
|---|---|---|
| Web | Next.js/React, TypeScript | Custom UI; no sensitive data in public caches or analytics |
| API | FastAPI, versioned OpenAPI contracts | Authoritative authorization and business validation |
| Identity | Customer OIDC; self-hosted Keycloak when required | MFA, session expiry, service identities |
| Records | PostgreSQL, SQLAlchemy, Alembic | Tenant-scoped transactions and schema migrations |
| Retrieval | PostgreSQL full-text plus pgvector | Policy/tenant scope enforced in queries; exact vector search initially |
| Files | Private object storage, S3 in selected Indian region as reference deployment | Encrypted originals, derivatives, short-lived scoped access |
| Jobs | Celery/RabbitMQ; PostgreSQL job state and transactional outbox | At-least-once execution, idempotent stages, bounded retries |
| OCR | Local PaddleOCR candidate; existing PDF extraction retained where reliable | Benchmark each supported script/document class |
| Embeddings | MiniLM baseline; BGE-M3 candidate | Local processing; choose by measured retrieval quality |
| Generation | Ollama initially, local models only | Schema-constrained extraction/explanation; no unrestricted tools |
| Serving upgrade | Evaluate a higher-throughput server only after load evidence | Do not couple business logic to a serving API |
| Operations | Containers, private metrics, redacted structured logs | Immutable releases, readiness, recovery, alerts |

Primary deployment recommendation: dedicated customer environment in an agreed Indian region. Keep a tenant-aware schema even in dedicated deployments. Customer-controlled VPC/on-premises is an enterprise option; it needs separate installation, upgrade, support, and recovery qualification. Shared SaaS infrastructure is a later optimization, not a launch dependency.

GPU size is deliberately undecided until the benchmark: evaluate quantization, context, batch size, peak concurrency, OCR/model coexistence, and p95 latency. The development 4 GB GPU is not a production sizing assumption. Do not buy hardware based on parameter count alone.

## 5. Data model

Core entities: organization, user membership, role/permission, claimant/member, authorized representative, policy product/UIN, wording version, schedule, endorsement, coverage period, claim, document, document version, page, extracted fact, bill line item, policy clause, approved rule version, evidence link, assessment run, calculation line, review, clarification, status event, job, audit event, retention/legal hold.

Every sensitive entity carries organization scope and ownership/assignment where relevant. Composite constraints prevent cross-organization references. Financial values use integer paise or precise decimals and explicit currency. Dates distinguish incident/admission/discharge/coverage dates from timestamps.

Every assessment records the document hashes, verified fact snapshot, policy/rule versions, retrieval configuration, embedding/model digests, prompt version, output, and reviewer action. Preserve enough evidence to explain or replay a calculation; do not promise bit-identical LLM regeneration.

Originals are immutable. Corrections create revisions. Reassessment creates a new run and leaves earlier outcomes intact. A changed fact marks dependent assessment results stale. Prior utilization is an external verified input until integrated; do not infer the remaining sum insured from a single policy PDF.

## 6. Visual document intelligence

Processing stages:
1. Authorized upload session, size/page/type checks, quarantine, malware scanning, content hash.
2. Safe PDF/image parsing in isolated workers with memory/time limits; no arbitrary network fetches.
3. Page classification, rotation/deskew, text-layer quality assessment.
4. Native extraction for usable text; local OCR for scanned or mixed pages.
5. Layout reconstruction: headings, tables, rows, columns, footnotes, reading order, bounding boxes.
6. Document classification: schedule, wording, endorsement, bill, discharge summary, receipt, report.
7. Typed extraction with source spans: identifiers, dates, amounts, procedures, line items.
8. Cross-document checks: name/member consistency, dates, totals, missing pages, duplicate hashes.
9. Reviewer verification of critical uncertain fields before dependent calculations.

Evaluate a local vision-language model only for cases the baseline cannot handle. It must cite page regions, obey the same access limits, and be judged on a separate held-out set. It must never silently replace illegible text with a guess. Store uncertainty and the original image crop. Handwriting is manual-review territory until independently validated.

Visual similarity and duplicate checks can raise review flags. They do not establish fraud. Medical image diagnosis, facial identification, and document-authenticity certification are outside scope.

## 7. Policy and assessment logic

Resolve the insured member, policy schedule, product UIN, coverage period, wording revision, and endorsements before retrieval. Missing or conflicting policy identity blocks definitive assessment.

Clause segmentation preserves headings, definitions, exclusions, exceptions, and cross-references. Retrieve within the resolved policy and organization; combine keyword and semantic retrieval, then evaluate reranking only if it improves held-out results. Keep governing wording distinct from explanatory summaries.

A policy specialist approves structured rule packs with effective dates and golden calculation cases. Model-extracted rules remain drafts until approved. Rules may represent copayments, deductibles, sublimits, room categories, waiting periods, continuity, restoration and utilization; none are universal defaults.

Calculate using approved rules with explicit ordering, rounding, provenance, and missing-input states. A monetary result needs verified inputs. Language models explain a computed result and summarize evidence; they cannot invent applicable rules or override calculations.

States distinguish operational progress from assessment findings. Example workflow: draft -> documents_processing -> verification_required -> ready_for_assessment -> assessing -> review_required -> authorized -> communicated. A failed technical job does not become a claim rejection. An authorized result requires a separate reviewer action and revision-safe transition.

No autonomous claim repudiation. Regulated decision authorities and communication responsibilities must be mapped with the customer before launch.

## 8. API contract outline

| Endpoint | Behavior |
|---|---|
| GET /v1/me | Verified identity, memberships, permissions |
| POST /v1/claims | Create with idempotency key |
| GET /v1/claims | Scoped, bounded cursor pagination |
| GET /v1/claims/{id} | Authorized case details |
| POST /v1/claims/{id}/upload-sessions | Bounded, expiring document upload grant |
| POST /v1/documents/{id}/complete | Verify uploaded object and queue quarantine/processing |
| GET /v1/documents/{id}/pages/{page} | Authorized page/overlay access |
| GET/PATCH /v1/claims/{id}/facts | Retrieve or revise facts with optimistic concurrency |
| POST /v1/claims/{id}/assessments | 202 with run/job ID; idempotent submission |
| GET /v1/jobs/{id} | Persistent state and safe failure reason |
| GET /v1/assessments/{id} | Findings, calculation, provenance, evidence |
| POST /v1/assessments/{id}/reviews | Authorized, version-checked review action |
| POST /v1/claims/{id}/clarifications | Create tracked request with appropriate recipient access |
| GET /v1/claims/{id}/timeline | Audience-filtered events |
| GET /v1/policies/{id}/versions | Authorized policy inventory |

Use stable error codes, request IDs, rate limits and upload quotas. Tenant context comes from verified membership, never arbitrary request data. Workers revalidate resource scope and permitted purpose. Signed callbacks/integrations need replay protection and idempotency. Public links never expose raw storage keys.

## 9. Privacy, security and India-specific governance

Local OCR/embedding/generation, disabled Ollama cloud features, model allowlists, no internet tools, deny-by-default worker egress, approved offline artifact provisioning, no cloud fallback. Verify with network tests rather than a marketing assertion.

Private storage and databases; TLS; customer-specific key access where agreed; encrypted backups; short-lived object access; minimal prompts; no payloads in telemetry; protected queues carrying IDs rather than full medical documents. Embeddings and OCR outputs receive the same protection as originals.

RBAC plus assignment/ownership, MFA/SSO, scoped service identities, tenant-safe database roles, row-level security as defense in depth, audit of reads/downloads/changes, approved time-limited support access. Test cross-tenant attacks at API, retrieval, files, caches, jobs and exports.

Audit events are append-only to the application role, with an independently retained protected export for stronger tamper evidence. Separate audit retention from clinical document retention. Define legal holds, deletion of derived artifacts, backup expiry and restore-time reapplication of deletion records.

Before processing real claims: establish processing roles and contractual instructions, permitted purposes, notice/lawful basis, representative access, subprocessors, hosting region, incident handling and retention. Map applicable DPDP commencement dates and insurance-sector obligations with qualified customer/legal owners; do not equate Indian hosting with complete compliance.

No customer training reuse by default. Development uses synthetic or properly authorized data; pseudonymized data remains protected. Notifications contain minimal metadata and a portal link; full medical details must not be placed into SMS/email by default. WhatsApp is a later explicit data-sharing decision, not a hidden dependency.

## 10. Phases, outputs, gates and indicative effort

Durations assume two experienced engineers plus part-time domain, design, security and QA support. They exclude procurement and customer onboarding delays. Implement one phase at a time; later phases require their own focused specification.

### Phase 0 — Discovery and evaluation design (1–2 weeks)
- Interview claims processors, medical reviewers, operations/security owners and policyholders or representatives.
- Choose one partner, reimbursement workflow, product versions, languages and explicit exclusions.
- Build a data inventory/threat model, workflow map, role matrix and approved data-access path.
- Define baseline manual review time and quality labels; collect an authorized, stratified evaluation set.
- Estimate deployment cost from expected pages/claim, claims/day, latency and retention.
- Gate: named product/domain/security owners, signed-off initial scope and acceptance criteria; no undocumented real-data access.

### Phase 1 — Secure foundation (2–3 weeks)
- Fix dependency/test baseline; add clean-install CI, migrations and isolated test fixtures.
- Introduce PostgreSQL schema, identity, role checks, object storage, audit and environment separation.
- Set up private container deployment, secrets, health/readiness and backup/restore scripts.
- Gate: unauthorized access denied, tenant boundary tests pass, migrations and restore work on a clean environment.

### Phase 2 — Product UI and document intelligence (3–4 weeks)
- Build public synthetic showcase and staff application shell with complete loading/error/empty states.
- Implement uploads, quarantine, durable jobs, OCR/layout parsing, source viewer and fact corrections.
- Add page/field provenance, table editing, processing failure recovery and supported-language testing.
- Gate: supported document classes are usable end to end; critical uncertain values require verification; no public production-data path.
- Release R1: private document workspace; no automated assessment claims.

### Phase 3 — Policy registry and deterministic assessment (3–4 weeks)
- Implement UIN/version/schedule/endorsement resolution and domain-approved rule packs.
- Add structured bill reconciliation, precise financial calculations and utilization-input handling.
- Add scoped evidence search and clause/source links; migrate eligible local prototype artifacts through verified re-ingestion.
- Gate: reference calculation suite passes exactly with specified rounding; wrong/missing policies block definitive results; cross-tenant retrieval tests pass.

### Phase 4 — Private AI assistance and review (2–3 weeks)
- Benchmark local model candidates, validate typed outputs and evidence, add explicit abstention.
- Implement immutable assessment runs, reviewer assignment/actions, conflict protection and drafted explanations.
- Test prompt injection, unsupported citations, multilingual errors and adversarial document content.
- Gate: held-out quality thresholds agreed in Phase 0 are met; no model action bypasses a review/permission gate.
- Release R2: shadow mode, existing review process remains authoritative.

### Phase 5 — Production pilot (2–4 weeks)
- Complete consumer status/clarification portal, representative permissions and approved communications.
- Run security review, peak-load tests, failure recovery, restore/rollback drills and operator training.
- Deploy controlled pilot, monitor quality and compare against manual baseline.
- Gate: domain/customer acceptance, operational ownership, incident runbooks and agreed capacity/quality thresholds; mandatory human authorization.
- Release R3: paid pilot for named products and document types.

### Phase 6 — Enterprise and cashless expansion (4–8+ weeks per scoped tranche)
- Customer SSO/integration adapters, utilization feeds, hospital/insurer systems and NHCX qualification where available.
- Cashless workflow with source-based event timestamps, escalation and verified SLA semantics.
- Availability/DR upgrades, customer-managed keys, deployment automation, one evaluated regional language at a time.
- Gate: partner integration approval, contract-tested mappings, end-to-end sandbox validation, recovery/capacity qualification.

### Phase 7 — Scale and advanced vision (ongoing, evidence-driven)
- Evaluate VLM fallback, broader document layouts, better multilingual retrieval and new policy families.
- Improve serving throughput only when measurements justify it; shared tenancy only after isolation qualification.
- Add other insurance lines as separate domain projects with separate evaluation sets.
- Gate: each capability demonstrates quality gain and acceptable cost; existing supported cases do not regress.

Indicative total through a controlled R3 pilot: 13–20 engineering calendar weeks under the staffing assumptions above, plus external delays. A solo implementation will take longer. Do not present this as a fixed bid before Phase 0.

## 11. Test and release strategy

Unit: rule calculations, policy resolution, state transitions, input validation.
Integration: DB/storage/queue transactions, authorization, upload validation, retries and idempotency.
End-to-end: upload -> correct facts -> assess -> review -> communicate, including keyboard/mobile journeys.
Security: cross-tenant IDs, signed URL leakage, worker scope, injection, malicious PDFs, privilege changes, log leakage.
Resilience: worker death, database/storage unavailability, broker redelivery, GPU OOM, model timeout, deployment rollback and restored backups.
Model evaluation: critical-field accuracy, clause retrieval recall, citation validity, unsupported findings, abstention quality, reviewer corrections, subgroup performance and latency.

Split evaluation by case and document family where possible to avoid near-duplicate leakage. Keep held-out cases out of prompt tuning. Domain reviewers adjudicate disputed labels. A few hundred cases can support a pilot assessment but cannot prove rare-error safety; expand by observed uncertainty and product diversity.

Hard gates: zero observed cross-tenant access in the test suite; all deterministic golden calculations pass; all final outcomes require an authorized review; all assessed facts have provenance or explicit missing status. These are gates, not claims of zero real-world risk. Statistical AI thresholds and latency/concurrency targets must be agreed in Phase 0 with denominators and uncertainty, not invented now.

Provisional recovery objectives for the bounded pilot: RPO <=24h and RTO <=4h, subject to customer acceptance and a demonstrated restore. Cashless operation requires tighter, separately agreed availability/recovery targets; do not reuse pilot objectives silently.

## 12. Migration from this repository

- Retain FastAPI, useful Pydantic validation and PDF extraction behind interfaces.
- Replace SQLite with migrated PostgreSQL records; sanitize prototype/demo data before any customer import.
- Replace shared FAISS files with scoped document/chunk/vector records; re-embed under a recorded model version.
- Replace fixed character slicing with layout/clause-aware segmentation.
- Replace synchronous /decide with jobs and assessment resources.
- Replace Streamlit with the web app after parity tests; keep it only as a temporary development utility.
- Replace prompt-only coverage decisions with policy resolution, rules, validated evidence and human review.
- Repair tests, raw exception leakage, permissive CORS, debug defaults and unbounded history queries.
- Preserve history/export capability during migration; rehearse rollback and reconcile counts/hashes.

## 13. Commercial and operating model

Validate a platform subscription plus bounded processing volume, dedicated hosting charge and scoped onboarding/integration fee. Track cost per page, assessment and reviewed claim; use quotas and backpressure. No charge tied to rejection volume. No invented price until workload and willingness-to-pay interviews exist.

Named ownership: product owner defines workflow; domain reviewer approves policy rules; engineers own implementation/operations; security/privacy owner approves controls; customer representative owns authorized use and acceptance. Incidents and model regressions have an immediate switch to manual processing.

Not in the initial release: autonomous denial/payment, universal policy support, all Indian languages, medical diagnosis, broad fraud scoring, unrestricted chat agents, fine-tuning on customer data, NHCX production access assumptions, Kubernetes by default, public anonymous real-claim uploads.

## 14. Research basis and limits

The following primary sources informed the proposal; they do not certify this design. Exact product/library versions, licenses, applicable legal obligations and integration access must be rechecked before implementation/deployment.

- India cashless timelines, Ministry of Finance: https://www.pib.gov.in/newsite/erelcontent.aspx?lang=2&reg=48&relid=286915
- Exact policy UIN/version selection, HDFC ERGO: https://www.hdfcergo.com/download/policy-wordings/health
- DPDP rules and enforcement notifications, MeitY: https://www.meity.gov.in/documents/act-and-policies/digital-personal-data-protection-rules-2025-gDOxUjMtQWa?pageTitle=Digital-Personal-Data-Protection-Rules-2025-2
- NHCX, government announcement: https://www.pib.gov.in/PressReleaseIframePage.aspx?PRID=2037634&lang=2&reg=48
- FHIR adoption guide, NRCeS: https://www.nrces.in/download/files/pdf/Implementation_Guide_for_Adoption_of_FHIR_in_ABDM_and_NHCX.pdf
- OCR language capabilities: https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/algorithm/PP-OCRv5/PP-OCRv5_multi_languages.en.md
- Local/cloud serving controls: https://docs.ollama.com/faq
- PostgreSQL isolation caveats: https://www.postgresql.org/docs/17/ddl-rowsecurity.html
- Vector search: https://github.com/pgvector/pgvector
- Model candidates: https://huggingface.co/Qwen/Qwen3-8B and https://bge-model.com/bge/bge_m3
- Object encryption: https://docs.aws.amazon.com/AmazonS3/latest/userguide/UsingKMSEncryption.html

Next authorized work should be Phase 0 only. Phase 0 produces the focused specification and backlog for Phase 1; it does not trigger implementation of every phase in this document.
