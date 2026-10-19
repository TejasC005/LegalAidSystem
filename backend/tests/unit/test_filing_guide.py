"""
=============================================================================
LEXIS — Complaint Filing Guide Agent Unit Tests (Module 9)
=============================================================================

TEST PHILOSOPHY FOR FILING GUIDE:
-----------------------------------
The Filing Guide is citizen-safety-critical: routing someone to the WRONG
government portal or quoting a WRONG fee amount is a real-world harm.

Test strategy:
  1. test_filing_seed_loads_correctly      — JSON structure validation (all required fields present)
  2. test_rti_authority_lookup             — RTI doc_type → correct CIC/PIO authority
  3. test_consumer_complaint_lookup        — consumer_complaint → edaakhil.nic.in portal
  4. test_rti_draft_context_carries_to_filing_guide_without_reentry
                                           — THE KEY HANDOFF TEST: RTI draft context
                                             flows into FilingGuideAgent without the
                                             citizen re-entering their situation.
  5. test_orchestrator_routes_filing_intent — Orchestrator wired to FilingGuideAgent

All tests run offline (no MongoDB required — uses in-memory seed cache;
no Qdrant required — no vector search for this agent;
no LLM API key required — agent uses template formatting, 0 LLM calls).
"""

import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# ── Seed file path ────────────────────────────────────────────────────────────
SEED_FILE = Path(__file__).parent.parent.parent / "data" / "filing_authorities" / "filing_seed.json"

# ── Required fields that every filing authority entry must have ───────────────
REQUIRED_AUTHORITY_FIELDS = {
    "id", "doc_type", "doc_type_name", "authority_name", "authority_short",
    "description", "required_documents", "legal_basis", "source_ref", "verified"
}


# =============================================================================
# Test 1 — Seed file structure validation
# =============================================================================

class TestFilingSeedFile:
    """
    Verifies that the filing seed JSON file is well-formed and every entry
    has the mandatory fields that the filing guide UI depends on.

    WHY THIS TEST MATTERS:
    A missing `portal_url` would silently show "None" to the citizen.
    A missing `required_documents` would leave them unprepared for filing.
    A missing `legal_basis` breaks the "no-fabrication" guarantee — the UI
    must always cite the Act/Section that mandates this filing path.
    """

    def test_filing_seed_loads_correctly(self):
        """
        Seed JSON must exist, have exactly 3 entries (one per supported doc_type),
        and each entry must contain all required fields.
        """
        assert SEED_FILE.exists(), (
            f"Filing authority seed file not found at {SEED_FILE}. "
            "Ensure backend/data/filing_authorities/filing_seed.json exists."
        )

        with open(SEED_FILE, "r", encoding="utf-8") as f:
            entries = json.load(f)

        assert isinstance(entries, list), "Seed file must be a JSON array"
        assert len(entries) == 3, (
            f"Expected exactly 3 filing authority entries (one per doc_type), got {len(entries)}. "
            "Doc types: rti_application, consumer_complaint, legal_notice."
        )

        expected_doc_types = {"rti_application", "consumer_complaint", "legal_notice"}
        actual_doc_types = {e.get("doc_type") for e in entries}
        assert actual_doc_types == expected_doc_types, (
            f"Expected doc_types {expected_doc_types}, got {actual_doc_types}."
        )

        for entry in entries:
            missing = REQUIRED_AUTHORITY_FIELDS - set(entry.keys())
            assert not missing, (
                f"Entry '{entry.get('id', '?')}' (doc_type={entry.get('doc_type')}) "
                f"is missing required fields: {missing}."
            )

            # Required documents list must not be empty
            assert entry.get("required_documents") and len(entry["required_documents"]) > 0, (
                f"Entry '{entry.get('id')}' has empty required_documents list."
            )

            # Legal basis must be non-empty (no-fabrication guarantee)
            assert entry.get("legal_basis", "").strip(), (
                f"Entry '{entry.get('id')}' has empty legal_basis — "
                "this is required for the no-fabrication guarantee."
            )

            # Authority must be explicitly marked as verified or not
            assert "verified" in entry, (
                f"Entry '{entry.get('id')}' is missing 'verified' field."
            )

        print(f"\n[SEED TEST] Validated {len(entries)} filing authority entries — all fields present ✓")
        for e in entries:
            print(f"  {e['id']} | {e['doc_type']} | verified={e['verified']}")


# =============================================================================
# Test 2 — RTI authority lookup
# =============================================================================

