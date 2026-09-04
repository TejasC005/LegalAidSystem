"""
=============================================================================
LEXIS — Confirmation Agent  (Module 11)
=============================================================================

WHAT IS THIS FILE?
------------------
The Confirmation Agent is a distinct LangGraph node that sits between the
specialist agents and the compile_response_node.  Its job: inspect every
agent's draft output BEFORE it reaches the citizen, reject drafts that fail
concrete quality criteria, and trigger a bounded retry loop.

THIS IS THE "SELF-CORRECTION" PILLAR OF LEXIS'S AGENTIC ARCHITECTURE.

─────────────────────────────────────────────────────────────────────────────
BEGINNER-FRIENDLY: WHAT IS "SELF-CORRECTION" HERE?
─────────────────────────────────────────────────────────────────────────────

Think of the Confirmation Agent as a QA reviewer who reads a draft legal
memo before it goes to a client.  The reviewer has a checklist:
  - Does the memo cite the relevant law?
  - Did the lawyer fill in all the blanks?
  - Is the filing authority correct?

If the memo fails any checklist item, the reviewer sends it BACK to the
lawyer with a specific note:
  "Revision needed: You cited Section 7 but didn't specify the time limit.
   Add the 30-day response deadline."

The lawyer revises it and resubmits.  The reviewer checks again.

In LEXIS, the "reviewer" is this Confirmation Agent node.  The "lawyer" is
the specialist agent (Rights, Drafter, etc.).  The revision note is the
`feedback_for_retry` field in ValidationResult.  The loop is bounded: after
3 failed attempts, instead of looping forever, the system honestly tells the
citizen: "I couldn't verify this confidently — here's what I found so far."

─────────────────────────────────────────────────────────────────────────────
HOW THE RETRY CAP PREVENTS INFINITE LOOPS
─────────────────────────────────────────────────────────────────────────────

The `retry_counts` dict in OrchestratorState tracks how many times each
agent has been retried on this request.  Before routing back:

    if retry_counts.get(intent, 0) >= MAX_RETRIES:
        # Cap reached — do NOT route back.  Return honest fallback.

Without this cap:
  Confirmation Agent fails → routes back to specialist → specialist produces
  same bad output → Confirmation Agent fails again → routes back → ... ∞

With the cap, the worst case is:
  3 specialist attempts + 3 confirmation checks = 6 total operations.
  Then the system stops and returns the honest fallback.

─────────────────────────────────────────────────────────────────────────────
HOW THIS IS WIRED INTO THE LANGGRAPH GRAPH
─────────────────────────────────────────────────────────────────────────────

Before Module 11:
  specialist_node → compile_response_node → END

After Module 11:
  specialist_node → confirmation_node ─── PASS ──→ compile_response_node → END
                         │
                         └── FAIL (retry < 3) → [set retry_target] → specialist_node (loop)
                         │
                         └── FAIL (retry >= 3) → compile_response_node (with honest_fallback flag)

The loopback edge from compile_response_node back to specialist_node was
commented-out in Module 4 and is now activated here.  The Confirmation Agent
sets state["retry_target"] to the intent that needs a retry, and
compile_response_node routes back instead of ending.

─────────────────────────────────────────────────────────────────────────────
CONCURRENT EXECUTION HANDLING
─────────────────────────────────────────────────────────────────────────────

When 2 agents ran concurrently (e.g., Rights + Filing for a "rights and filing"
query), both their outputs are in the scratchpad.  The Confirmation Agent:

  1. Validates each output individually against its per-agent criteria.
  2. If BOTH pass individual checks, runs the cross-agent contradiction check.
  3. If a contradiction is found, logs it and adds a note to the compiled
     response warning the citizen that two agent outputs may be inconsistent.

The contradiction does NOT trigger a retry (we cannot tell which agent is
"wrong" without additional domain knowledge).  Instead, it generates an
advisory note in the final response and is logged for admin review.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from agents.confirmation_agent.contradiction import run_contradiction_checks
from agents.confirmation_agent.criteria import validate_agent_output
from agents.confirmation_agent.reflection_logger import ReflectionLogger
from agents.orchestrator.state import AgentIntent, AgentOutput, OrchestratorState

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
MAX_RETRIES: int = 3  # Hard cap: 3 total attempts (1 original + 2 retries)

HONEST_FALLBACK_PREFIX: str = (
    "⚠️ I wasn't able to fully verify this response after multiple attempts.  "
    "Here is what I found so far — please verify independently before acting on this information:\n\n"
)

# Disclaimer appended when a cross-agent contradiction is detected
CONTRADICTION_DISCLAIMER: str = (
    "\n\n---\n"
    "⚠️ **Note:** Two of the agent responses above may be inconsistent.  {description}  "
    "Please review both sections carefully and consult a legal professional if unsure which applies to your situation."
)


# =============================================================================
# Core Confirmation Logic
# =============================================================================

class ConfirmationAgent:
    """
    The Confirmation Agent reviews specialist agent draft outputs and decides
    whether they meet quality criteria before being shown to the citizen.

    Methods
    -------
    run_confirmation_pass(scratchpad, retry_counts, query, reflection_logger)
        → (approved_scratchpad, failed_intents_with_feedback, contradiction_note)
    """

    async def run_confirmation_pass(
        self,
        scratchpad: List[AgentOutput],
        retry_counts: Dict[str, int],
        query: str,
        reflection_logger: Optional[ReflectionLogger] = None,
        session_id: str = "unknown",
    ) -> tuple:
        """
        Validates all specialist agent outputs in the scratchpad.

        Returns
        -------
        A 3-tuple:
          (
            approved_outputs  : List[AgentOutput]  — outputs that passed validation
            failed_feedbacks  : Dict[str, str]      — intent → feedback_for_retry (failed outputs)
            contradiction_note: Optional[str]        — advisory note if cross-agent contradiction found
          )

        How to read the return value:
          - If failed_feedbacks is empty: all agents passed — compile the response.
          - If failed_feedbacks is non-empty: some agents failed — check retry_counts.
            If retries remain, route those agents back. If exhausted, use honest fallback.
          - contradiction_note is independent: it's appended to the final response
            regardless of individual pass/fail (a contradiction ≠ a validation failure).
        """
        # Deduplicate scratchpad entries by intent: keep only the most recent entry per intent
        latest_by_intent: Dict[str, AgentOutput] = {}
        for record in scratchpad:
            intent_key = record.get("intent", "")
            latest_by_intent[intent_key] = record
        deduped_scratchpad = list(latest_by_intent.values())

        approved: List[AgentOutput] = []
        failed_feedbacks: Dict[str, str] = {}
        agents_checked: List[str] = []

        for record in deduped_scratchpad:
            intent = record.get("intent", "")
            status = record.get("status", "")
            output_text = record.get("output", "")
            metadata = record.get("metadata", {})

            # ── Only validate "ok" records ────────────────────────────────────
            # error/timeout records from failed agents pass through unchanged —
            # the specialist node already wrote a graceful error message.
            if status != "ok":
                approved.append(record)
                continue

            agents_checked.append(intent)

            # ── Run the per-agent validation criterion ────────────────────────
            result = validate_agent_output(
                intent=intent,
                output_text=output_text,
                metadata=metadata,
            )

            if result.passed:
                approved.append(record)
                logger.info(
                    "ConfirmationAgent: PASS for intent='%s' retry_count=%d",
                    intent, retry_counts.get(intent, 0),
                )
                # Log successful pass
                if reflection_logger:
                    await reflection_logger.log_reflection_pass(
                        session_id=session_id,
                        agents_checked=[intent],
                        pass_fail="pass",
                        retry_count=retry_counts.get(intent, 0),
                        query_length=len(query),
                        response_length=len(output_text),
                    )
            else:
                current_retries = retry_counts.get(intent, 0)
                logger.warning(
                    "ConfirmationAgent: FAIL for intent='%s' retry_count=%d reason='%s'",
                    intent, current_retries, result.failure_reason,
                )

                if reflection_logger:
                    # Cap check: if already at MAX_RETRIES, label as "fallback"
                    pf = "fallback" if current_retries >= MAX_RETRIES else "fail"
                    await reflection_logger.log_reflection_pass(
                        session_id=session_id,
                        agents_checked=[intent],
                        pass_fail=pf,
                        retry_count=current_retries,
                        rejection_reason=result.failure_reason,
                        query_length=len(query),
                        response_length=len(output_text),
                    )

                if current_retries >= MAX_RETRIES:
                    # ── Retry cap exhausted ───────────────────────────────────
                    # Don't route back. Include the output with an honest fallback
                    # prefix so the citizen gets partial information rather than nothing.
                    logger.warning(
                        "ConfirmationAgent: Retry cap reached for intent='%s'. Using honest fallback.",
                        intent,
                    )
                    fallback_record: AgentOutput = {
                        "intent": intent,
                        "status": "ok",  # Prevents the "error" penalty in compile_response_node
                        "output": HONEST_FALLBACK_PREFIX + output_text,
                        "metadata": {
                            **metadata,
                            "confirmation_fallback": True,
                            "rejection_reason": result.failure_reason,
                        },
                    }
                    approved.append(fallback_record)
                else:
                    # ── Route back for retry ──────────────────────────────────
                    failed_feedbacks[intent] = result.feedback_for_retry

        # ── Cross-agent contradiction check ───────────────────────────────────
        contradiction_note: Optional[str] = None
        if len(agents_checked) >= 2:
            contradiction = run_contradiction_checks(approved)
            if contradiction and contradiction.has_contradiction:
                contradiction_note = CONTRADICTION_DISCLAIMER.format(
                    description=contradiction.description
                )
                logger.warning(
                    "ConfirmationAgent: Cross-agent CONTRADICTION detected: %s",
                    contradiction.description,
                )
                if reflection_logger:
                    await reflection_logger.log_reflection_pass(
                        session_id=session_id,
                        agents_checked=contradiction.agents_involved,
                        pass_fail="contradiction",
                        retry_count=0,
                        contradiction=contradiction.description,
                        query_length=len(query),
                        response_length=0,
                    )

        return approved, failed_feedbacks, contradiction_note


# ── Singleton factory ─────────────────────────────────────────────────────────
_confirmation_agent_instance: Optional[ConfirmationAgent] = None


def get_confirmation_agent() -> ConfirmationAgent:
    """Returns the singleton ConfirmationAgent instance."""
    global _confirmation_agent_instance
    if _confirmation_agent_instance is None:
        _confirmation_agent_instance = ConfirmationAgent()
    return _confirmation_agent_instance


# =============================================================================
# LangGraph Node
# =============================================================================

async def confirmation_node(state: OrchestratorState) -> dict:
    """
    LangGraph node: Confirmation Agent.

    This node is called after all specialist nodes finish (after the parallel
    superstep completes and all scratchpad entries are collected).

    It reads the scratchpad, runs validation, and returns state updates:
      - If all pass: state stays unchanged (scratchpad ready for compile).
      - If some fail and retries remain: sets retry_target + retry_feedback
        so compile_response_node can route back.
      - If retry cap reached: wraps failing outputs in honest fallback prefix.
      - If contradiction detected: appends a contradiction_note to state.

    STATE FIELDS WRITTEN:
      scratchpad       → may be replaced (honest fallback wrapping)
      retry_target     → intent to retry (or None if all passed)
      retry_feedback   → feedback string for the retrying agent
      retry_counts     → incremented for the failed intent
      contradiction_note → advisory note if cross-agent contradiction found
    """
    scratchpad: List[AgentOutput] = state.get("scratchpad", [])
    retry_counts: Dict[str, int] = dict(state.get("retry_counts", {}))
    query: str = state.get("query", "")
    session_id: str = state.get("session_id", "unknown")

    # Lazy-import to avoid circular dependency at module level
    from agents.confirmation_agent.reflection_logger import get_reflection_logger
    reflection_logger = get_reflection_logger()

    agent = get_confirmation_agent()
    approved, failed_feedbacks, contradiction_note = await agent.run_confirmation_pass(
        scratchpad=scratchpad,
        retry_counts=retry_counts,
        query=query,
        reflection_logger=reflection_logger,
        session_id=session_id,
    )

    # ── No failures → all clear ───────────────────────────────────────────────
    if not failed_feedbacks:
        logger.info(
            "ConfirmationAgent: All agents passed. Routing to compile. session=%s",
            session_id,
        )
        result = {
            # Write to confirmed_outputs (NOT scratchpad) to avoid double-appending
            # via the operator.add reducer. compile_response_node reads this field.
            "confirmed_outputs": approved,
            "retry_target": None,
            "retry_feedback": "",
            "retry_counts": retry_counts,
        }
        if contradiction_note:
            result["contradiction_note"] = contradiction_note
        return result

    # ── Some failures → pick the first failed intent to retry ────────────────
    # We only retry one agent per pass (picking the first alphabetically for
    # determinism in tests).  Future enhancement: retry all failed agents in
    # the next superstep.
    retry_intent_str, feedback = next(iter(failed_feedbacks.items()))

    # Increment the retry counter for this intent
    retry_counts[retry_intent_str] = retry_counts.get(retry_intent_str, 0) + 1

    logger.info(
        "ConfirmationAgent: Routing retry for intent='%s' (attempt %d/%d)",
        retry_intent_str, retry_counts[retry_intent_str], MAX_RETRIES,
    )

    # Remove the failed agent's output from the scratchpad so the retry
    # produces a fresh record (the old failed one is discarded)
    approved_without_failed = [
        r for r in approved
        if r.get("intent") != retry_intent_str or r.get("metadata", {}).get("confirmation_fallback")
    ]

    return {
        # Write to confirmed_outputs (NOT scratchpad) to avoid double-appending
        "confirmed_outputs": approved_without_failed,
        "retry_target": AgentIntent(retry_intent_str),
        "retry_feedback": feedback,
        "retry_counts": retry_counts,
        **({"contradiction_note": contradiction_note} if contradiction_note else {}),
    }
