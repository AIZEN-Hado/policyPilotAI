"""
Core decision engine for PolicyPilotAI — Ollama Edition.

Pipeline:
    1. Retrieve top-K policy chunks from FAISS (HuggingFace embeddings, CPU).
    2. Format the LangChain ChatPromptTemplate with claim + context.
    3. Run inference via Ollama (local GPU — GTX 1650 4 GB).
    4. Parse the JSON response robustly (handles model quirks).
    5. Persist claim + decision to SQLite.

GPU NOTE (GTX 1650 — 4 GB VRAM):
    - Ollama offloads model layers to CUDA automatically.
    - phi3:mini (~2.5 GB at Q4) fits comfortably.
    - Embeddings run on CPU → zero VRAM competition.
    - num_gpu=99 tells Ollama to offload ALL layers to GPU.
    - If you see CUDA OOM, switch to tinyllama in .env.
"""
from __future__ import annotations

import json
import re

from langchain_ollama import OllamaLLM

from app.config import settings
from app.prompts import DECISION_PROMPT, build_prompt_kwargs
from app.rag.retriever import PolicyRetriever
from app.utils.validators import ClaimRequest, DecisionResponse


def _build_llm() -> OllamaLLM:
    """
    Build a LangChain OllamaLLM pointing at the local Ollama server.

    Key parameters for GTX 1650 (4 GB):
        num_gpu=99   → offload every layer to GPU (Ollama ignores layers > model size)
        num_ctx=4096 → context window; reduce to 2048 if you hit memory errors
        temperature  → low (0.1) for deterministic JSON output
    """
    return OllamaLLM(
        model=settings.OLLAMA_MODEL,
        base_url=settings.OLLAMA_BASE_URL,
        temperature=settings.LLM_TEMPERATURE,
        num_ctx=settings.LLM_NUM_CTX,
        num_gpu=settings.LLM_NUM_GPU,       # push all layers to CUDA
        num_thread=settings.LLM_NUM_THREAD,
    )


def _extract_json(raw: str) -> dict:
    """
    Extract the first valid JSON object from *raw*.

    Small models sometimes:
      - Wrap JSON in ```json … ``` fences
      - Add a preamble sentence before the object
      - Truncate the JSON if context is too long

    This function handles all three cases gracefully.
    """
    # 1. Strip markdown fences
    raw = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()

    # 2. Direct parse (happy path)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # 3. Find first { … } block in the output
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    # 4. Safe fallback — never crash the API
    return {
        "decision": "REQUIRES_MORE_INFO",
        "confidence": 0.0,
        "reasoning": (
            "The model did not return valid JSON. "
            "Raw output (first 400 chars): " + raw[:400]
        ),
        "relevant_clauses": [],
        "exclusions_noted": [],
        "recommendation": "Please retry, or check that Ollama is running and the model is pulled.",
    }


class DecisionEngine:
    """
    Orchestrates the RAG + Ollama pipeline to produce a coverage decision.

    LLM    : Ollama local server (GTX 1650, GPU-accelerated)
    Embeds : HuggingFace SentenceTransformers (CPU — no VRAM used)
    Chain  : LangChain LCEL  →  DECISION_PROMPT | OllamaLLM
    """

    def __init__(self) -> None:
        self.llm       = _build_llm()
        self.retriever = PolicyRetriever()
        self._chain    = DECISION_PROMPT | self.llm

    async def decide(
        self,
        claim: ClaimRequest,
        db=None,
    ) -> DecisionResponse:
        """
        Given a claim, retrieve policy context and run Ollama inference.

        Args:
            claim : Validated ClaimRequest pydantic model.
            db    : Optional AsyncSession — saves claim+decision to SQLite.

        Returns:
            DecisionResponse with decision, confidence, reasoning, etc.
        """
        # ── 1. Retrieve relevant policy chunks ─────────────────────────────────
        query  = f"{claim.claim_type}: {claim.description}"
        chunks = self.retriever.retrieve(query, top_k=settings.TOP_K_RESULTS)
        context = "\n\n---\n\n".join(
            f"[Source: {c['source']} | Page {c['page']}]\n{c['text']}"
            for c in chunks
        )

        # ── 2. Build prompt kwargs ──────────────────────────────────────────────
        prompt_kwargs = build_prompt_kwargs(claim=claim, context=context)

        # ── 3. Run LangChain chain (ChatPromptTemplate | OllamaLLM) ────────────
        # OllamaLLM.invoke() is synchronous but fast with GPU offload.
        raw: str = self._chain.invoke(prompt_kwargs)

        # ── 4. Parse JSON ───────────────────────────────────────────────────────
        data = _extract_json(raw)

        response = DecisionResponse(
            decision         = data.get("decision", "UNKNOWN"),
            confidence       = float(data.get("confidence", 0.0)),
            reasoning        = data.get("reasoning", ""),
            relevant_clauses = data.get("relevant_clauses", []),
            exclusions_noted = data.get("exclusions_noted", []),
            recommendation   = data.get("recommendation", ""),
        )

        # ── 5. Persist to SQLite ────────────────────────────────────────────────
        if db is not None:
            await _persist(claim, response, db)

        return response


# ── DB persistence helper ───────────────────────────────────────────────────────

async def _persist(claim: ClaimRequest, result: DecisionResponse, db) -> None:
    """Insert Claim + Decision + AuditLog rows into SQLite."""
    import json as _json
    from app.db import Claim as DBClaim, Decision as DBDecision, AuditLog

    db_claim = DBClaim(
        claimant_name = claim.claimant_name,
        policy_number = claim.policy_number,
        claim_type    = claim.claim_type.value,
        incident_date = claim.incident_date,
        claim_amount  = claim.claim_amount,
        description   = claim.description,
    )
    db.add(db_claim)
    await db.flush()

    db.add(DBDecision(
        claim_id         = db_claim.id,
        decision         = result.decision.value,
        confidence       = result.confidence,
        reasoning        = result.reasoning,
        relevant_clauses = _json.dumps(result.relevant_clauses),
        exclusions_noted = _json.dumps(result.exclusions_noted),
        recommendation   = result.recommendation,
        model_used       = f"ollama/{settings.OLLAMA_MODEL}",
    ))

    db.add(AuditLog(
        event  = "claim_decided",
        detail = f"claim_id={db_claim.id} decision={result.decision.value} model=ollama/{settings.OLLAMA_MODEL}",
    ))

    await db.commit()
