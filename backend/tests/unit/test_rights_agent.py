"""
=============================================================================
LEXIS Unit Tests — Module 5: Rights Explainer Agent (RAG + Qdrant)
=============================================================================
Verifies:
  1. Ingestion of starter legal dataset into Qdrant vector DB.
  2. RAG retrieval and answer drafting for a known question from the seed DB.
  3. Response includes a citation to a real, existing source document/section.
  4. Honest safeguard fallback when query has no confident match (no hallucination).
  5. Minimal output check citation validation logic.
  6. Orchestrator multi-intent routing integration (rights RAG + concurrent placeholder).
"""

import pytest
from unittest.mock import patch

from db.qdrant_client import get_qdrant_client
from services.rag.ingestion import seed_starter_knowledge_base
from agents.rights_agent.agent import RightsAgent, RIGHTS_SAFEGUARD_FALLBACK
from agents.orchestrator.agent import build_orchestrator_graph
from agents.orchestrator.state import AgentIntent


@pytest.fixture
def test_qdrant_client():
    """Provides an isolated, seeded in-memory Qdrant client for testing."""
    client = get_qdrant_client(force_in_memory=True)
    seed_starter_knowledge_base(client=client, force_recreate=True, test_mode=True)
    return client


@pytest.fixture
def rights_agent(test_qdrant_client):
    """Provides a RightsAgent instance backed by the seeded in-memory Qdrant DB."""
    from services.rag.embedder import BGEM3Embedder
    embedder = BGEM3Embedder(test_mode=True)
    return RightsAgent(qdrant_client=test_qdrant_client, embedder=embedder)


@pytest.mark.asyncio
async def test_rights_agent_known_question_returns_real_citation(rights_agent):
    """
    Test 1: Ask a known question from the seeded knowledge base and confirm
    the response includes a citation to a real, existing source in the DB.
    """
    query = "What is the timeline for a landlord to refund a tenant security deposit?"

    response_text, citations, status = await rights_agent.explain_rights(query)

    assert status == "ok"
    assert len(citations) > 0, "Response must include at least one retrieved citation"

    # Verify citation references the real source Act/Section in the DB
    assert any("Model Tenancy Act" in c or "Rent Control" in c for c in citations)
    assert "[Source:" in response_text or any(c in response_text for c in citations)


@pytest.mark.asyncio
async def test_rights_agent_posh_act_query_citations(rights_agent):
    """
    Test 2: Ask about workplace sexual harassment reporting (POSH Act) and verify citation.
    """
    query = "What is the rule for reporting workplace harassment under POSH Act?"

    response_text, citations, status = await rights_agent.explain_rights(query)

    assert status == "ok"
    assert len(citations) > 0
    assert any("POSH Act" in c for c in citations)


@pytest.mark.asyncio
async def test_rights_agent_safeguard_fallback_on_unverified_query(rights_agent):
    """
    Test 3: Ask an unverified question outside the knowledge base.
    Confirm the agent refuses to hallucinate legal claims or section numbers.
    """
    query = "What is the penalty for flying a spacecraft without a license under Martian Space Law?"

    # Force retrieval to return no hits by searching an irrelevant string with high threshold
    with patch.object(rights_agent, 'retrieve_relevant_chunks', return_value=[]):
        response_text, citations, status = await rights_agent.explain_rights(query)

        assert status == "no_confident_match"
        assert response_text == RIGHTS_SAFEGUARD_FALLBACK
        assert len(citations) == 0


def test_minimal_output_check_attaches_missing_citation(rights_agent):
    """
    Test 4: Verify minimal output check — if draft answer lacks a citation,
    the validator attaches the primary citation.
    """
    draft_without_citation = "Tenants have a right to get their security deposit back within 30 days."
    valid_citations = ["Model Tenancy Act 2021, Section 13 & 21"]

    validated = rights_agent._validate_and_attach_citation(draft_without_citation, valid_citations)

    assert "[Source: Model Tenancy Act 2021, Section 13 & 21]" in validated


@pytest.mark.asyncio
async def test_orchestrator_routes_rights_intent_to_rag_agent(test_qdrant_client):
    """
    Test 5: Verify orchestrator multi-intent dispatch where 'rights' intent
    uses real RightsAgent RAG while 'filing' uses placeholder.
    """
    from services.rag.embedder import BGEM3Embedder
    embedder = BGEM3Embedder(test_mode=True)
    test_agent = RightsAgent(qdrant_client=test_qdrant_client, embedder=embedder)

    graph = build_orchestrator_graph()

    initial_state = {
        "query": "What are tenant security deposit refund rights and how do I file a complaint?",
        "history": [],
        "intents": [],
        "confidence": 0.0,
        "scratchpad": [],
        "final_response": "",
        "status": "pending",
        "llm_calls_used": 0,
        "llm_calls_limit": 10,
        "retry_target": None,
    }

    with patch("agents.rights_agent.agent.get_rights_agent", return_value=test_agent), \
         patch("agents.orchestrator.agent._call_llm_classifier", return_value=([AgentIntent.RIGHTS, AgentIntent.FILING], 0.95)):
        final_state = await graph.ainvoke(initial_state)

        assert final_state["status"] == "ok"
        scratchpad = final_state["scratchpad"]
        assert len(scratchpad) == 2, f"Expected 2 scratchpad outputs, got {len(scratchpad)}"

        rights_output = next(r for r in scratchpad if r["intent"] == "rights")
        filing_output = next(r for r in scratchpad if r["intent"] == "filing")

        assert rights_output["status"] == "ok"
        assert filing_output["status"] == "ok"
        assert "[Source:" in rights_output["output"] or "Model Tenancy Act" in rights_output["output"]
        assert "Filing Guide" in filing_output["output"] or "Legal Demand Notice" in filing_output["output"]

        # Verify metadata is truthful
        assert rights_output["metadata"]["agent"] == "RightsExplainerAgent"
        assert rights_output["metadata"]["model"] == "gpt-4o-mini / BGE-M3"
        assert len(rights_output["metadata"]["citations"]) > 0
        assert filing_output["metadata"]["agent"] == "FilingGuideAgent"
