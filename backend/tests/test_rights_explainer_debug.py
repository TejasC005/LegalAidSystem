"""
LEXIS — Regression Tests for Rights Explainer & Knowledge Base Debugging
========================================================================
Validates fixes for:
1. Intent classification routing for consumer rights, defective products,
   and compensation queries (both LLM and keyword fallback).
2. Preservation of legitimate unclear clarification behavior.
3. Retrieval of admin-uploaded legal documents by the Rights Agent.
4. Exclusion of deactivated documents from retrieval.
5. Grounding of LLM context with retrieved chunks and citation validation.
6. End-to-end /api/v1/query endpoint execution with mocked LLMs.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from agents.orchestrator.state import AgentIntent
from agents.orchestrator.agent import (
    _keyword_classifier_fallback,
    _parse_intent_response,
    orchestrator_graph,
)
from agents.rights_agent.agent import RightsAgent, get_rights_agent
from fastapi.testclient import TestClient
from main import app
from services.auth.jwt_service import create_access_token


Q1_DEFECTIVE_PRODUCT = (
    "A defective washing machine caused a fire and damaged my furniture. "
    "Can I claim compensation for the damage?"
)
Q2_CONSUMER_COMMISSION = (
    "Who is included in the definition of a member of a Consumer Commission?"
)


# ── Test 1: Keyword Classification Fallback for Consumer Queries ──────────────

def test_keyword_fallback_classifies_defective_product_as_rights():
    """Verify keyword fallback recognizes product defect, damage, and compensation."""
    intents, confidence = _keyword_classifier_fallback(Q1_DEFECTIVE_PRODUCT)
    assert AgentIntent.RIGHTS in intents
    assert confidence >= 0.4


def test_keyword_fallback_classifies_consumer_commission_as_rights():
    """Verify keyword fallback recognizes consumer commission queries."""
    intents, confidence = _keyword_classifier_fallback(Q2_CONSUMER_COMMISSION)
    assert AgentIntent.RIGHTS in intents
    assert confidence >= 0.4


def test_keyword_fallback_preserves_unclear_for_casual_query():
    """Verify non-legal casual queries are not falsely routed to rights."""
    intents, confidence = _keyword_classifier_fallback("Hello, what is the weather today?")
    assert len(intents) == 0
    assert confidence < 0.4


# ── Test 2: LLM Classifier Parsing & Routing ──────────────────────────────────

def test_parse_intent_response_parses_rights():
    intents, confidence = _parse_intent_response("rights")
    assert intents == [AgentIntent.RIGHTS]
    assert confidence >= 0.8


def test_parse_intent_response_parses_unclear():
    intents, confidence = _parse_intent_response("unclear")
    assert intents == []
    assert confidence == 0.0


# ── Test 3: Rights Agent Retrieval of Uploaded & Active Documents ─────────────

def test_rights_agent_retrieves_uploaded_consumer_act():
    """Verify RightsAgent retrieves Consumer Protection Act chunks for Q1 and Q2."""
    agent = get_rights_agent()
    retrieved = agent.retrieve_relevant_chunks(Q1_DEFECTIVE_PRODUCT, top_k=5)
    assert len(retrieved) > 0

    acts = [p.get("act_name", "") for p, _ in retrieved]
    has_consumer_act = any("Consumer" in act for act in acts)
    assert has_consumer_act, f"Expected Consumer Protection Act in retrieved acts: {acts}"


def test_rights_agent_excludes_deactivated_documents():
    """Verify chunks with is_active=False are filtered out during retrieval."""
    mock_qdrant = MagicMock()
    mock_point_active = MagicMock()
    mock_point_active.payload = {
        "act_name": "Active Consumer Act 2019",
        "section": "Sec 35",
        "content": "Active content",
        "citation": "Active Act Sec 35",
        "is_active": True,
    }
    mock_point_active.score = 0.85

    mock_point_inactive = MagicMock()
    mock_point_inactive.payload = {
        "act_name": "Deactivated Consumer Act 1986",
        "section": "Sec 12",
        "content": "Old repealed content",
        "citation": "Repealed Act",
        "is_active": False,
    }
    mock_point_inactive.score = 0.95

    mock_response = MagicMock()
    mock_response.points = [mock_point_inactive, mock_point_active]
    mock_qdrant.query_points.return_value = mock_response

    agent = RightsAgent(qdrant_client=mock_qdrant)
    results = agent.retrieve_relevant_chunks("consumer rights complaint", top_k=2)

    assert len(results) == 1
    assert results[0][0]["act_name"] == "Active Consumer Act 2019"
    assert results[0][0]["is_active"] is True


# ── Test 4: Rights Agent Answer Generation & Template Fallback ────────────────

@pytest.mark.asyncio
async def test_rights_agent_template_synthesis_selects_relevant_chunk():
    """Verify template synthesis picks the most keyword-relevant chunk when LLM fails."""
    agent = RightsAgent()
    chunks = [
        {
            "topic": "Tenant Security Deposit",
            "act_name": "Model Tenancy Act 2021",
            "section": "Section 11",
            "title": "Security Deposit",
            "content": "Tenant security deposit refund rules.",
            "citation": "Model Tenancy Act 2021, Section 11",
        },
        {
            "topic": "Consumer Protection and Defective Products",
            "act_name": "Consumer Protection Act 2019",
            "section": "Section 35",
            "title": "Filing a Complaint for Defective Goods",
            "content": "Consumers may claim compensation for defective products causing damage before the District Commission.",
            "citation": "Consumer Protection Act 2019, Section 35",
        },
    ]

    answer = agent._synthesize_template_answer(Q1_DEFECTIVE_PRODUCT, chunks)
    assert "Consumer Protection Act 2019" in answer
    assert "Model Tenancy Act 2021" not in answer
    assert "[Source: Consumer Protection Act 2019, Section 35]" in answer


@pytest.mark.asyncio
async def test_rights_agent_explain_rights_attaches_citation():
    """Verify explain_rights validates and attaches citations."""
    agent = RightsAgent()
    with patch.object(
        agent,
        "_generate_answer",
        new=AsyncMock(return_value="Under consumer law you have a right to safety and replacement."),
    ):
        text, citations, status = await agent.explain_rights(Q1_DEFECTIVE_PRODUCT)
        assert status == "ok"
        assert len(citations) > 0
        assert "[Source:" in text


# ── Test 5: End-to-End Orchestrator Execution for Both Queries ────────────────

@pytest.mark.asyncio
async def test_orchestrator_handles_q1_defective_product():
    """Verify full orchestrator handles Q1 without unclear fallback."""
    state = {
        "query": Q1_DEFECTIVE_PRODUCT,
        "session_id": "test-q1",
        "conversation_history": [],
        "intents": [],
        "confidence": 0.0,
        "scratchpad": [],
        "final_response": "",
        "status": "ok",
        "llm_calls_used": 0,
        "llm_calls_limit": 10,
        "retry_target": None,
        "retry_counts": {},
        "retry_feedback": "",
        "contradiction_note": None,
        "confirmed_outputs": None,
    }

    result = await orchestrator_graph.ainvoke(state)
    assert result["status"] == "ok"
    assert AgentIntent.RIGHTS in result["intents"]
    assert len(result["scratchpad"]) > 0
    assert "[Source:" in result["final_response"]


@pytest.mark.asyncio
async def test_orchestrator_handles_q2_consumer_commission():
    """Verify full orchestrator handles Q2 and returns citations."""
    state = {
        "query": Q2_CONSUMER_COMMISSION,
        "session_id": "test-q2",
        "conversation_history": [],
        "intents": [],
        "confidence": 0.0,
        "scratchpad": [],
        "final_response": "",
        "status": "ok",
        "llm_calls_used": 0,
        "llm_calls_limit": 10,
        "retry_target": None,
        "retry_counts": {},
        "retry_feedback": "",
        "contradiction_note": None,
        "confirmed_outputs": None,
    }

    result = await orchestrator_graph.ainvoke(state)
    assert result["status"] == "ok"
    assert AgentIntent.RIGHTS in result["intents"]
    assert len(result["scratchpad"]) > 0
    assert "[Source:" in result["final_response"]


# ── Test 6: API Route Integration with Mocked LLM ────────────────────────────

def test_api_query_endpoint_handles_q1_with_mock_auth():
    """Verify POST /api/v1/query returns HTTP 200 with verified status & citations."""
    token = create_access_token("test_user_777", "citizen")
    client = TestClient(app)

    response = client.post(
        "/api/v1/query",
        json={"query": Q1_DEFECTIVE_PRODUCT},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "rights" in data["intents"]
    assert len(data["agents"]) >= 1
    assert data["citations"] is not None
    assert len(data["citations"]) > 0
