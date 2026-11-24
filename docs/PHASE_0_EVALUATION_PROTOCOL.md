# Phase 0 — Evaluation protocol

Status: first three development exemplars generated (24 PDFs / 29 pages); engineering validation recorded in `evaluation/synthetic/validation_report.json`. No model/OCR accuracy measurements or real-data validation yet. The 48-bundle matrix remains future work.

The user has confirmed there is no partner and requires realistic synthetic data. Generation must follow [Synthetic data quality specification](SYNTHETIC_DATA_SPEC.md). A fixture count alone does not meet the quality requirement.

## Initial synthetic engineering matrix

Create 24 case families with clean and degraded document variants: 48 fixture bundles. Group variants under a single family ID so train/development/evaluation partitions never split near-duplicates. This small corpus is an engineering baseline, not proof of real-world accuracy.

| Families | Scenarios |
|---|---|
| 1–4 | Complete straightforward claim; explicit copay; explicit deductible; defined sublimit |
| 5–8 | Room category restriction; endorsement changes term; waiting-period boundary; coverage-date boundary |
| 9–12 | Family member mismatch; unknown prior utilization; conflicting policy versions; absent schedule |
| 13–16 | Missing bill page; arithmetic discrepancy; duplicate upload; same claim retried |
| 17–20 | Low-quality scan; rotated table; ambiguous date; Hindi/English mixed document |
| 21–24 | Document prompt injection; foreign-tenant document reference; changed fact after assessment; contradictory evidence |

All financial terms and expected results come from explicitly fictional approved fixture rules. Never assume a universal deductible/copay order. Each test records the order and rounding it is testing.

## Bundle schema

Each case contains case_family_id, variant_id, organization_id, member_id, policy_version_id, document manifest/hashes, source facts with page coordinates, expected missing/uncertain facts, applicable fictional rules, expected calculation lines, expected workflow state and prohibited behaviors.

A domain-reviewed real-case set later adds language, hospital/document origin, product version, scan quality and outcome strata. Historical decisions are evidence to review, not automatically correct ground truth. Resolve annotation disagreement explicitly.

## Measurements

| Measure | Definition |
|---|---|
| Critical-field exact accuracy | Correct normalized values / annotated critical fields; report abstentions separately |
| Critical-field unsafe error rate | Incorrect critical fields accepted without verification / critical fields |
| Citation validity | Supported findings with correct source/version/span / cited findings |
| Required-evidence recall | Required annotated evidence retrieved / all required annotated evidence |
| Calculation correctness | Exact agreement with approved decimal/rounding reference cases |
| Unsupported outcome rate | Definitive findings lacking required support / definitive findings |
| Abstention behavior | Correct missing-evidence deferrals and unnecessary deferrals, separately |
| Review effort | Active reviewer minutes and corrections per case |
| System performance | Queue delay, processing p50/p95, memory and failure/retry rate at declared load |

Report denominators, scenario breakdowns and uncertainty; aggregate accuracy must not conceal failures in a language or poor-scan subgroup. Separate OCR, retrieval, generation and rule errors.

## Engineering gates

- All golden financial calculations match their explicit rules and rounding.
- Cross-tenant access is denied in API, file, search, job and export tests.
- Every critical unverified input blocks dependent definitive calculations.
- Every final outcome requires the appropriate human permission and version check.
- Corrections mark affected assessments stale; prior assessment history remains available.
- Failed processing never becomes a substantive claim rejection.
- Worker restart and duplicate delivery do not duplicate business outcomes.
- Every finding has a valid source or an explicit missing-evidence status.

These gates are test requirements, not guarantees of zero production risk. Real-data model accuracy, latency and business improvement thresholds remain subject to partner/domain validation before deployment.

## Model comparison procedure

Fix the dataset, input normalization, policy scope and prompt version; compare the existing baseline against candidate OCR, embeddings and generation separately. Record model digest, license review, hardware, quantization, context, concurrency, runtime, cost and error taxonomy. Use held-out case families for selection checks; do not continually tune against the final acceptance set.

No external model API receives private samples. No model download or inference job is authorized by this document alone.
