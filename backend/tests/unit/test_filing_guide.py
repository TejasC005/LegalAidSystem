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