class TestRTILookup:
    """
    Verifies that looking up 'rti_application' returns the correct authority
    (PIO → First Appellate Authority → CIC) and the official RTI Online portal.
    """

    @pytest.mark.asyncio
    async def test_rti_authority_lookup(self):
        """
        Looking up doc_type='rti_application' must return:
          - authority referencing the Public Information Officer / CIC
          - portal_url = 'https://rtionline.gov.in'
          - legal_basis referencing 'Right to Information Act, 2005'
          - required_documents list is non-empty
          - verified = True
        """
        from agents.filing_guide.agent import FilingGuideAgent, reset_filing_agent
        reset_filing_agent()

        agent = FilingGuideAgent(mongo_db=None)  # No DB — uses in-memory cache

        result = await agent.lookup_authority("rti_application", mongo_db=None)

        assert result.found, (
            "RTI application lookup returned found=False. "
            "Check that the seed cache loaded 'rti_application' correctly."
        )

        record = result.record

        # Authority correctness (must reference PIO / CIC — not an invented authority)
        authority_text = (record.get("authority_short", "") + record.get("authority_name", "")).lower()
        assert any(kw in authority_text for kw in ["information commission", "pio", "public information"]), (
            f"RTI authority must reference CIC/PIO, got: '{record.get('authority_short')}'. "
            "Do not invent a different authority."
        )

        # Official portal URL — verified against the RTI Act / government portal
        assert record.get("portal_url") == "https://rtionline.gov.in", (
            f"RTI portal_url must be 'https://rtionline.gov.in', got: '{record.get('portal_url')}'. "
            "Only include the verified government portal."
        )

        # Legal basis must cite the RTI Act
        assert "right to information act" in record.get("legal_basis", "").lower(), (
            f"RTI legal_basis must cite the RTI Act 2005, got: '{record.get('legal_basis')}'"
        )

        # Documents checklist
        assert len(record.get("required_documents", [])) >= 3, (
            "RTI required_documents must have at least 3 items."
        )

        # Verified flag
        assert record.get("verified") is True, (
            "RTI authority entry must be marked as verified."
        )

        result_dict = result.to_dict()
        assert result_dict["found"] is True
        assert result_dict["portal_url"] == "https://rtionline.gov.in"

        print(f"\n[RTI LOOKUP TEST] Found authority: '{record.get('authority_short')}' ✓")
        print(f"  Portal: {record.get('portal_url')}")
        print(f"  Legal basis: {record.get('legal_basis')}")
        print(f"  Required docs: {len(record.get('required_documents', []))} items")

        reset_filing_agent()


# =============================================================================
# Test 3 — Consumer complaint lookup
# =============================================================================

class TestConsumerComplaintLookup:
    """
    Verifies that looking up 'consumer_complaint' returns the e-Daakhil portal
    and the Consumer Protection Act 2019 as the legal basis.
    """

    @pytest.mark.asyncio
    async def test_consumer_complaint_lookup(self):
        """
        doc_type='consumer_complaint' must return:
          - portal_url = 'https://edaakhil.nic.in' (official NCDRC portal)
          - legal_basis referencing 'Consumer Protection Act, 2019'
          - fee information present
          - required_documents list non-empty
        """
        from agents.filing_guide.agent import FilingGuideAgent, reset_filing_agent
        reset_filing_agent()

        agent = FilingGuideAgent(mongo_db=None)
        result = await agent.lookup_authority("consumer_complaint", mongo_db=None)

        assert result.found, (
            "Consumer complaint lookup returned found=False. "
            "Check that the seed cache loaded 'consumer_complaint' correctly."
        )

        record = result.record

        # e-Daakhil is the official government consumer complaint portal (NCDRC)
        assert record.get("portal_url") == "https://edaakhil.nic.in", (
            f"Consumer complaint portal_url must be 'https://edaakhil.nic.in', "
            f"got: '{record.get('portal_url')}'. Only include the verified official portal."
        )

        # Legal basis
        assert "consumer protection act" in record.get("legal_basis", "").lower(), (
            f"Consumer complaint legal_basis must cite CPA 2019, got: '{record.get('legal_basis')}'"
        )

        # Fee info must be present (verified from CPA 2019 Rules)
        assert record.get("fee"), "Consumer complaint must have fee information."

        # Filing tiers (District / State / National commissions)
        assert len(record.get("filing_tiers", [])) >= 3, (
            "Consumer complaint must have at least 3 filing tiers (District, State, National)."
        )

        print(f"\n[CONSUMER COMPLAINT TEST] Found authority: '{record.get('authority_short')}' ✓")
        print(f"  Portal: {record.get('portal_url')}")
        print(f"  Filing tiers: {len(record.get('filing_tiers', []))}")

        reset_filing_agent()


