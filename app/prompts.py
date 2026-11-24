"""
LangChain PromptTemplates for PolicyPilotAI — Ollama Edition.

phi3:mini and llama3.2 both follow the ChatML / instruction format well,
so we use ChatPromptTemplate which LangChain's OllamaLLM handles correctly.

IMPORTANT — JSON instruction:
    Small models (phi3:mini, tinyllama) sometimes wrap JSON in prose.
    The system prompt explicitly forbids this, and decision_engine.py
    has a robust _extract_json() fallback for when they disobey.
"""
from __future__ import annotations

from langchain.prompts import (
    ChatPromptTemplate,
    HumanMessagePromptTemplate,
    SystemMessagePromptTemplate,
)

from app.utils.validators import ClaimRequest

# ── System message ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT_TEXT = """You are PolicyPilotAI, an expert insurance policy analyst.

Your job is to decide if an insurance claim is covered based ONLY on the policy text provided.

Decision labels (pick exactly one):
  COVERED | PARTIALLY_COVERED | EXCLUDED | REQUIRES_MORE_INFO

Rules:
- Use ONLY the policy excerpts given. Never assume coverage from general knowledge.
- If the policy text is ambiguous or missing, return REQUIRES_MORE_INFO.
- Cite the exact clause that supports your decision.
- Output ONLY a raw JSON object. No markdown. No explanation outside the JSON.

Required JSON format:
{{
  "decision": "COVERED",
  "confidence": 0.9,
  "reasoning": "Step-by-step explanation referencing the policy.",
  "relevant_clauses": ["Exact clause text from policy"],
  "exclusions_noted": ["Any exclusion clause if present"],
  "recommendation": "Suggested next step for the claimant"
}}"""

# ── LangChain ChatPromptTemplate ────────────────────────────────────────────────

DECISION_PROMPT = ChatPromptTemplate.from_messages([
    SystemMessagePromptTemplate.from_template(SYSTEM_PROMPT_TEXT),
    HumanMessagePromptTemplate.from_template(
        "## Claim Details\n"
        "- Claimant: {claimant_name}\n"
        "- Policy Number: {policy_number}\n"
        "- Claim Type: {claim_type}\n"
        "- Incident Date: {incident_date}\n"
        "- Amount (USD): {claim_amount}\n"
        "- Description: {description}\n\n"
        "## Retrieved Policy Excerpts\n"
        "{context}\n\n"
        "Return ONLY the JSON object — no other text."
    ),
])

# Keep plain-text aliases for tests / fallback
SYSTEM_PROMPT = SYSTEM_PROMPT_TEXT


def build_prompt_kwargs(claim: ClaimRequest, context: str) -> dict:
    return {
        "claimant_name": claim.claimant_name or "Not provided",
        "policy_number": claim.policy_number  or "Not provided",
        "claim_type":    str(claim.claim_type),
        "incident_date": claim.incident_date  or "Not provided",
        "claim_amount":  str(claim.claim_amount) if claim.claim_amount else "Not specified",
        "description":   claim.description,
        "context":       context if context else "No relevant policy excerpts found.",
    }


def build_decision_prompt(claim: ClaimRequest, context: str) -> str:
    """Plain-string version used in tests."""
    kw = build_prompt_kwargs(claim, context)
    return (
        f"## Claim Details\n"
        f"- Claimant: {kw['claimant_name']}\n"
        f"- Policy Number: {kw['policy_number']}\n"
        f"- Claim Type: {kw['claim_type']}\n"
        f"- Incident Date: {kw['incident_date']}\n"
        f"- Amount (USD): {kw['claim_amount']}\n"
        f"- Description: {kw['description']}\n\n"
        f"## Retrieved Policy Excerpts\n{kw['context']}\n\n"
        f"Return ONLY the JSON object."
    )
