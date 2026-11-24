# Neural Review Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development to implement and review each task.

**Goal:** Connect verified specialist inference and ship five reviewer tools.

**Architecture:** A CPU service runs the existing networks; a bounded authenticated adapter validates returned citations. Review tools retain immutable evidence snapshots and correction history.

**Tech Stack:** Python, FastAPI, PostgreSQL, existing vanilla JavaScript UI, optional PyTorch service.

**Spec:** docs/superpowers/specs/2026-11-24-neural-review-design.md

## Global constraints

Preserve rule fallback, synthetic scope, exact citations, authentication, reviewer authority, and existing model guards. No provisioning or deployment. Git metadata is read-only: edit the authorized working directory and record changes without commits.

## Task 1: Specialist inference
- [ ] Create `pilot/specialist_client.py`, `specialists/serving.py`, service requirements and operator documentation.
- [ ] Define `review_specialists(documents) -> dict`: state, checkpoint, suggestions keyed by six labels, evidence keyed by six labels, detail. Suggestions carry existing candidate citation keys; errors return unavailable, disabled returns disabled.
- [ ] Validate input/output bounds, citations, finite scores, checkpoint identity, and support document kinds explicitly.
- [ ] Verify real preprocessing and model loading, bounded windows and inference, auth, no document logs; test with transport fixtures and checkpoint loader failure fixtures.

## Task 2: Review tools API and persistence
- [ ] Create `pilot/review_tools.py`, `pilot/review_routes.py`, migration 010, and tests.
- [ ] Register `register_review_routes(app, connect, get_case, actor, review_revision, event)` from api before StaticFiles mount.
- [ ] Expose GET `/api/cases/{cid}/tools`, POST `/api/cases/{cid}/corrections`, GET `/api/cases/{cid}/report`, GET `/api/review-metrics`.
- [ ] Tools response: checklist list of kind/label/present/required, timeline list, corrections list, current_corrections list, review_revision. Corrections body: review_revision, field, value, reason, document_id, page, start_offset, end_offset, source (`rules` or `neural`).
- [ ] Preserve evidence revision identity across correction edits; invalidate acknowledgements, reject stale requests, and isolate old corrections after uploads.
- [ ] Implement escaped HTML report and latest-per-field outcome metrics with clear denominators/checkpoint grouping.
- [ ] Test SQL through existing SQLite route harness adapted for new migration and JSON values, plus pure functions.

## Task 3: Interface
- [ ] Create `pilot/static/review-tools.js` and CSS; modify index and app event payload only as needed.
- [ ] Show checklist, timeline, neural suggestions and supported ranked evidence, revision-bound correction form/history, report download, workspace dashboard.
- [ ] Use textContent/escaping, existing source citation events, stale navigation guards and accessible forms. Correction saves reload active case.
- [ ] Add focused JS interface checks and run existing node checks.

## Task 4: Integration and verification
- [ ] Call specialist adapter after PDF extraction; persist availability, checkpoint and suggestions in result. Extend readiness.
- [ ] Review each deliverable and fix material findings; run API, PDF, JS and deployment checks.
- [ ] Locate verified trained checkpoint if accessible without secret disclosure or provisioning. Run actual-model verification only in permitted environment; otherwise state this remaining limitation explicitly.
- [ ] Document migration, separate service launch, environment settings and rollback/fallback behavior.