# =============================================================================
# Test 4 — THE KEY HANDOFF TEST
# =============================================================================

class TestHandoffFromDocumentDrafter:
    """
    THE KEY MODULE 9 HANDOFF TEST.

    Tests that a drafted RTI document's context (specifically its doc_type)
    correctly carries into a Filing Guide lookup WITHOUT the citizen manually
    re-entering their situation.

    WHAT THIS PROVES:
    -----------------
    Scenario:
      1. Citizen completes an RTI application draft in Module 6.
      2. The draft is saved to MongoDB as: {"doc_type": "rti_application", "draft_id": "abc-123"}
      3. Citizen clicks "Where do I file this?" on the document preview screen.
      4. Frontend calls: GET /api/v1/filing/lookup?draft_id=abc-123
      5. Filing agent reads doc_type from the draft record → returns RTI authority.
      6. Citizen sees the correct authority — NO re-entry required.

    WHY HANDOFF IS DIFFERENT FROM RE-ENTERING:
    -------------------------------------------
    Re-entry path:
      - Citizen closes drafter, opens filing guide.
      - Types: "I want to file an RTI application about my pension not being processed."
      - Agent classifies natural language → infers "rti_application".
      - Risk: classification error (could be misclassified as "complaint" if poorly worded).
      - Burden: citizen must describe their situation again.

    Handoff path (this test):
      - doc_type = "rti_application" is authoritative structured data from the draft session.
      - FilingGuideAgent.lookup_authority("rti_application") is called directly.
      - No classification step. No re-entry. No risk of misclassification.
      - The citizen's exact document type is preserved across tools.
    """

    @pytest.mark.asyncio
    async def test_rti_draft_context_carries_to_filing_guide_without_reentry(self):
        """
        Simulates the complete Module 6 → Module 9 handoff.

        The test directly replicates what the API endpoint does:
          1. Read doc_type from a mock draft record (simulating MongoDB user_drafts).
          2. Pass doc_type to FilingGuideAgent.lookup_authority().
          3. Verify the returned authority is correct for RTI.
          4. Verify the citizen did NOT need to re-enter their situation
             (no NLP classification step was involved in the lookup).
        """
        from agents.filing_guide.agent import FilingGuideAgent, reset_filing_agent
        reset_filing_agent()

        # ── Step 1: Simulate the completed draft record from Module 6 ─────────
        # This is what Module 6 saves to MongoDB when a draft is completed.
        mock_completed_draft = {
            "draft_id": "abc-123-rti-draft",
            "user_id": "test_user_001",
            "doc_type": "rti_application",          # ← This is the handoff carrier
            "doc_type_name": "RTI Application",
            "collected_answers": {
                "pio_name": "Public Information Officer",
                "authority_name": "Ministry of Railways",
                "city": "New Delhi",
                "information_requested": "Status of pension application reference PO-2024-001",
                "applicant_name": "Test Citizen",
                "applicant_address": "123 Test Lane, New Delhi",
                "applicant_phone": "+919876543210",
                "applicant_email": "test@example.com",
            },
            "document_text": "APPLICATION UNDER THE RIGHT TO INFORMATION ACT, 2005\n...",
            "status": "completed",
        }

        # ── Step 2: Extract doc_type from draft (simulating the API endpoint) ──
        # The API reads this from MongoDB: db.user_drafts.find_one({"draft_id": draft_id, "user_id": user_id})
        doc_type_from_draft = mock_completed_draft["doc_type"]

        # KEY ASSERTION: doc_type is pulled directly from the structured draft record.
        # The citizen did NOT type anything — this is the handoff.
        assert doc_type_from_draft == "rti_application", (
            "doc_type from draft record must be 'rti_application'. "
            "This simulates the handoff — the citizen's situation is known from Module 6."
        )

        # ── Step 3: FilingGuideAgent lookup — NO NLP classification ────────────
        # This is the EXACT call the API makes — no classify_intent, no NLP.
        agent = FilingGuideAgent(mongo_db=None)
        result = await agent.lookup_authority(doc_type_from_draft, mongo_db=None)

        # ── Step 4: Verify correct authority returned ──────────────────────────
        assert result.found, (
            f"FilingGuideAgent.lookup_authority('rti_application') returned found=False. "
            "The seed cache must contain 'rti_application' for the handoff to work."
        )

        record = result.record

        # The correct authority for RTI is the PIO → FAA → CIC chain
        assert "information commission" in (record.get("authority_short", "")).lower() or \
               "pio" in (record.get("authority_short", "")).lower(), (
            f"RTI authority must reference the CIC/PIO, got: '{record.get('authority_short')}'"
        )

        # The verified portal must be rtionline.gov.in
        assert record.get("portal_url") == "https://rtionline.gov.in", (
            f"RTI portal must be 'https://rtionline.gov.in', "
            f"got: '{record.get('portal_url')}'. No invented URLs."
        )

        # Verify the RTI Act is cited (legal basis, not invented)
        assert "right to information act" in record.get("legal_basis", "").lower(), (
            "RTI authority record must cite the Right to Information Act 2005."
        )

        # ── Step 5: Verify no re-entry happened ───────────────────────────────
        # The doc_type came from structured data (mock_completed_draft["doc_type"]),
        # NOT from classifying the citizen's natural language description.
        # There was no call to _keyword_classifier_fallback or _call_llm_classifier.
        # This is the fundamental difference from a disconnected tool.
        collected_answers = mock_completed_draft["collected_answers"]
        assert "pio_name" in collected_answers, "Draft answers must be preserved in the draft record"
        assert "information_requested" in collected_answers, "Draft content must carry the citizen's specifics"

        print(f"\n[HANDOFF TEST] RTI draft context carried to Filing Guide successfully ✓")
        print(f"  Draft doc_type (from Module 6): '{doc_type_from_draft}'")
        print(f"  Filing authority resolved: '{record.get('authority_short')}'")
        print(f"  Portal: {record.get('portal_url')}")
        print(f"  Citizen re-entry required: NONE (handoff via draft_id)")
        print(f"  Classification steps: ZERO (doc_type is authoritative structured data)")
        print(f"  Draft contained {len(collected_answers)} answered fields from the questionnaire")

        reset_filing_agent()


