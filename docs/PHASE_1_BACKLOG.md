# Phase 1 — Secure foundation backlog

Status: proposed implementation backlog. Depends on the Phase 0 scope decision. This document does not start application changes or infrastructure spending.

## Sequence

| ID | Work package | Dependencies | Acceptance evidence |
|---|---|---|---|
| F01 | Establish supported runtime, reproducible dependencies and clean isolated tests | None | Clean install and tests; no production DB/model download dependency |
| F02 | Define configuration profiles and safe error contracts | F01 | Invalid production settings fail startup; errors omit secrets and raw payloads |
| F03 | Introduce PostgreSQL and Alembic schema for organizations, memberships, cases and audit | F01 | Migration/rollback rehearsal; tenant-safe references; precise monetary types |
| F04 | Integrate OIDC identity and verified organization context | F02, F03 | Valid/expired/wrong-audience credentials and membership changes tested |
| F05 | Enforce role/assignment authorization and DB isolation | F04 | Cross-tenant/object access tests; application role cannot bypass intended controls |
| F06 | Create private object-storage adapter and bounded upload sessions | F02, F05 | Unauthorized/expired uploads and downloads denied; quarantine enforced |
| F07 | Add durable jobs, transactional outbox and idempotency | F03, F05 | Crash/redelivery/retry tests; consistent committed business state |
| F08 | Add safe audit events and minimal operational telemetry | F05, F07 | Access/change events attributable; no sensitive payloads in logs |
| F09 | Package a private local/staging deployment and secrets handling | F02–F08 | Repeatable boot, readiness, network isolation and offline model boundary checks |
| F10 | Add backup/restore and release/rollback rehearsal | F09 | Restore reconciles records and objects; documented operator steps |
| F11 | Close Phase 1 review | F01–F10 | All gates demonstrated; remaining risks documented before Phase 2 |

## Intended code boundaries

Preserve useful FastAPI/Pydantic logic while extracting configuration, authorization, claims, document storage, jobs and audit modules. No model capability changes in this phase. Existing unauthenticated history/ingestion routes must be protected or disabled in the new secured deployment.

Use separate unit, database integration and external-service integration tests. Run relevant checks per work package; avoid rebuilding the entire UI or OCR stack as part of foundation work.

## Deliverable

A reproducible private service that authenticates users, enforces resource scope, persists cases, accepts quarantined documents, records durable work and recovers from a rehearsed failure. UI implementation and actual OCR enter Phase 2.

## Decisions needed before implementation

Confirm synthetic-only engineering versus partner-backed pilot; identity provider and development identity strategy; local container availability; deployment ownership; whether infrastructure provisioning is within scope. Do not require real customer data to build the foundation.
