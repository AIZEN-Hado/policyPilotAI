# Phase 0 — Pilot definition and validation

Status: synthetic-first development confirmed by user; no pilot partner yet. Partner and domain validation remain outstanding for a real-data release.
Date: 2026-11-07.
Parent plan: [Production master plan](PRODUCTION_MASTER_PLAN.md).

## Working scope

Use a synthetic Indian hospitalization reimbursement workflow to develop and demonstrate the product until a partner and authorized data access are established. The user explicitly selected this path and requires realistic, high-quality synthetic data. Follow [Synthetic data quality specification](SYNTHETIC_DATA_SPEC.md). No pilot partner is currently available.

Target buyer: a TPA or insurer operations team. Target user: a claims processor collaborating with an authorized reviewer. Target beneficiary: the policyholder receiving clearer status and explanations.

First journey: create case -> attach policy schedule/wording/endorsement and claim documents -> inspect extraction -> correct uncertain facts -> resolve policy -> generate evidence-backed assessment -> reviewer authorizes result -> publish audience-appropriate explanation.

First language scope: English documents and interface baseline; Hindi document/explanation evaluation before claiming Hindi support. No initial all-language commitment.

First product families: two explicitly fictional policy fixtures, one individual and one family-floater policy. These exercise software behavior without presenting invented terms as an actual insurer product. Real products replace or supplement them only after version identification and domain review.

Exclude cashless guarantees, payouts, clinical diagnosis, fraud determinations, automatic repudiation, and government/insurer integrations from the first journey.

## What is known versus assumed

Known: current repository has FastAPI, Streamlit, local Ollama inference, PDF text extraction, a shared FAISS index and SQLite. It lacks tenant authorization, OCR, authoritative policy matching and a human review workflow.

Assumed: dedicated customer deployment; customer allows private model hosting; primary buyer is TPA/insurer; initial workflow is reimbursement. These must be revisited if the partner is a hospital/broker or requires on-premises deployment.

Unresolved decisions: partner identity/type, deployment ownership and region, document access permissions, supported product versions, accountable domain reviewer, daily/peak volume, document size distribution, budget, target languages, retention and recovery requirements. None can be validated from repository inspection.

## Stakeholder discovery

Interview before committing to a real-data pilot:
- Operations lead: where cases wait, common clarification loops, throughput and escalation ownership.
- Claims processor: actual document sequence, data re-entry, source systems, typical exceptions.
- Authorized reviewer: decision authority, required evidence, deduction ordering, override procedure.
- Security/privacy owner: processing instructions, deployment restrictions, data access, retention and incident procedure.
- Policyholder/representative: unclear communications, accessibility, authorization and status needs.

Capture current median and p95 handling time, time spent correcting documents, clarification count and reviewer disagreement. Do not invent baseline measurements. Compare assisted and unassisted review on equivalent case mixes and record corrections alongside time savings.

## Initial role matrix

| Role | Allowed | Restricted |
|---|---|---|
| Organization administrator | Membership and configuration | No routine claim-content access solely from admin role |
| Processor | Assigned cases, upload, correct facts, request assessment | Cannot authorize final outcome |
| Reviewer | Assigned cases, inspect evidence, authorize/revise outcome | Cannot change identity/security configuration |
| Policy specialist | Draft and approve policy rules under explicit permission | No blanket access to unrelated medical records |
| Policyholder | Own case's published status and permitted documents | No internal notes or other family members' unrelated records |
| Representative | Explicitly delegated case scope and duration | No implicit access based on shared phone/policy number |
| Support engineer | Approved, expiring support scope | No default access to live case contents |

Actual customer roles and segregation-of-duty requirements must be mapped before real-data use.

## Data access boundary

Use generated fictional names, identifiers, documents and rules for the initial fixture set. Never copy real medical records into public demos, version control, development logs, or external model tools. Public policy wordings can inform research but are not proof of a member's coverage.

Before authorized customer cases: document processing instructions and roles, access list, permitted environment, retention, de-identification limits, transfer method and domain review ownership. Derived OCR, embeddings and annotations remain sensitive. De-identification is not assumed merely because names are removed.

## Phase 0 exit checklist

- [x] Repository baseline and gaps documented.
- [x] Initial scope, exclusions and synthetic fallback drafted.
- [x] Role matrix and evaluation protocol drafted.
- [x] Dependency-ordered Phase 1 backlog drafted.
- [ ] Pilot buyer/workflow validated through stakeholder discussion.
- [ ] Domain reviewer and acceptance owner identified.
- [x] Synthetic-only scope explicitly selected by user; no real customer data authorized.
- [ ] Product versions, languages and document classes selected.
- [ ] Workload, budget, deployment and operational objectives agreed.
- [ ] Quantitative model-quality thresholds agreed against an evaluation baseline.

Phase 0 is not complete until the external decisions applicable to the intended release are resolved. Synthetic engineering can proceed under its own scoped approval without claiming customer validation.
