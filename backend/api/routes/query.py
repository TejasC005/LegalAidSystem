"""
LEXIS — Query API Route (Module 4)
====================================

POST /api/v1/query

This is the single entry point for the frontend to send a citizen's legal
query to the LEXIS orchestrator.  The orchestrator classifies the intent,
fans out to specialist agents concurrently, and returns a compiled response.

INPUT GUARDRAILS (applied before anything hits the graph):
  - query must be a non-empty string
  - query length is capped at MAX_QUERY_LENGTH characters (2000)
  - Basic injection guard: queries starting with typical prompt-injection
    patterns are rejected with HTTP 400
  - Authentication: Bearer JWT required (from Module 2)

The endpoint is async because the entire LangGraph graph is async.
"""

import logging
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from agents.orchestrator.agent import orchestrator_graph, MAX_LLM_CALLS_PER_REQUEST
from agents.orchestrator.state import AgentIntent
from api.dependencies.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/query", tags=["Query"])

# ── Query length guardrail ────────────────────────────────────────────────────
MAX_QUERY_LENGTH = 2000

# ── Prompt injection guard patterns ──────────────────────────────────────────
# Lightweight check for obvious injection attempts.  NOT a complete defense
# (that is handled at the prompt level in each agent).  This layer rejects
# the most obvious cases before they enter the graph.
_INJECTION_PATTERNS = re.compile(
    r"(ignore previous instructions|you are now|disregard all prior|jailbreak|act as if)",
    re.IGNORECASE,
)


# ── Request / Response schemas ────────────────────────────────────────────────

class QueryRequest(BaseModel):
    """
    The body of POST /api/v1/query.

    Fields:
      query                — the citizen's legal question (required)
      conversation_history — prior turns for context (optional, default empty)
      llm_calls_limit      — override the per-request LLM call ceiling (optional)
    """
    query: str = Field(
        ...,
        min_length=1,
        max_length=MAX_QUERY_LENGTH,
        description="The citizen's legal question.",
        examples=["What are my rights as a tenant if my landlord refuses to return the security deposit?"],
    )
    conversation_history: List[dict] = Field(
        default_factory=list,
        description="Prior conversation turns as [{role, content}] dicts.",
    )
    llm_calls_limit: Optional[int] = Field(
        default=None,
        ge=1,
        le=50,
        description="Override the max LLM calls for this request (1–50).",
    )

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Query must not be empty or only whitespace.")
        if _INJECTION_PATTERNS.search(stripped):
            raise ValueError(
                "Query contains disallowed patterns. Please rephrase your legal question."
            )
        return stripped


class AgentResultSummary(BaseModel):
    """Summary of one agent's contribution in the response."""
    intent:   str
    status:   str
    preview:  str  # First 200 chars of the agent's output
    metadata: Optional[Dict[str, Any]] = None


class QueryResponse(BaseModel):
    """
    The structured response from POST /api/v1/query.

    Fields:
      final_response       — the compiled, human-readable answer
      status               — "ok" | "partial" | "unclear" | "error"
      intents              — which intents were detected and dispatched
      agents               — per-agent status summaries (for debugging / UI)
      verification_status  — verification badge status (e.g. "verified", "verified_with_scope", "unverified")
      citations            — list of verified source citations
      llm_calls_used       — how many LLM calls this request consumed
      llm_calls_limit      — the ceiling that was in effect
    """
    final_response:      str
    status:              str
    intents:             List[str]
    agents:              List[AgentResultSummary]
    verification_status: Optional[str] = None
    citations:           Optional[List[str]] = None
    llm_calls_used:      int
    llm_calls_limit:     int


# ── Route handler ─────────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=QueryResponse,
    summary="Submit a legal query to the LEXIS orchestrator",
    description=(
        "Classifies the query into one or more specialist intents, dispatches "
        "the matching agents CONCURRENTLY, and returns a compiled response. "
        "Requires a valid Bearer JWT token."
    ),
)
async def submit_query(
    body: QueryRequest,
    current_user: dict = Depends(get_current_user),
) -> QueryResponse:
    """
    Main query endpoint.

    1. Validates input (Pydantic handles length + format; @validator handles logic).
    2. Builds the initial LangGraph state from the request body.
    3. Invokes the compiled orchestrator graph asynchronously.
    4. Extracts the final state and maps it to the response schema.
    """
    user_id = current_user.get("sub", "anonymous")
    logger.info(
        "Query received",
        extra={"user_id": user_id, "query_len": len(body.query)},
    )

    # ── Build initial state ───────────────────────────────────────────────────
    # -- Build initial state (Module 11 fields added) ----
    from uuid import uuid4
    calls_limit = body.llm_calls_limit or MAX_LLM_CALLS_PER_REQUEST
    session_id = str(uuid4())  # Random UUID per request -- NOT user_id
    initial_state = {
        "query":                body.query,
        "session_id":           session_id,
        "conversation_history": body.conversation_history,
        "intents":              [],
        "confidence":           0.0,
        "scratchpad":           [],
        "final_response":       "",
        "status":               "ok",
        "llm_calls_used":       0,
        "llm_calls_limit":      calls_limit,
        "retry_target":         None,
        "retry_counts":         {},
        "retry_feedback":       "",
        "contradiction_note":   None,
        "confirmed_outputs":    None,            # Module 11: set by confirmation_node
    }

    # ── Invoke the graph ──────────────────────────────────────────────────────
    try:
        final_state = await orchestrator_graph.ainvoke(initial_state)
    except Exception as exc:
        logger.error(
            "Orchestrator graph failed with unhandled exception",
            extra={"user_id": user_id, "error": str(exc)},
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while processing your query. Please try again.",
        )

    # ── Map to response schema ─────────────────────────────────────────────────
    scratchpad = final_state.get("scratchpad", [])
    agent_summaries = [
        AgentResultSummary(
            intent=r["intent"],
            status=r["status"],
            preview=r["output"][:200],
            metadata=r.get("metadata", {}),
        )
        for r in scratchpad
    ]

    # Extract verification status & citations (prioritizing Rights Explainer)
    top_verification_status = None
    all_citations: List[str] = []
    for r in scratchpad:
        meta = r.get("metadata", {})
        if meta.get("citations"):
            for c in meta["citations"]:
                if c not in all_citations:
                    all_citations.append(c)
        if r.get("intent") == "rights" or meta.get("agent") == "RightsExplainerAgent":
            if meta.get("verification_status"):
                top_verification_status = meta["verification_status"]
        elif not top_verification_status and meta.get("verification_status"):
            top_verification_status = meta["verification_status"]

    if not top_verification_status and any(r.get("intent") == "rights" for r in scratchpad):
        top_verification_status = "unverified"

    logger.info(
        "Query completed",
        extra={
            "user_id":       user_id,
            "status":        final_state.get("status"),
            "intents":       [i.value if isinstance(i, AgentIntent) else i for i in final_state.get("intents", [])],
            "llm_calls":     final_state.get("llm_calls_used", 0),
        },
    )

    return QueryResponse(
        final_response=final_state.get("final_response", ""),
        status=final_state.get("status", "error"),
        intents=[
            i.value if isinstance(i, AgentIntent) else str(i)
            for i in final_state.get("intents", [])
        ],
        agents=agent_summaries,
        verification_status=top_verification_status,
        citations=all_citations if all_citations else None,
        llm_calls_used=final_state.get("llm_calls_used", 0),
        llm_calls_limit=calls_limit,
    )
