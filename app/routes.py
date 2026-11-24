"""
API routes for PolicyPilotAI.

Endpoints:
    GET  /health              — liveness check
    GET  /policies            — list ingested PDFs
    POST /ingest              — trigger PDF ingestion
    POST /decide              — submit a claim → AI coverage decision
    GET  /history             — list past claims + decisions (from SQLite)
    GET  /history/{claim_id}  — single claim + decision by ID
"""
import json
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db import get_db, Claim, Decision, AuditLog
from app.decision_engine import DecisionEngine
from app.rag.ingest import ingest_policies
from app.utils.validators import ClaimRequest, DecisionResponse

router = APIRouter()
engine = DecisionEngine()


# ── Health ─────────────────────────────────────────────────────────────────────

@router.get("/health", tags=["ops"])
async def health_check() -> dict:
    """Liveness probe."""
    return {"status": "ok", "version": "2.0.0"}


# ── Policies ────────────────────────────────────────────────────────────────────

@router.get("/policies", tags=["policies"], response_model=List[str])
async def list_policies() -> List[str]:
    """Return a list of all ingested policy PDF filenames."""
    policy_dir = Path(settings.POLICY_PDF_DIR)
    if not policy_dir.exists():
        return []
    return [f.name for f in policy_dir.glob("*.pdf")]


# ── Ingestion ───────────────────────────────────────────────────────────────────

@router.post("/ingest", tags=["policies"])
async def trigger_ingestion(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Trigger background ingestion of all PDFs in the policy directory.
    Ingestion runs asynchronously; returns immediately.
    """
    background_tasks.add_task(ingest_policies)
    db.add(AuditLog(event="ingest_triggered", detail=settings.POLICY_PDF_DIR))
    await db.commit()
    return {"status": "ingestion started", "policy_dir": settings.POLICY_PDF_DIR}


# ── Decision ────────────────────────────────────────────────────────────────────

@router.post("/decide", tags=["decisions"], response_model=DecisionResponse)
async def make_decision(
    claim: ClaimRequest,
    db: AsyncSession = Depends(get_db),
) -> DecisionResponse:
    """
    Submit a claim and receive an AI-generated coverage decision.

    Pipeline:
    1. FAISS retrieves relevant policy clauses (HuggingFace embeddings).
    2. LangChain chain formats the prompt and calls the HuggingFace LLM.
    3. Response is parsed into a structured JSON decision.
    4. Claim + decision are persisted to SQLite.
    """
    try:
        result = await engine.decide(claim, db=db)
        return result
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Vector store not found. Run /ingest first. ({exc})",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── History ─────────────────────────────────────────────────────────────────────

@router.get("/history", tags=["history"])
async def list_history(
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """Return the most recent *limit* claims with their decisions from SQLite."""
    result = await db.execute(
        select(Claim)
        .options(selectinload(Claim.decision))
        .order_by(Claim.id.desc())
        .limit(limit)
    )
    claims = result.scalars().all()

    rows = []
    for c in claims:
        row = {
            "id":             c.id,
            "claimant_name":  c.claimant_name,
            "policy_number":  c.policy_number,
            "claim_type":     c.claim_type,
            "incident_date":  c.incident_date,
            "claim_amount":   c.claim_amount,
            "description":    c.description[:120] + ("…" if len(c.description) > 120 else ""),
            "created_at":     str(c.created_at),
            "decision":       None,
        }
        if c.decision:
            d = c.decision
            row["decision"] = {
                "decision":         d.decision,
                "confidence":       d.confidence,
                "reasoning":        d.reasoning,
                "relevant_clauses": json.loads(d.relevant_clauses),
                "exclusions_noted": json.loads(d.exclusions_noted),
                "recommendation":   d.recommendation,
                "model_used":       d.model_used,
                "created_at":       str(d.created_at),
            }
        rows.append(row)
    return rows


@router.get("/history/{claim_id}", tags=["history"])
async def get_claim(
    claim_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve a single claim and its decision by ID."""
    result = await db.execute(
        select(Claim)
        .options(selectinload(Claim.decision))
        .where(Claim.id == claim_id)
    )
    claim = result.scalar_one_or_none()
    if claim is None:
        raise HTTPException(status_code=404, detail=f"Claim {claim_id} not found.")

    out = {
        "id":            claim.id,
        "claimant_name": claim.claimant_name,
        "policy_number": claim.policy_number,
        "claim_type":    claim.claim_type,
        "incident_date": claim.incident_date,
        "claim_amount":  claim.claim_amount,
        "description":   claim.description,
        "created_at":    str(claim.created_at),
        "decision":      None,
    }
    if claim.decision:
        d = claim.decision
        out["decision"] = {
            "decision":         d.decision,
            "confidence":       d.confidence,
            "reasoning":        d.reasoning,
            "relevant_clauses": json.loads(d.relevant_clauses),
            "exclusions_noted": json.loads(d.exclusions_noted),
            "recommendation":   d.recommendation,
            "model_used":       d.model_used,
            "created_at":       str(d.created_at),
        }
    return out
