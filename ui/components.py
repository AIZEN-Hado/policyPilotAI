"""
Reusable Streamlit UI components for PolicyPilotAI — Ollama Edition.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

import httpx
import streamlit as st


# ── Header ─────────────────────────────────────────────────────────────────────

def render_header() -> None:
    st.markdown(
        """
        <h1 style='text-align:center; color:#4A90D9;'>🛡️ PolicyPilotAI</h1>
        <p style='text-align:center; color:#888; font-size:1.1rem;'>
            AI-powered insurance coverage decisions — 100% local &amp; private.<br>
            <small>Powered by <strong>Ollama</strong> + <strong>LangChain</strong>
            + <strong>FAISS</strong> · Runs on your GTX 1650</small>
        </p>
        <hr>
        """,
        unsafe_allow_html=True,
    )


# ── Sidebar ────────────────────────────────────────────────────────────────────

# Models safe for GTX 1650 (4 GB VRAM)
SAFE_MODELS = {
    "phi3:mini":   "phi3:mini   (~2.5 GB) ← recommended",
    "llama3.2:3b": "llama3.2:3b (~2.3 GB)",
    "gemma:2b":    "gemma:2b    (~1.5 GB)",
    "tinyllama":   "tinyllama   (~0.8 GB) ← fastest",
}


def render_sidebar(api_base: str) -> None:
    with st.sidebar:
        st.image("https://img.icons8.com/fluency/96/shield.png", width=80)
        st.title("PolicyPilotAI")
        st.caption("Ollama · LangChain · FAISS · SQLite")

        # ── Ollama status ──────────────────────────────────────────────────────
        st.divider()
        st.subheader("🤖 Ollama Status")
        try:
            resp = httpx.get("http://localhost:11434", timeout=2)
            st.success("✅ Ollama is running")
        except Exception:
            st.error("❌ Ollama not detected on :11434")
            st.caption("Start it with: `ollama serve`")

        # ── Model info ─────────────────────────────────────────────────────────
        st.divider()
        st.subheader("🧠 Model (GTX 1650 safe)")
        for short, label in SAFE_MODELS.items():
            st.caption(f"• `{label}`")
        st.caption("Change model in `.env` → `OLLAMA_MODEL=`")

        # ── Policies ───────────────────────────────────────────────────────────
        st.divider()
        st.subheader("📁 Policies")
        if st.button("🔄 Refresh", key="sidebar_refresh"):
            st.rerun()
        try:
            resp = httpx.get(f"{api_base}/policies", timeout=5)
            policies = resp.json()
            if policies:
                for p in policies:
                    st.markdown(f"- 📄 `{p}`")
            else:
                st.info("No policies ingested yet.")
        except Exception:
            st.warning("Backend offline.")

        st.divider()
        if st.button("⚡ Ingest PDFs"):
            with st.spinner("Ingesting…"):
                try:
                    r = httpx.post(f"{api_base}/ingest", timeout=10)
                    st.success(r.json().get("status", "Started"))
                except Exception as exc:
                    st.error(str(exc))

        st.divider()
        st.caption("DB: `data/policypilot.db` (SQLite)")
        st.caption("Embeds: `all-MiniLM-L6-v2` (CPU)")


# ── Claim Form ─────────────────────────────────────────────────────────────────

def render_claim_form() -> Optional[Dict[str, Any]]:
    with st.form("claim_form"):
        st.subheader("📋 Submit a Claim")
        col1, col2 = st.columns(2)
        with col1:
            claimant_name = st.text_input("Claimant Name (optional)")
            policy_number = st.text_input("Policy Number (optional)")
            incident_date = st.date_input("Incident Date")
        with col2:
            claim_type = st.selectbox(
                "Claim Type",
                ["medical", "property", "auto", "life", "liability", "travel", "other"],
            )
            claim_amount = st.number_input("Claim Amount (USD)", min_value=0.0, step=100.0, value=0.0)

        description = st.text_area(
            "Claim Description",
            placeholder="Describe the incident and what is being claimed…",
            height=150,
        )
        submitted = st.form_submit_button("🔍 Analyse Claim", use_container_width=True)

    if submitted:
        if len(description.strip()) < 20:
            st.warning("Please provide at least 20 characters.")
            return None
        return {
            "claimant_name": claimant_name or None,
            "policy_number": policy_number or None,
            "claim_type":    claim_type,
            "incident_date": str(incident_date),
            "claim_amount":  claim_amount if claim_amount > 0 else None,
            "description":   description.strip(),
        }
    return None


# ── Decision Result ─────────────────────────────────────────────────────────────

_DECISION_STYLES: Dict[str, tuple] = {
    "COVERED":            ("✅ COVERED",            "success"),
    "PARTIALLY_COVERED":  ("⚠️ PARTIALLY COVERED",  "warning"),
    "EXCLUDED":           ("❌ EXCLUDED",            "error"),
    "REQUIRES_MORE_INFO": ("ℹ️ REQUIRES MORE INFO", "info"),
    "UNKNOWN":            ("❓ UNKNOWN",             "info"),
}


def render_decision_result(result: Dict[str, Any]) -> None:
    label, level = _DECISION_STYLES.get(result.get("decision", "UNKNOWN"), ("❓ UNKNOWN", "info"))
    getattr(st, level)(f"**Decision: {label}**")

    confidence = result.get("confidence", 0.0)
    st.metric("Confidence", f"{confidence:.0%}")
    st.progress(confidence)
    st.divider()

    st.subheader("🧠 Reasoning")
    st.write(result.get("reasoning", "No reasoning provided."))

    clauses = result.get("relevant_clauses", [])
    if clauses:
        st.subheader("📜 Relevant Policy Clauses")
        for i, c in enumerate(clauses, 1):
            with st.expander(f"Clause {i}"):
                st.write(c)

    exclusions = result.get("exclusions_noted", [])
    if exclusions:
        st.subheader("🚫 Exclusions Noted")
        for e in exclusions:
            st.warning(e)

    rec = result.get("recommendation", "")
    if rec:
        st.subheader("💡 Recommendation")
        st.info(rec)


# ── History ────────────────────────────────────────────────────────────────────

def render_history(api_base: str) -> None:
    st.subheader("📂 Past Claims & Decisions")
    col1, col2 = st.columns([3, 1])
    with col1:
        limit = st.slider("Show last N claims", 5, 100, 20)
    with col2:
        st.write("")
        if st.button("🔄 Refresh", key="history_refresh"):
            st.rerun()

    try:
        resp = httpx.get(f"{api_base}/history?limit={limit}", timeout=10)
        resp.raise_for_status()
        rows = resp.json()
    except Exception as exc:
        st.error(f"Could not load history: {exc}")
        return

    if not rows:
        st.info("No claims yet. Submit one via the Analyse Claim tab.")
        return

    for row in rows:
        dec = row.get("decision") or {}
        dlabel = dec.get("decision", "PENDING")
        label_text, _ = _DECISION_STYLES.get(dlabel, ("❓ UNKNOWN", "info"))

        with st.expander(
            f"#{row['id']} · {row['claim_type'].upper()} · {label_text} · {row['created_at']}"
        ):
            c1, c2 = st.columns(2)
            with c1:
                st.markdown(f"**Claimant:** {row.get('claimant_name') or '—'}")
                st.markdown(f"**Policy #:** {row.get('policy_number') or '—'}")
                st.markdown(f"**Incident:** {row.get('incident_date') or '—'}")
                st.markdown(f"**Amount:** {row.get('claim_amount') or '—'}")
            with c2:
                if dec:
                    st.metric("Confidence", f"{dec.get('confidence', 0):.0%}")
                    st.caption(f"Model: `{dec.get('model_used', '—')}`")
            st.markdown(f"**Description:** {row['description']}")
            if dec:
                st.markdown("**Reasoning:**")
                st.write(dec.get("reasoning", ""))
                for clause in dec.get("relevant_clauses", []):
                    st.caption(f"› {clause}")