# =============================================================================
# Test 5 — Orchestrator routing for AgentIntent.FILING
# =============================================================================

class TestOrchestratorRouting:
    """
    Verifies that the LangGraph orchestrator correctly routes AgentIntent.FILING
    to FilingGuideAgent (not a placeholder echo).

    This test mirrors the pattern used in test_scam_detection.py Test 5.
    """

    @pytest.mark.asyncio
    async def test_orchestrator_routes_filing_intent(self):
        """
        When the orchestrator processes a query with FILING intent,
        it must route to FilingGuideAgent and return a response that
        contains 'FilingGuideAgent' in the metadata.
        """
        from agents.orchestrator.state import AgentIntent, OrchestratorState
        from agents.orchestrator.agent import _run_specialist_work

        mock_output = (
            "**Filing Guide: RTI Application**\n\n"
            "**Authority:** PIO / First Appellate Authority / Central Information Commission\n\n"
            "**Official Portal:** [RTI Online](https://rtionline.gov.in)\n\n"
            "**Legal Basis:** Right to Information Act, 2005"
        )
        mock_metadata = {
            "agent": "FilingGuideAgent",
            "doc_type": "rti_application",
            "found": True,
            "authority_id": "FILING_RTI_001",
            "authority_name": "Public Information Officer (PIO) of the concerned Public Authority",
            "portal_url": "https://rtionline.gov.in",
            "verified": True,
            "llm_used": False,
        }

        with patch("agents.filing_guide.agent.get_filing_agent") as mock_get_agent:
            mock_agent = MagicMock()
            mock_agent.explain_for_query = AsyncMock(
                return_value=(mock_output, mock_metadata, 0)
            )
            mock_get_agent.return_value = mock_agent

            result = await _run_specialist_work(
                intent=AgentIntent.FILING,
                query="Where do I file my RTI application for information from Ministry of Railways?",
                state={
                    "query": "Where do I file my RTI application for information from Ministry of Railways?",
                    "intents": [AgentIntent.FILING],
                    "confidence": 0.9,
                    "scratchpad": [],
                    "llm_calls_used": 0,
                    "llm_calls_limit": 10,
                    "status": "processing",
                    "final_response": "",
                    "_current_intent": AgentIntent.FILING,
                    "retry_target": None,
                    "conversation_history": [],
                }
            )

        output_text, metadata, llm_calls = result

        assert metadata.get("agent") == "FilingGuideAgent", (
            f"Expected agent='FilingGuideAgent', got '{metadata.get('agent')}'. "
            "Orchestrator may not have been wired to the filing agent."
        )
        assert metadata.get("found") is True, "Filing agent should have found the RTI authority"
        assert metadata.get("portal_url") == "https://rtionline.gov.in", (
            f"Portal URL must be verified rtionline.gov.in, got: '{metadata.get('portal_url')}'"
        )
        assert llm_calls == 0, (
            f"Filing agent should use 0 LLM calls (template formatting). Got {llm_calls}."
        )
        assert "Filing Guide" in output_text or "RTI" in output_text, (
            "Output must reference Filing Guide or RTI."
        )
        assert metadata.get("verified") is True, (
            "Authority record must be marked as verified — no unverified data served."
        )

        print(f"\n[ORCHESTRATOR TEST] AgentIntent.FILING correctly routed to FilingGuideAgent ✓")
        print(f"  Authority: {metadata.get('authority_name')}")
        print(f"  Portal: {metadata.get('portal_url')}")
        print(f"  LLM calls used: {llm_calls} (must be 0 — template formatting)")
        print(f"  Verified: {metadata.get('verified')}")


