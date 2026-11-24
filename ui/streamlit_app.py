"""
Streamlit frontend for PolicyPilotAI — Ollama Edition.

Run with:
    streamlit run ui/streamlit_app.py
"""
import httpx
import streamlit as st

from ui.components import (
    render_header,
    render_sidebar,
    render_claim_form,
    render_decision_result,
    render_history,
)

API_BASE = "http://localhost:8000/api/v1"

st.set_page_config(
    page_title="PolicyPilotAI",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

render_sidebar(api_base=API_BASE)
render_header()

tab_decide, tab_history = st.tabs(["🔍 Analyse Claim", "📂 History"])

with tab_decide:
    claim_data = render_claim_form()
    if claim_data:
        with st.spinner("🤖 Running local inference via Ollama…"):
            try:
                response = httpx.post(f"{API_BASE}/decide", json=claim_data, timeout=180)
                response.raise_for_status()
                render_decision_result(response.json())
            except httpx.ConnectError:
                st.error("❌ Cannot reach the backend. Run: `uvicorn app.main:app --reload`")
            except httpx.HTTPStatusError as exc:
                st.error(f"❌ API Error {exc.response.status_code}: {exc.response.text}")
            except Exception as exc:
                st.error(f"❌ {exc}")

with tab_history:
    render_history(api_base=API_BASE)
