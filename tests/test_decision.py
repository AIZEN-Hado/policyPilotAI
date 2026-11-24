"""
Tests for the decision engine.
OllamaLLM and PolicyRetriever are fully mocked — Ollama does not need
to be running to execute these tests.
"""
import json
import pytest
from unittest.mock import MagicMock, patch

from app.utils.validators import ClaimRequest, DecisionLabel


@pytest.fixture
def sample_claim():
    return ClaimRequest(
        claimant_name="Jane Doe",
        policy_number="POL-001",
        claim_type="medical",
        incident_date="2024-01-15",
        claim_amount=5000.0,
        description="Patient admitted for emergency appendectomy surgery at a network hospital.",
    )


@pytest.mark.asyncio
@patch("app.decision_engine.PolicyRetriever")
@patch("app.decision_engine._build_llm")
async def test_decide_covered(mock_build_llm, mock_retriever_cls, sample_claim):
    # Mock retriever
    mock_retriever = MagicMock()
    mock_retriever.retrieve.return_value = [
        {"text": "Emergency surgery is covered under Section 3.",
         "source": "policy.pdf", "page": 2}
    ]
    mock_retriever_cls.return_value = mock_retriever

    # Mock Ollama chain output (clean JSON)
    fake_json = json.dumps({
        "decision": "COVERED",
        "confidence": 0.92,
        "reasoning": "Emergency surgery is explicitly covered under Section 3.",
        "relevant_clauses": ["Emergency surgery is covered under Section 3."],
        "exclusions_noted": [],
        "recommendation": "Submit hospital bills with the claim form.",
    })
    mock_chain = MagicMock()
    mock_chain.invoke.return_value = fake_json
    mock_build_llm.return_value = MagicMock()

    from app.decision_engine import DecisionEngine
    engine = DecisionEngine()
    engine._chain = mock_chain

    result = await engine.decide(sample_claim, db=None)

    assert result.decision == DecisionLabel.COVERED
    assert result.confidence == pytest.approx(0.92)
    assert "Section 3" in result.reasoning


def test_extract_json_strips_markdown_fence():
    from app.decision_engine import _extract_json
    raw = '```json\n{"decision":"EXCLUDED","confidence":0.8,' \
          '"reasoning":"Not covered.","relevant_clauses":[],' \
          '"exclusions_noted":[],"recommendation":""}\n```'
    data = _extract_json(raw)
    assert data["decision"] == "EXCLUDED"


def test_extract_json_finds_embedded_object():
    from app.decision_engine import _extract_json
    raw = 'Sure! Here is my analysis:\n{"decision":"COVERED","confidence":0.7,' \
          '"reasoning":"ok","relevant_clauses":[],"exclusions_noted":[],"recommendation":""}'
    data = _extract_json(raw)
    assert data["decision"] == "COVERED"


def test_extract_json_fallback_on_garbage():
    from app.decision_engine import _extract_json
    data = _extract_json("I am unable to provide a JSON response.")
    assert data["decision"] == "REQUIRES_MORE_INFO"
    assert data["confidence"] == 0.0


def test_claim_pii_guard():
    with pytest.raises(Exception):
        ClaimRequest(
            claim_type="medical",
            description="My SSN is 123-45-6789, please process my claim.",
        )