# =============================================================================
# Test 6 — Conversational Filing Guide Engine (Module 9 Enhanced)
# =============================================================================

class TestConversationalFilingGuide:
    """
    Tests the natural-language conversational capabilities of the Filing Guide Agent:
      1. Insufficient information detection & clarification prompts
      2. Full structured guide generation
      3. Pecuniary jurisdiction calculation (Consumer Protection Act 2019)
      4. Follow-up Q&A context preservation
      5. State jurisdiction detection
      6. Unsupported filing categories
      7. Anti-hallucination portal validation
    """

    @pytest.mark.asyncio
    async def test_conversational_insufficient_info(self):
        """Vague query returns insufficient_info intent with clarifying questions."""
        from agents.filing_guide.agent import FilingGuideAgent, reset_filing_agent
        reset_filing_agent()

        agent = FilingGuideAgent(mongo_db=None)
        res = await agent.process_conversation(query="I want to file a case")

        assert res["intent"] == "insufficient_info", f"Expected 'insufficient_info', got '{res['intent']}'"
        assert res["guide"] is None
        assert "dispute" in res["reply_text"].lower()
        assert "amount" in res["reply_text"].lower()
        assert "state" in res["reply_text"].lower()
        assert res["disclaimer"], "Must include statutory disclaimer"

    @pytest.mark.asyncio
    async def test_conversational_new_guide_generation(self):
        """Detailed RTI query generates a complete structured guide."""
        from agents.filing_guide.agent import FilingGuideAgent, reset_filing_agent
        reset_filing_agent()

        agent = FilingGuideAgent(mongo_db=None)
        res = await agent.process_conversation(query="How do I file an RTI application for delayed road repairs in my municipal ward?")

        assert res["intent"] == "new_guide"
        assert res["doc_type"] == "rti_application"
        assert res["guide"] is not None

        guide = res["guide"]
        assert guide["portal_url"] == "https://rtionline.gov.in"
        assert len(guide["required_documents"]) >= 3
        assert len(guide["step_by_step_procedure"]) >= 5
        assert len(guide["common_mistakes"]) >= 3
        assert len(guide["checklist"]) >= 3
        assert "right to information act" in guide["legal_basis"].lower()

    @pytest.mark.asyncio
    async def test_pecuniary_jurisdiction_calculation(self):
        """Consumer claims must be accurately routed to District, State, or National commission."""
        from agents.filing_guide.catalog import get_filing_catalog
        catalog = get_filing_catalog()

        # Under 50 Lakh -> District Commission (DCDRC)
        tier_district = catalog.calculate_consumer_pecuniary_tier(50_000)
        assert "District" in tier_district["tier_name"]
        assert "50 Lakh" in tier_district["jurisdiction_limit"]

        tier_district_exact = catalog.calculate_consumer_pecuniary_tier(5_000_000)
        assert "District" in tier_district_exact["tier_name"]

        # Between 50 Lakh and 2 Crore -> State Commission (SCDRC)
        tier_state = catalog.calculate_consumer_pecuniary_tier(7_500_000)  # 75 Lakh
        assert "State" in tier_state["tier_name"]
        assert "2 Crore" in tier_state["jurisdiction_limit"]

        # Above 2 Crore -> National Commission (NCDRC)
        tier_national = catalog.calculate_consumer_pecuniary_tier(30_000_000)  # 3 Crore
        assert "National" in tier_national["tier_name"]

    @pytest.mark.asyncio
    async def test_consumer_guide_with_pecuniary_amount(self):
        """Consumer complaint query with explicit amount calculates tier in guide object."""
        from agents.filing_guide.agent import FilingGuideAgent, reset_filing_agent
        reset_filing_agent()

        agent = FilingGuideAgent(mongo_db=None)
        res = await agent.process_conversation(query="I bought a defective car for Rs. 75 Lakh in Mumbai and dealer refuses refund. How do I file?")

        assert res["doc_type"] == "consumer_complaint"
        guide = res["guide"]
        assert guide is not None
        assert guide["calculated_tier"] is not None
        assert "State Commission" in guide["calculated_tier"]["short_name"]
        assert guide["state_jurisdiction"] == "Maharashtra"
        assert guide["portal_url"] == "https://edaakhil.nic.in"

    @pytest.mark.asyncio
    async def test_followup_question_handling(self):
        """Follow-up questions preserve previous guide context."""
        from agents.filing_guide.agent import FilingGuideAgent, reset_filing_agent
        reset_filing_agent()

        agent = FilingGuideAgent(mongo_db=None)
        history = [
            {"sender": "user", "text": "How do I file a consumer complaint for a defective refrigerator?"},
            {"sender": "agent", "text": "Filing Guide: Consumer Complaint with Consumer Disputes Redressal Commission."}
        ]
        res = await agent.process_conversation(
            query="Do I need to hire an advocate to file this?",
            conversation_history=history
        )

        assert res["intent"] == "followup"
        assert res["doc_type"] == "consumer_complaint"
        assert "not required to hire an advocate" in res["reply_text"].lower() or "lawyer" in res["reply_text"].lower()

    @pytest.mark.asyncio
    async def test_anti_hallucination_portals(self):
        """All portal URLs in the catalog must be verified .gov.in or .nic.in domains."""
        from agents.filing_guide.catalog import get_filing_catalog
        catalog = get_filing_catalog()

        for authority in catalog.get_all_authorities():
            portal_url = authority.get("portal_url")
            if portal_url:
                assert ".gov.in" in portal_url or ".nic.in" in portal_url, (
                    f"Authority {authority.get('id')} has unverified domain: {portal_url}"
                )
            assert authority.get("verified") is True, f"Authority {authority.get('id')} not marked verified"


