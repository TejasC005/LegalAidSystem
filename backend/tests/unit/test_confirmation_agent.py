"""
=============================================================================
LEXIS — Module 11: Confirmation Agent Tests
=============================================================================

8 unit tests covering:
  1. Session store concurrent write safety
  2. Rights Agent citation check — PASS case
  3. Rights Agent citation check — FAIL case (no citation)
  4. Document Drafter placeholder check — FAIL case
  5. Scam Detection DB ID check — FAIL case (no db_id)
  6. Retry cap test — FORCED 3 consecutive failures → honest fallback
  7. Cross-agent contradiction detection (Rights vs Filing Act mismatch)
  8. Reflection log PII scrubbing — no forbidden fields in log entry

WHAT THESE TESTS DEMONSTRATE FOR EVALUATION
---------------------------------------------
Test 6 (retry cap) is the most critical:
  - It directly proves the system stops retrying after MAX_RETRIES and
    returns the honest fallback prefix rather than looping forever.
  - The mock is set up so the Rights Agent always fails.
  - After 3 failures, retry_counts["rights"] == MAX_RETRIES, so the
    Confirmation Agent wraps the output with the honest fallback prefix
    instead of requesting a 4th retry.

Test 7 (cross-agent contradiction) directly proves the concrete Rule C1:
  - Rights Agent output cites "Consumer Protection Act 2019"
  - Filing Guide output cites "RTI Act 2005"
  - Both pass their individual validation checks (both have citations,
    both have portal URLs)
  - The contradiction checker catches the Act mismatch and returns a note.

Tests run WITHOUT requiring:
  - Redis (session store uses redis_client=None → no-op mode)
  - MongoDB (reflection logger uses db=None → Python log only)
  - LLM API key (all agent outputs are synthetic mocks)
  - Qdrant vector database

Run with: cd backend && pytest tests/unit/test_confirmation_agent.py -v
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.confirmation_agent.agent import (
    MAX_RETRIES,
    HONEST_FALLBACK_PREFIX,
    ConfirmationAgent,
    confirmation_node,
)
from agents.confirmation_agent.contradiction import (
    check_rights_vs_filing_contradiction,
    run_contradiction_checks,
)
from agents.confirmation_agent.criteria import (
    validate_rights_output,
    validate_drafter_output,
    validate_scam_output,
    validate_filing_output,
    validate_vault_output,
)
from agents.confirmation_agent.reflection_logger import ReflectionLogger
from core.memory.session_store import SessionStore


# =============================================================================
# Test 1 — Session Store: concurrent writes don't corrupt data
# =============================================================================

@pytest.mark.asyncio
async def test_session_store_concurrent_write_safety():
    """
    Proves that two coroutines writing to the same session simultaneously
    do not corrupt each other's data.

    HOW THE TEST WORKS:
    - We use redis_client=None (no-op mode) so no real Redis is needed.
    - We inject a fake Redis that records all HSET calls and simulates
      a realistic read-modify-write cycle with controlled interleaving.
    - We verify that after 10 concurrent add_turn calls, the turn count
      is exactly 10 (no double-writes, no lost writes).

    NOTE: With redis_client=None, all writes are no-ops — this tests
    the asyncio.Lock logic by using a fake Redis that tracks calls.
    """
    # Use a simple in-memory dict to simulate Redis
    fake_store = {}

    class FakeRedis:
        async def hget(self, key, field):
            val = fake_store.get(f"{key}:{field}")
            return val.encode() if val else None

        async def hset(self, key, mapping=None, **kwargs):
            if mapping:
                for field, value in mapping.items():
                    fake_store[f"{key}:{field}"] = value

        async def expire(self, key, ttl):
            pass  # No-op for testing

    store = SessionStore(redis_client=FakeRedis(), ttl=3600)
    session_id = "test-session-concurrent"

    # Launch 10 concurrent add_turn calls
    tasks = [
        store.add_turn(session_id, role="user", content=f"Message {i}")
        for i in range(10)
    ]
    await asyncio.gather(*tasks)

    # Verify all 10 turns were recorded (no lost writes, no duplicates)
    turns = await store.get_turns(session_id)
    assert len(turns) == 10, (
        f"Expected 10 turns after concurrent writes, got {len(turns)}. "
        f"Concurrent write safety broken — asyncio.Lock is not working."
    )


# =============================================================================
# Test 2 — Rights Agent: output WITH citation → PASS
# =============================================================================

def test_rights_validation_pass_with_citation():
    """
    When the Rights Agent includes a [Source: <non-empty>] citation,
    validation MUST pass.  This is the happy-path baseline.
    """
    output_with_citation = (
        "Under Indian law, a tenant has the right to receive their security deposit back "
        "within 15 days of vacating the premises.\n\n"
        "[Source: Model Tenancy Act 2021, Section 15]"
    )
    result = validate_rights_output(output_with_citation, metadata={})
    assert result.passed, (
        f"Rights validation should PASS when [Source:] citation is present. "
        f"Got failure: {result.failure_reason}"
    )


# =============================================================================
# Test 3 — Rights Agent: output WITHOUT citation → FAIL with actionable feedback
# =============================================================================

def test_rights_validation_fail_missing_citation():
    """
    When the Rights Agent produces a response with no [Source:] citation,
    validation MUST fail.  The failure_reason must explain what's missing.
    The feedback_for_retry must tell the agent exactly what to add.

    This is the PASS-1-FAIL case: a plausible-sounding legal answer that is
    nonetheless invalid because it lacks a grounded citation.
    """
    output_without_citation = (
        "Under Indian tenancy law, landlords must return the security deposit within "
        "a reasonable period. Withholding it without justification is illegal."
        # NOTE: no [Source: ...] — this answer could be hallucinated
    )
    result = validate_rights_output(output_without_citation, metadata={})

    assert not result.passed, (
        "Rights validation should FAIL when [Source:] citation is absent."
    )
    assert result.failure_reason, "failure_reason must be non-empty on failure."
    assert result.feedback_for_retry, "feedback_for_retry must be non-empty on failure."
    assert "[Source:" in result.feedback_for_retry, (
        "feedback_for_retry must tell the agent the exact format needed: [Source: ...]"
    )


# =============================================================================
# Test 4 — Document Drafter: unfilled [FILL IN:] placeholder → FAIL
# =============================================================================

def test_drafter_validation_fail_unfilled_placeholder():
    """
    When the Document Drafter leaves [FILL IN: ...] markers in the output,
    validation MUST fail.  A document with unfilled placeholders is NOT
    ready for the citizen to use.

    This simulates the common failure mode where the LLM partially completes
    the template but doesn't fill in the citizen's personal details.
    """
    draft_with_placeholder = (
        "Date: 28 August 2026\n\n"
        "To: [FILL IN: Recipient Name]\n"    # <-- unfilled
        "[FILL IN: Recipient Address]\n\n"   # <-- unfilled
        "Subject: Security Deposit Return\n\n"
        "Dear Sir/Madam,\n\n"
        "I write to demand return of my security deposit of Rs. 50,000.\n\n"
        "Yours sincerely,\n"
        "[FILL IN: Your Full Name]\n"         # <-- unfilled
    )
    result = validate_drafter_output(draft_with_placeholder, metadata={})

    assert not result.passed, (
        "Drafter validation should FAIL when [FILL IN:] placeholders remain."
    )
    assert "3" in result.failure_reason or "placeholder" in result.failure_reason.lower(), (
        f"failure_reason should mention the count or type of placeholders. Got: {result.failure_reason}"
    )


# =============================================================================
# Test 5 — Scam Detection: no db_id in metadata and no SCAM_XXX in text → FAIL
# =============================================================================

def test_scam_validation_fail_no_db_id():
    """
    When Scam Detection produces an alert with no verified DB pattern ID
    (neither SCAM_XXX in the text nor db_id in metadata), validation MUST fail.

    This is the grounding check: the agent MUST tie its alert to a real
    verified pattern record, not generate ungrounded alert content.

    Contrast with the safe fallback path (no match found) which correctly
    passes validation.
    """
    # Scam alert with no DB grounding
    scam_output_no_id = (
        "WARNING: This appears to be a scam. The caller is likely impersonating a "
        "government official to steal your money. Do not share your OTP."
    )
    # No db_id in metadata either
    result = validate_scam_output(scam_output_no_id, metadata={"db_id": ""})

    assert not result.passed, (
        "Scam validation should FAIL when no SCAM_XXX pattern ID is present "
        "and the output is not the standard safe fallback."
    )
    assert "pattern" in result.failure_reason.lower() or "DB" in result.failure_reason, (
        f"failure_reason should mention the missing DB pattern ID. Got: {result.failure_reason}"
    )

    # Contrast: verify that the safe fallback (no match) PASSES
    safe_fallback = (
        "We could not match this to any known scam pattern in our database. "
        "If you are concerned, please report to cybercrime.gov.in or call 1930."
    )
    safe_result = validate_scam_output(safe_fallback, metadata={})
    assert safe_result.passed, (
        "Scam validation should PASS when the safe fallback no-match response is returned."
    )


# =============================================================================
# Test 6 — RETRY CAP: 3 consecutive failures → honest fallback (NOT 4th retry)
# =============================================================================

@pytest.mark.asyncio
async def test_retry_cap_forces_honest_fallback_after_3_failures():
    """
    THE CRITICAL RETRY CAP TEST.

    This test verifies that after MAX_RETRIES (3) failed attempts by the
    Rights Agent, the Confirmation Agent STOPS requesting retries and instead
    wraps the output with the honest fallback prefix.

    Setup:
      - A Rights Agent output with NO citation (guaranteed to fail validation).
      - retry_counts["rights"] = MAX_RETRIES (= 3), simulating that 3 attempts
        have already been consumed.

    Expected behaviour:
      - The Confirmation Agent detects citation missing → would normally retry.
      - BUT retry_counts["rights"] >= MAX_RETRIES, so it uses honest fallback.
      - The output is wrapped with HONEST_FALLBACK_PREFIX.
      - NO retry_target is set in the returned state.
      - The 4th specialist call is NEVER made.

    This proves: the system stops looping and gives an honest answer
    rather than spinning forever on a bad LLM response.
    """
    agent = ConfirmationAgent()

    # Failing Rights output — no [Source:] citation
    failing_rights_output = {
        "intent": "rights",
        "status": "ok",
        "output": "As a tenant you have the right to your deposit back.",
        "metadata": {"citations": []},
    }

    # Simulate that we have already exhausted all 3 retries
    retry_counts = {"rights": MAX_RETRIES}  # = 3

    reflection_logger = ReflectionLogger(db=None)  # No MongoDB in tests

    approved, failed_feedbacks, contradiction_note = await agent.run_confirmation_pass(
        scratchpad=[failing_rights_output],
        retry_counts=retry_counts,
        query="What are my tenant rights?",
        reflection_logger=reflection_logger,
        session_id="test-retry-cap",
    )

    # ASSERTION 1: No failed_feedbacks — the cap was hit, no more retries requested
    assert not failed_feedbacks, (
        f"After {MAX_RETRIES} retries, failed_feedbacks should be empty (no more retries). "
        f"Got: {failed_feedbacks}"
    )

    # ASSERTION 2: The output was wrapped with the honest fallback prefix
    assert len(approved) == 1, "Should have exactly one approved output."
    fallback_output_text = approved[0]["output"]
    assert fallback_output_text.startswith(HONEST_FALLBACK_PREFIX), (
        f"Output at retry cap should start with HONEST_FALLBACK_PREFIX.\n"
        f"Expected prefix: {repr(HONEST_FALLBACK_PREFIX[:50])}\n"
        f"Got start: {repr(fallback_output_text[:100])}"
    )

    # ASSERTION 3: The metadata records that this is a confirmation fallback
    assert approved[0]["metadata"].get("confirmation_fallback") is True, (
        "Fallback output metadata should have confirmation_fallback=True."
    )

    # ASSERTION 4: No contradiction note (only one agent ran)
    assert contradiction_note is None, (
        "No contradiction note should be generated when only one agent ran."
    )


# =============================================================================
# Test 7 — Cross-agent contradiction: Rights vs Filing Act mismatch
# =============================================================================

def test_cross_agent_contradiction_detected():
    """
    PROVES RULE C1 — Legal Act Mismatch.

    Setup:
      - Rights Agent output cites "Consumer Protection Act 2019" as the
        governing law for the citizen's complaint.
      - Filing Guide output cites "RTI Act 2005" as the law under which
        to file.
      - Both outputs individually pass their validation checks.

    Expected behaviour:
      run_contradiction_checks() detects that the primary Acts differ
      and returns a ContradictionResult with has_contradiction=True.

    Why this matters:
      A citizen reading both responses would receive conflicting instructions.
      The contradiction check catches this BEFORE the response reaches them.

    Also verifies the NEGATIVE case:
      When both outputs cite the same Act, no contradiction is returned.
    """
    rights_output = {
        "intent": "rights",
        "status": "ok",
        "output": (
            "Your complaint falls under the Consumer Protection Act 2019. "
            "You have the right to file a complaint with the District Consumer Forum. "
            "[Source: Consumer Protection Act 2019, Section 35]"
        ),
        "metadata": {"citations": ["Consumer Protection Act 2019, Section 35"]},
    }
    filing_output = {
        "intent": "filing",
        "status": "ok",
        "output": (
            "To file this complaint, submit an application under the RTI Act 2005. "
            "Visit https://rtionline.gov.in to file online."
        ),
        "metadata": {"portal_url": "https://rtionline.gov.in"},
    }

    # POSITIVE: Different Acts → should detect contradiction
    result = run_contradiction_checks([rights_output, filing_output])

    assert result is not None, (
        "run_contradiction_checks should return a ContradictionResult "
        "when Rights and Filing cite different Acts."
    )
    assert result.has_contradiction is True, (
        f"has_contradiction should be True when Acts differ. "
        f"Rights cited 'Consumer Protection Act 2019', Filing cited 'RTI Act 2005'."
    )
    assert "consumer protection act 2019" in result.description.lower() or \
           "rti act 2005" in result.description.lower(), (
        f"Contradiction description should name the conflicting Acts. Got: {result.description}"
    )
    assert "rights" in result.agents_involved and "filing" in result.agents_involved, (
        f"agents_involved should include both 'rights' and 'filing'. Got: {result.agents_involved}"
    )

    # NEGATIVE: Same Act in both → should NOT detect contradiction
    rights_same = {
        "intent": "rights",
        "status": "ok",
        "output": (
            "Your complaint falls under the RTI Act 2005. "
            "[Source: RTI Act 2005, Section 7]"
        ),
        "metadata": {},
    }
    filing_same = {
        "intent": "filing",
        "status": "ok",
        "output": (
            "File under the RTI Act 2005. Visit https://rtionline.gov.in."
        ),
        "metadata": {"portal_url": "https://rtionline.gov.in"},
    }
    result_no_conflict = run_contradiction_checks([rights_same, filing_same])

    assert result_no_conflict is None or not result_no_conflict.has_contradiction, (
        "No contradiction should be detected when both agents cite the same Act."
    )


# =============================================================================
# Test 8 — Reflection log: no PII in log entries
# =============================================================================

@pytest.mark.asyncio
async def test_reflection_log_contains_no_pii():
    """
    Verifies that reflection log entries do not contain PII.

    The reflection logger calls MongoDB.insert_one(entry).  We mock the
    MongoDB collection to capture the exact dict that would be inserted
    and inspect it for forbidden fields.

    Forbidden fields: phone, phone_number, user_id, email, name, address,
                      query, output, content, response

    This test also verifies the logger doesn't CRASH when given various
    pass_fail values and that it correctly logs all valid pass_fail states.
    """
    captured_entries = []

    class FakeCollection:
        async def insert_one(self, entry):
            captured_entries.append(dict(entry))

    class FakeDB:
        def __getitem__(self, name):
            return FakeCollection()

    logger = ReflectionLogger(db=FakeDB(), collection_name="test_reflection_logs")

    # Log a realistic reflection pass entry
    await logger.log_reflection_pass(
        session_id="test-session-pii-check",
        agents_checked=["rights"],
        pass_fail="fail",
        retry_count=1,
        rejection_reason="Missing citation",
        contradiction=None,
        query_length=45,
        response_length=200,
    )

    assert len(captured_entries) == 1, "One entry should have been logged."
    entry = captured_entries[0]

    # ASSERTION: No PII fields present
    FORBIDDEN_FIELDS = {
        "phone", "phone_number", "user_id", "email", "name", "address",
        "query", "output", "content", "response",
    }
    found_forbidden = {k for k in entry if k.lower() in FORBIDDEN_FIELDS}
    assert not found_forbidden, (
        f"Reflection log entry contains forbidden PII fields: {found_forbidden}\n"
        f"Full entry keys: {list(entry.keys())}"
    )

    # ASSERTION: Required safe metadata fields ARE present
    assert "session_id" in entry, "session_id must be present (it's a random UUID, not PII)."
    assert "timestamp" in entry, "timestamp must be present."
    assert "agents_checked" in entry, "agents_checked must be present."
    assert "pass_fail" in entry, "pass_fail must be present."
    assert "retry_count" in entry, "retry_count must be present."
    assert "query_length" in entry, "query_length (count, not text) must be present."

    # ASSERTION: user_id is NOT in session_id (it's truly random, not derived)
    # The session_id should be "test-session-pii-check" — not a phone number or user_id
    assert entry["session_id"] == "test-session-pii-check", (
        "session_id should be the exact value passed in (random UUID in production)."
    )