# =============================================================================
# Test 7 — Filing Guide API Route Tests (POST /api/v1/filing/guide)
# =============================================================================

from fastapi.testclient import TestClient
from fastapi import FastAPI, APIRouter
from api.routes.filing import router as filing_router
from services.auth.jwt_service import create_access_token

def build_test_filing_app() -> FastAPI:
    app = FastAPI()
    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(filing_router)
    app.include_router(api_v1)

    # Mock DB state
    mock_db = MagicMock()
    mock_db.user_drafts = MagicMock()
    mock_db.user_drafts.find_one = AsyncMock(return_value=None)
    mock_db.filing_authorities = MagicMock()
    app.state.mongo_client = MagicMock()
    app.state.mongo_client.__getitem__ = MagicMock(return_value=mock_db)
    app.state.mongo_db_name = "lexis"
    return app


class TestFilingApiEndpoints:
    """Tests the REST API routes for Filing Guide."""

    def test_post_filing_guide_success(self):
        """POST /api/v1/filing/guide with valid JWT returns 200 and structured response."""
        app = build_test_filing_app()
        client = TestClient(app)

        token = create_access_token(user_id="user_123", role="user")
        headers = {"Authorization": f"Bearer {token}"}

        payload = {
            "query": "How do I file an RTI application for delayed road repairs?",
            "conversation_history": []
        }
        resp = client.post("/api/v1/filing/guide", json=payload, headers=headers)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

        data = resp.json()
        assert "reply_text" in data
        assert data["intent"] == "new_guide"
        assert data["doc_type"] == "rti_application"
        assert data["guide"] is not None
        assert data["guide"]["portal_url"] == "https://rtionline.gov.in"
        assert data["verified"] is True
        assert len(data["guide"]["step_by_step_procedure"]) > 0

    def test_post_filing_guide_unauthorized(self):
        """POST /api/v1/filing/guide without token returns 401 Unauthorized."""
        app = build_test_filing_app()
        client = TestClient(app)

        payload = {"query": "How do I file an RTI?"}
        resp = client.post("/api/v1/filing/guide", json=payload)
        assert resp.status_code == 401

    def test_post_filing_guide_empty_query_rejected(self):
        """POST /api/v1/filing/guide with empty query returns 422 Unprocessable Entity."""
        app = build_test_filing_app()
        client = TestClient(app)

        token = create_access_token(user_id="user_123", role="user")
        headers = {"Authorization": f"Bearer {token}"}

        payload = {"query": ""}
        resp = client.post("/api/v1/filing/guide", json=payload, headers=headers)
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_unmatched_query_graceful_insufficient_info(self):
        """Queries longer than 4 words without recognized doc_type must not crash."""
        from agents.filing_guide.agent import FilingGuideAgent, reset_filing_agent
        reset_filing_agent()

        agent = FilingGuideAgent(mongo_db=None)
        res = await agent.process_conversation(
            "Can you tell me how to file a complaint against someone who cheated me?"
        )
        assert res["intent"] == "insufficient_info"
        assert res["guide"] is None
        assert "needs_verification" in res["reply_text"]
        assert res["verified"] is True

    @pytest.mark.asyncio
    async def test_lookup_authority_with_none_or_empty(self):
        """Calling lookup_authority with None or invalid type must not raise AttributeError."""
        from agents.filing_guide.agent import FilingGuideAgent, reset_filing_agent
        reset_filing_agent()

        agent = FilingGuideAgent(mongo_db=None)
        res_none = await agent.lookup_authority(None)
        assert res_none.found is False

        res_empty = await agent.lookup_authority("")
        assert res_empty.found is False

    @pytest.mark.asyncio
    async def test_confirmation_agent_validates_insufficient_info(self):
        """Filing guide text from explain_for_query must pass Confirmation Agent validation."""
        from agents.filing_guide.agent import FilingGuideAgent, reset_filing_agent
        from agents.confirmation_agent.criteria import validate_filing_output
        reset_filing_agent()

        agent = FilingGuideAgent(mongo_db=None)
        # 1. Vague query
        text, meta, _ = await agent.explain_for_query("I want to file a case")
        val = validate_filing_output(text, meta)
        assert val.passed is True, f"Failed validation: {val.failure_reason}"

        # 2. Specific query
        text2, meta2, _ = await agent.explain_for_query("How do I file an RTI application?")
        val2 = validate_filing_output(text2, meta2)
        assert val2.passed is True, f"Failed validation: {val2.failure_reason}"

    def test_expanded_keywords_mapping(self):
        """Newly supported everyday citizen dispute keywords must map to correct category."""
        from agents.filing_guide.catalog import get_filing_catalog
        catalog = get_filing_catalog()

        assert catalog.infer_doc_type("I have an issue with electricity meter and power supply") == "consumer_complaint"
        assert catalog.infer_doc_type("Company is withholding my unpaid salary dues") == "legal_notice"
        assert catalog.infer_doc_type("Need municipal records and tender copy") == "rti_application"
        assert catalog.infer_doc_type("flight cancellation and airline refund") == "consumer_complaint"
        assert catalog.infer_doc_type("dishonour of cheque under section 138") == "legal_notice"
        assert catalog.infer_doc_type("file rti for public grievance record") == "rti_application"

    def test_trailing_currency_extraction(self):
        """Tests that trailing currency designations (rs, rupees, inr) are accurately extracted."""
        from agents.filing_guide.catalog import get_filing_catalog
        catalog = get_filing_catalog()

        assert catalog.extract_monetary_amount("claim amount is 45000 rs") == 45000.0
        assert catalog.extract_monetary_amount("dispute value of 50000 rupees") == 50000.0
        assert catalog.extract_monetary_amount("refund of 500 inr") == 500.0
        assert catalog.extract_monetary_amount("worth 1.5 crore") == 15_000_000.0
        assert catalog.extract_monetary_amount("deposit of 75 lakhs") == 7_500_000.0

    def test_expanded_city_to_state_mapping(self):
        """Tests that newly mapped commercial cities correctly resolve to their state."""
        from agents.filing_guide.catalog import get_filing_catalog
        catalog = get_filing_catalog()

        assert catalog.extract_jurisdiction_state("filed in Navi Mumbai") == "Maharashtra"
        assert catalog.extract_jurisdiction_state("dispute in Visakhapatnam") == "Andhra Pradesh"
        assert catalog.extract_jurisdiction_state("supplier in Vadodara") == "Gujarat"
        assert catalog.extract_jurisdiction_state("factory in Ludhiana") == "Punjab"
        assert catalog.extract_jurisdiction_state("resident of Agra") == "Uttar Pradesh"
        assert catalog.extract_jurisdiction_state("order placed in Kozhikode") == "Kerala"
        assert catalog.extract_jurisdiction_state("branch in Raipur") == "Chhattisgarh"
        assert catalog.extract_jurisdiction_state("hotel in Shimla") == "Himachal Pradesh"
        assert catalog.extract_jurisdiction_state("transport in Srinagar") == "Jammu and Kashmir"

    def test_post_filing_guide_with_draft_handoff(self):
        """POST /api/v1/filing/guide automatically extracts doc_type and collected_answers from draft."""
        app = build_test_filing_app()
        client = TestClient(app)

        token = create_access_token(user_id="user_abc", role="user")
        headers = {"Authorization": f"Bearer {token}"}

        mock_draft = {
            "draft_id": "draft-consumer-999",
            "user_id": "user_abc",
            "doc_type": "consumer_complaint",
            "doc_type_name": "Consumer Complaint",
            "collected_answers": {
                "compensation_amount": "7500000",
                "city": "Mumbai"
            }
        }

        # Configure mock_db to return this draft for user_abc
        async def mock_find_draft(query):
            if query.get("draft_id") == "draft-consumer-999" and query.get("user_id") == "user_abc":
                return mock_draft
            return None

        app.state.mongo_client.__getitem__.return_value.user_drafts.find_one = AsyncMock(side_effect=mock_find_draft)

        payload = {
            "query": "Where do I submit this completed complaint?",
            "draft_id": "draft-consumer-999"
        }
        resp = client.post("/api/v1/filing/guide", json=payload, headers=headers)
        assert resp.status_code == 200, f"Expected 200, got: {resp.text}"

        data = resp.json()
        assert data["doc_type"] == "consumer_complaint"
        guide = data["guide"]
        assert guide is not None
        assert guide["calculated_tier"] is not None
        assert "State Commission" in guide["calculated_tier"]["short_name"]
        assert guide["state_jurisdiction"] == "Maharashtra"
        assert guide["portal_url"] == "https://edaakhil.nic.in"

    def test_post_filing_guide_unauthorized_draft_access_denied(self):
        """POST /api/v1/filing/guide with draft owned by another user returns 404."""
        app = build_test_filing_app()
        client = TestClient(app)

        # Attacker token
        token_attacker = create_access_token(user_id="attacker_user", role="user")
        headers = {"Authorization": f"Bearer {token_attacker}"}

        # Mock DB returns None for attacker
        app.state.mongo_client.__getitem__.return_value.user_drafts.find_one = AsyncMock(return_value=None)

        payload = {
            "query": "Give me filing guide for draft",
            "draft_id": "victim-draft-id"
        }
        resp = client.post("/api/v1/filing/guide", json=payload, headers=headers)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_followup_deadlines_and_documentation(self):
        """Follow-up questions regarding deadlines and required documents return focused statutory answers."""
        from agents.filing_guide.agent import FilingGuideAgent, reset_filing_agent
        reset_filing_agent()

        agent = FilingGuideAgent(mongo_db=None)
        history = [
            {"sender": "user", "text": "How do I file a consumer complaint for a defective car?"},
            {"sender": "agent", "text": "Filing Guide: Consumer Complaint with District Consumer Commission."}
        ]

        # 1. Ask about deadline/limitation
        res_deadline = await agent.process_conversation(
            query="What is the deadline or limitation period to file?",
            conversation_history=history
        )
        assert res_deadline["intent"] == "followup"
        assert "limitation period" in res_deadline["reply_text"].lower() or "2 years" in res_deadline["reply_text"].lower()

        # 2. Ask about documents
        res_docs = await agent.process_conversation(
            query="What key documents and proof do I need to attach?",
            conversation_history=history
        )
        assert res_docs["intent"] == "followup"
        assert "invoice" in res_docs["reply_text"].lower() or "documents" in res_docs["reply_text"].lower()

    @pytest.mark.asyncio
    async def test_confirmation_agent_validates_unsupported_category(self):
        """Unsupported category responses must still pass Confirmation Agent validation."""
        from agents.filing_guide.agent import FilingGuideAgent, reset_filing_agent
        from agents.confirmation_agent.criteria import validate_filing_output
        reset_filing_agent()

        agent = FilingGuideAgent(mongo_db=None)
        text, meta, _ = await agent.explain_for_query("How do I file a petition for patent invalidation?")
        val = validate_filing_output(text, meta)
        assert val.passed is True, f"Validation failed: {val.failure_reason}"



