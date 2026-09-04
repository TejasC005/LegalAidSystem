"""
=============================================================================
LEXIS Orchestrator Agent -- Module 4: Orchestrator Agent Core
=============================================================================

WHAT IS THIS FILE?
------------------
This file defines the LEXIS Orchestrator: a LangGraph state machine that
receives a citizen's legal query, classifies it into one or more intent
categories, dispatches specialist agent nodes CONCURRENTLY for each matched
intent, collects and merges their outputs safely, and compiles a single
unified response.

WHAT IS A LANGGRAPH GRAPH AND WHY NOT JUST USE if/else?
---------------------------------------------------------
A LangGraph "graph" is a directed graph where:
  - NODES are Python functions (sync or async) that do one unit of work.
  - EDGES are rules that decide which node runs next.
  - STATE is a typed dictionary passed into every node, updated by each node,
    and passed to the next node.

If we used if/else, the code would look like:

    intents = classify(query)
    if "rights" in intents:
        result1 = rights_agent(query)   # waits 3 seconds
    if "filing" in intents:
        result2 = filing_agent(query)   # waits 3 MORE seconds (total: 6s)

That is sequential.  With LangGraph's Send API:

    classify -> Send("specialist_node", rights_state)
             -> Send("specialist_node", filing_state)
                  Both run AT THE SAME TIME -> compile (total: ~3s)

The graph approach also gives us:
  - A clear, visual representation of the system flow.
  - Automatic state passing -- no manual parameter threading.
  - Built-in failure isolation between parallel nodes.
  - Extension points for retry/loopback without rewriting the routing logic.

HOW CONCURRENT FAN-OUT WORKS (Send API)
-----------------------------------------
The fan_out_router function returns a list of Send objects:

    return [Send("specialist_node", {"intent": i, ...}) for i in intents]

LangGraph schedules ALL of them in the SAME super-step.  A "super-step" is
one "round" of execution.  All nodes in a super-step run concurrently.
When ALL of them finish, LangGraph advances to the next super-step.

The scratchpad key uses Annotated[List[AgentOutput], operator.add] as its
reducer.  This means: when multiple nodes each return {"scratchpad": [item]},
LangGraph ADDS all those lists together instead of overwriting.  Without the
reducer, the last node to finish would overwrite everyone else's result.

PARTIAL RESULTS AND FAILURE ISOLATION
---------------------------------------
CRITICAL DESIGN CHOICE: LangGraph's "atomic failure" rule says that if ANY
node in a parallel super-step lets an exception PROPAGATE (i.e., raises),
the ENTIRE super-step fails and ALL state changes are rolled back.  You would
lose ALL results, not just the one that failed.

The solution: each specialist node catches ALL exceptions internally and
writes an {"status": "error", ...} AgentOutput to the scratchpad instead of
raising.  The node NEVER raises.  This way:
  - If Agent A crashes internally, it writes a graceful error record.
  - Agent B still finishes and writes its successful result.
  - The compiler sees both records and returns a partial result.
  - The user gets Agent B's answer + a note that Agent A had an issue.

COST / LATENCY GUARDRAILS
---------------------------
MAX_LLM_CALLS_PER_REQUEST limits the total LLM API calls in one request
(1 for classification + N for specialist agents).  If the classifier returns
more intents than would fit under the limit, only the first N are dispatched.
This prevents runaway costs on complex or adversarial queries.  Any breach is
logged at WARNING level for alerting.

MODULE 11 EXTENSION POINT (RETRY / LOOPBACK)
----------------------------------------------
The compile_response_node checks state["retry_target"].  In Module 4 this is
always None.  In Module 11, the Confirmation Agent can set retry_target to an
AgentIntent value, and this node will re-Send to specialist_node for that
intent instead of returning the final response.  The loopback edge structure
is wired here as a comment block to make Module 11 a simple addition.
"""

import asyncio
import logging
import time
from typing import List
from uuid import uuid4

from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

from agents.orchestrator.state import AgentIntent, AgentOutput, OrchestratorState
from agents.orchestrator.prompts import (
    INTENT_CLASSIFICATION_SYSTEM,
    INTENT_CLASSIFICATION_USER_TEMPLATE,
    UNCLEAR_INTENT_RESPONSE,
)

logger = logging.getLogger(__name__)

# ── Cost guardrail constant ───────────────────────────────────────────────────
# Maximum total LLM API calls allowed in a single request.
# 1 call = intent classifier.  Each specialist agent = 1 more call.
# So MAX_LLM_CALLS_PER_REQUEST=5 means: classifier + up to 4 specialist agents.
# Adjust in settings (Module 4 uses this as the hard-coded default).
MAX_LLM_CALLS_PER_REQUEST: int = 10

# ── Per-specialist timeout (seconds) ─────────────────────────────────────────
# Each specialist node has this wall-clock budget before it times out.
# The timeout is enforced via asyncio.wait_for inside the node so we can
# write a graceful "timeout" record instead of letting the error propagate.
SPECIALIST_TIMEOUT_SECONDS: float = 30.0


# =============================================================================
# NODE 1 — Intent Classifier
# =============================================================================

async def classify_intent_node(state: OrchestratorState) -> dict:
    """
    Reads the citizen's query and classifies it into one or more AgentIntents.

    HOW IT WORKS:
      1. Calls an LLM (or mock when no API key is set) with a structured prompt.
      2. Parses the LLM's comma-separated response into a list of AgentIntent values.
      3. Falls back to "unclear" if the response is unrecognised or confidence is low.
      4. Returns updates to the shared state: intents, confidence, llm_calls_used.

    FALLBACK BEHAVIOUR:
      If OPENAI_API_KEY is empty/missing, we use a lightweight keyword-based
      classifier instead of an LLM call.  This means all tests and local dev
      work without needing a real API key.
    """
    query = state["query"]
    calls_limit = state.get("llm_calls_limit", MAX_LLM_CALLS_PER_REQUEST)
    # With operator.add reducer, state["llm_calls_used"] is the CURRENT total.
    # We read it to enforce the guardrail, but we RETURN only our increment (0 or 1).
    calls_used_so_far = state.get("llm_calls_used", 0)

    # ── Guardrail: check LLM call budget before making a call ────────────────
    if calls_used_so_far >= calls_limit:
        logger.warning(
            "LLM call ceiling reached before classification",
            extra={"calls_used": calls_used_so_far, "calls_limit": calls_limit, "query_len": len(query)},
        )
        return {
            "intents": [],
            "confidence": 0.0,
            "llm_calls_used": 0,  # This node made 0 calls (guardrail hit)
            "status": "error",
            "final_response": "Request could not be processed: LLM call limit reached.",
        }

    # ── Try LLM classification, fall back to keyword matching ────────────────
    llm_increment = 0
    try:
        intents, confidence = await _call_llm_classifier(query)
        llm_increment = 1  # We made 1 LLM call
    except Exception as exc:
        logger.warning("LLM classifier failed, falling back to keyword match: %s", exc)
        intents, confidence = _keyword_classifier_fallback(query)
        # llm_increment stays 0: keyword fallback makes no LLM call

    logger.info(
        "Intent classified",
        extra={"intents": [i.value for i in intents], "confidence": confidence, "query_len": len(query)},
    )

    return {
        "intents": intents,
        "confidence": confidence,
        "llm_calls_used": llm_increment,
    }


async def _call_llm_classifier(query: str):
    """
    Makes an LLM API call to classify the query into AgentIntent values.

    Returns (list[AgentIntent], confidence_float).
    Uses Google GenAI (Gemini) API.
    """
    from core.config import get_settings
    settings = get_settings()

    api_key = settings.GEMINI_API_KEY or settings.OPENAI_API_KEY
    if not api_key or api_key.startswith("sk-replace"):
        raise RuntimeError("No valid LLM API key configured -- using keyword fallback")

    model_name = settings.GEMINI_MODEL_DEV if settings.GEMINI_API_KEY else settings.OPENAI_MODEL_DEV

    from google import genai
    client = genai.Client(api_key=api_key)
    prompt = f"{INTENT_CLASSIFICATION_SYSTEM}\n\n{INTENT_CLASSIFICATION_USER_TEMPLATE.format(query=query)}"

    response = await client.aio.models.generate_content(
        model=model_name,
        contents=prompt,
    )
    raw = response.text.strip().lower() if response.text else ""

    return _parse_intent_response(raw)


def _keyword_classifier_fallback(query: str):
    """
    Lightweight keyword-based intent classifier used when no API key is set.

    This is NOT a replacement for the LLM classifier -- it is a development
    fallback that allows the full graph to run and be tested locally without
    spending API credits.  Returns (list[AgentIntent], confidence_float).
    """
    q = query.lower()
    matched = []

    keyword_map = {
        AgentIntent.RIGHTS:  ["right", "rights", "law", "legal", "protection", "tenant", "landlord", "deposit", "worker", "employee", "consumer", "constitution", "posh", "harassment", "maternity"],
        AgentIntent.DRAFT:   ["draft", "write", "template", "agreement", "notice", "letter", "affidavit", "document"],
        AgentIntent.ANALYZE: ["analyze", "analyse", "review", "check", "clause", "contract", "risk", "flag"],
        AgentIntent.SCAM:    ["scam", "fraud", "fake", "suspicious", "cheat", "phishing", "lottery", "prize"],
        AgentIntent.FILING:  ["file", "filing", "report", "complaint", "court", "police", "rti", "forum", "fir", "submit"],
        AgentIntent.VAULT:   ["save", "store", "remind", "reminder", "deadline", "expire", "document vault", "track"],
    }

    for intent, keywords in keyword_map.items():
        if any(kw in q for kw in keywords):
            matched.append(intent)

    confidence = 0.75 if matched else 0.0
    return matched, confidence


def _parse_intent_response(raw: str):
    """
    Parses the LLM's raw text output into (list[AgentIntent], confidence_float).

    Expected LLM output: "rights" or "rights,filing" or "unclear"
    """
    if not raw or raw == "unclear":
        return [], 0.0

    valid_values = {e.value for e in AgentIntent}
    parts = [p.strip() for p in raw.split(",")]
    parsed = []

    for part in parts:
        if part in valid_values:
            parsed.append(AgentIntent(part))
        else:
            logger.warning("Unrecognised intent token from LLM: '%s'", part)

    confidence = 0.85 if parsed else 0.0
    return parsed, confidence


# =============================================================================
# ROUTER — Fan-out to specialist nodes (concurrent dispatch)
# =============================================================================

def fan_out_router(state: OrchestratorState) -> List[Send]:
    """
    The heart of the concurrent fan-out.

    This function is called as a CONDITIONAL EDGE, not a node.  It returns
    a list of Send objects.  LangGraph schedules ALL of them in the SAME
    super-step, which means specialist_node runs CONCURRENTLY for each intent.

    WHAT IS A Send OBJECT?
    -----------------------
    Send("node_name", state_dict) tells LangGraph:
      "Start a copy of 'node_name' with this specific state."

    Each Send is independent -- they don't share memory at the Python level.
    They DO share the OrchestratorState scratchpad via the reducer mechanism.

    GUARDRAIL:
    If dispatching all intents would exceed the LLM call budget, we truncate
    the list and log a warning.  The citizen gets partial results + a note.
    """
    intents = state.get("intents", [])
    confidence = state.get("confidence", 0.0)
    calls_used = state.get("llm_calls_used", 0)
    calls_limit = state.get("llm_calls_limit", MAX_LLM_CALLS_PER_REQUEST)

    # ── Unclear intent: skip fan-out, go directly to compile ─────────────────
    if not intents or confidence < 0.4:
        logger.info("No clear intents detected -- routing to compile with unclear status")
        return [Send("compile_response_node", {**state, "intents": []})]

    # ── Guardrail: limit intents to remaining LLM budget ─────────────────────
    remaining_budget = calls_limit - calls_used
    if len(intents) > remaining_budget:
        logger.warning(
            "LLM call ceiling would be exceeded; truncating intents",
            extra={
                "requested": len(intents),
                "allowed": remaining_budget,
                "calls_used": calls_used,
                "calls_limit": calls_limit,
            },
        )
        intents = intents[:remaining_budget]

    # ── Build one Send per matched intent ─────────────────────────────────────
    # Each Send passes the FULL state plus the specific intent for that copy.
    # specialist_node uses state["_current_intent"] to know which agent to run.
    sends = [
        Send("specialist_node", {**state, "_current_intent": intent})
        for intent in intents
    ]

    logger.info(
        "Fan-out dispatching %d specialist nodes concurrently",
        len(sends),
        extra={"intents": [i.value for i in intents]},
    )

    return sends


# =============================================================================
# NODE 2 — Specialist Agent (Placeholder)
# =============================================================================

async def specialist_node(state: OrchestratorState) -> dict:
    """
    Specialist agent node wrapper.

    Executes domain-specific work for state["_current_intent"].
    Injects timing into agent-supplied metadata and records AgentOutput to scratchpad.

    CRITICAL SAFETY DESIGN:
    This function NEVER raises an exception. All exceptions are caught
    internally and written as {"status": "error"} or {"status": "timeout"}
    records. This is required for partial-result safety under concurrent
    execution.

    TIMEOUT BEHAVIOUR:
    The actual work is wrapped in asyncio.wait_for(SPECIALIST_TIMEOUT_SECONDS).
    If the work exceeds the budget, asyncio.TimeoutError is caught HERE and
    a timeout record is written. The exception does NOT propagate to LangGraph.
    """
    intent: AgentIntent = state["_current_intent"]
    query: str = state["query"]
    t_start = time.perf_counter()

    try:
        # ── Main work wrapped in timeout guard ───────────────────────────────
        work_result = await asyncio.wait_for(
            _run_specialist_work(intent, query, state),
            timeout=SPECIALIST_TIMEOUT_SECONDS,
        )
        elapsed_ms = int((time.perf_counter() - t_start) * 1000)

        # Handle tuple return (real specialist) or string return (test mocks or placeholders)
        if isinstance(work_result, tuple):
            output_text, metadata, llm_calls = work_result
        else:
            output_text = str(work_result)
            metadata = {
                "agent": f"placeholder_{intent.value}",
                "model": "none (placeholder)",
            }
            llm_calls = 0

        metadata["latency_ms"] = elapsed_ms

        agent_output: AgentOutput = {
            "intent":   intent.value,
            "status":   "ok",
            "output":   output_text,
            "metadata": metadata,
        }
        logger.info(
            "Specialist node completed",
            extra={"intent": intent.value, "latency_ms": elapsed_ms},
        )

    except asyncio.TimeoutError:
        elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        logger.warning(
            "Specialist node timed out",
            extra={"intent": intent.value, "timeout_s": SPECIALIST_TIMEOUT_SECONDS},
        )
        agent_output = {
            "intent":   intent.value,
            "status":   "timeout",
            "output":   f"[{intent.value.upper()} agent timed out after {SPECIALIST_TIMEOUT_SECONDS}s — partial result omitted]",
            "metadata": {"latency_ms": elapsed_ms, "timeout_s": SPECIALIST_TIMEOUT_SECONDS},
        }
        llm_calls = 0

    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        logger.error(
            "Specialist node failed with exception",
            extra={"intent": intent.value, "error": str(exc)},
            exc_info=True,
        )
        agent_output = {
            "intent":   intent.value,
            "status":   "error",
            "output":   f"[{intent.value.upper()} agent encountered an error — partial result omitted: {type(exc).__name__}]",
            "metadata": {"latency_ms": elapsed_ms, "error": str(exc)},
        }
        llm_calls = 0

    # The return dict only contains the scratchpad key and actual llm_calls increment.
    # Also pass through session_id and initialize retry_counts if not set.
    return {
        "scratchpad":   [agent_output],
        "llm_calls_used": llm_calls,
    }


async def _run_specialist_work(
    intent: AgentIntent, query: str, state: OrchestratorState
) -> tuple[str, dict, int]:
    """
    Executes domain-specific work for the given intent.

    Returns (output_text, metadata_dict, llm_calls_count).

    MODULE 5 WIRING:
    - AgentIntent.RIGHTS -> Routes to real RightsAgent (RAG via Qdrant + BGE-M3).
    - Other intents (DRAFT, ANALYZE, SCAM, FILING, VAULT) -> Continue hitting
      placeholder echo until their respective modules (6-10) are built.
    """
    if intent == AgentIntent.RIGHTS:
        from agents.rights_agent.agent import get_rights_agent
        from core.config import get_settings
        rights_agent = get_rights_agent()
        response_text, citations, status = await rights_agent.explain_rights(query)
        metadata = {
            "citations": citations,
            "agent": "RightsExplainerAgent",
            "model": "gpt-4o-mini / BGE-M3",
        }
        llm_calls = 1 if (get_settings().OPENAI_API_KEY and status == "ok") else 0
        return response_text, metadata, llm_calls

    if intent == AgentIntent.DRAFT:
        from agents.document_drafter.agent import get_drafter_agent
        drafter_agent = get_drafter_agent()
        doc_type = drafter_agent.match_template_type(query)
        response_text, _, status = await drafter_agent.process_turn(doc_type, {}, user_input=query)
        metadata = {
            "agent": "DocumentDrafterAgent",
            "model": "template_clause_engine",
            "doc_type": doc_type,
            "draft_status": status,
        }
        return response_text, metadata, 0

    if intent == AgentIntent.ANALYZE:
        # Module 7: Document Analyzer — text-only path.
        # Full file analysis is handled via POST /api/v1/analysis/upload.
        # This orchestrator path handles the case where the user asks about
        # document analysis without uploading a file.
        from agents.document_analyzer.agent import get_analyzer_agent
        analyzer_agent = get_analyzer_agent()
        response_text, metadata, llm_calls = await analyzer_agent.explain_for_query(query)
        return response_text, metadata, llm_calls

    if intent == AgentIntent.SCAM:
        # Module 8: Scam Detection Agent — fully DB-grounded, 0 LLM calls.
        # Alert content (legal_reality, recommended_action) comes exclusively from
        # the MongoDB `scam_patterns` collection seeded from scam_seed.json.
        # The LLM is NOT used to generate alert facts — only DB records are shown.
        from agents.scam_detection.agent import get_scam_agent
        scam_agent = get_scam_agent(mongo_db=None)  # mongo_db injected via /scam/check route
        response_text, metadata, llm_calls = await scam_agent.explain_for_query(query)
        return response_text, metadata, llm_calls

    if intent == AgentIntent.FILING:
        # Module 9: Filing Guide Agent — exact-match DB lookup, 0 LLM calls.
        # Authority records come from the MongoDB `filing_authorities` collection
        # seeded from filing_seed.json (verified against RTI Act 2005,
        # Consumer Protection Act 2019, and official government portals).
        # No semantic search — wrong authority = wrong filing = real-world harm.
        from agents.filing_guide.agent import get_filing_agent
        filing_agent = get_filing_agent(mongo_db=None)  # mongo_db injected via /filing/lookup route
        response_text, metadata, llm_calls = await filing_agent.explain_for_query(query, state=state)
        return response_text, metadata, llm_calls

    if intent == AgentIntent.VAULT:
        # Module 10: Vault & Deadline Agent — text-only orchestrator path.
        # Full vault functionality (upload, deadlines, scheduler) is in /api/v1/vault/.
        # This path handles vault-intent text queries from the chat interface.
        from agents.vault_deadline.agent import get_vault_agent
        vault_agent = get_vault_agent()
        response_text, metadata, llm_calls = await vault_agent.explain_for_query(query)
        return response_text, metadata, llm_calls

    # All intents are now handled — this line should never be reached in production.
    await asyncio.sleep(0.01)

    placeholder_text = (
        f"[PLACEHOLDER — {intent.value.upper()} AGENT]\n\n"
        f"Your query: \"{query}\"\n\n"
        f"This is a placeholder response from the {intent.value} specialist agent. "
        f"The real {intent.value} agent will be implemented in Module "
        + {
            AgentIntent.RIGHTS:  "5",
            AgentIntent.DRAFT:   "6",
            AgentIntent.ANALYZE: "7",
            AgentIntent.SCAM:    "8",
            AgentIntent.FILING:  "9",
            AgentIntent.VAULT:   "10",
        }.get(intent, "?")
        + "."
    )
    placeholder_metadata = {
        "agent": f"placeholder_{intent.value}",
        "model": "none (placeholder)",
    }
    return placeholder_text, placeholder_metadata, 0


# =============================================================================
# NODE 3 — Compile Response
# =============================================================================

async def compile_response_node(state: OrchestratorState) -> dict:
    """
    Reads all AgentOutput records from the scratchpad and compiles them
    into a single human-readable final_response.

    Also sets the overall status:
      "ok"      -- all agents that ran succeeded
      "partial" -- mix of successes and failures/timeouts
      "unclear" -- no intents were matched with sufficient confidence
      "error"   -- all agents failed or no agents were dispatched at all

    MODULE 11 EXTENSION POINT:
    Checks state["retry_target"].  If a Confirmation Agent has set this
    to a specific AgentIntent, this function should re-Send to specialist_node
    for that intent instead of returning the final response.  The loopback
    logic is shown as a comment block below.
    """
    # Read from confirmed_outputs (set by confirmation_node) if available;
    # fall back to scratchpad (for tests/paths that skip confirmation).
    # This prevents double-counting: scratchpad uses operator.add reducer
    # (appends), so we read confirmed_outputs which is a plain replace field.
    confirmed = state.get("confirmed_outputs")
    scratchpad: List[AgentOutput] = confirmed if confirmed is not None else state.get("scratchpad", [])
    intents = state.get("intents", [])
    calls_used = state.get("llm_calls_used", 0)
    calls_limit = state.get("llm_calls_limit", MAX_LLM_CALLS_PER_REQUEST)

    # ── Log if LLM calls are approaching the ceiling ─────────────────────────
    if calls_used >= calls_limit:
        logger.warning(
            "LLM call ceiling REACHED on this request",
            extra={"calls_used": calls_used, "calls_limit": calls_limit},
        )
    elif calls_used >= int(calls_limit * 0.8):
        logger.warning(
            "LLM call ceiling at 80%% on this request",
            extra={"calls_used": calls_used, "calls_limit": calls_limit},
        )

    # -- MODULE 11 LOOPBACK -- ACTIVATED --------------------------------------------------
    # The Confirmation Agent sets retry_target when a specialist agent's output fails
    # validation and has retries remaining (retry_count < MAX_RETRIES).
    # compile_response_node reads this and re-dispatches to specialist_node.
    retry_target = state.get("retry_target")
    retry_feedback = state.get("retry_feedback", "")

    if retry_target is not None:
        logger.info(
            "Confirmation Agent requested retry for intent: %s (feedback preview: %s)",
            retry_target.value, retry_feedback[:80] if retry_feedback else "",
        )
        state_copy = {
            **state,
            "retry_target":    None,            # Clear the flag so we don't loop again
            "_current_intent": retry_target,
            "retry_feedback":  retry_feedback,
        }
        return Send("specialist_node", state_copy)
    # -------------------------------------------------------------------------------------

    # ── Unclear intent: no agents were dispatched ─────────────────────────────
    if not intents:
        return {
            "final_response": UNCLEAR_INTENT_RESPONSE,
            "status": "unclear",
        }

    # ── Empty scratchpad means all agents failed silently (should not happen) ─
    if not scratchpad:
        return {
            "final_response": (
                "An unexpected error occurred: no agent results were collected. "
                "Please try again."
            ),
            "status": "error",
        }

    # ── Compile results from scratchpad ──────────────────────────────────────
    successful = [r for r in scratchpad if r["status"] == "ok"]
    failed     = [r for r in scratchpad if r["status"] in ("error", "timeout")]

    # Intent section title mapping for clear multi-intent response formatting
    intent_section_titles = {
        "rights":  "### ⚖️ Legal Rights & Principles",
        "draft":   "### 📝 Document Drafting Assistant",
        "analyze": "### 🔍 Document Risk Analysis",
        "scam":    "### ⚠️ Scam Safety Alert",
        "filing":  "### 📋 Legal Filing & Portal Guide",
        "vault":   "### 📁 Vault & Deadline Management",
    }

    # Build the response body from successful results
    sections = []
    for result in successful:
        intent_val = result.get("intent", "")
        if len(successful) > 1:
            header = intent_section_titles.get(intent_val, f"### {intent_val.title()}")
            sections.append(f"{header}\n\n{result['output']}")
        else:
            sections.append(result["output"])

    # Add a note for failed agents so the user knows some info may be missing
    if failed:
        failed_names = ", ".join(r["intent"].upper() for r in failed)
        sections.append(
            f"\n---\n"
            f"Note: The following specialist agent(s) could not complete their response "
            f"and have been omitted: {failed_names}. "
            f"Please try again or rephrase your query."
        )

    final_response = "\n\n".join(sections).strip()

    # ── Append contradiction note if the Confirmation Agent flagged one ────────
    contradiction_note = state.get("contradiction_note")
    if contradiction_note:
        final_response += contradiction_note

    # ── Determine overall status ──────────────────────────────────────────────
    if successful and failed:
        overall_status = "partial"
    elif successful and not failed:
        overall_status = "ok"
    else:
        overall_status = "error"
        final_response = (
            "All specialist agents encountered errors. "
            "Please try again. If this persists, contact support."
        )

    logger.info(
        "Response compiled",
        extra={
            "status":     overall_status,
            "successful": len(successful),
            "failed":     len(failed),
            "calls_used": calls_used,
        },
    )

    return {
        "final_response": final_response,
        "status": overall_status,
    }


# =============================================================================
# Graph Assembly
# =============================================================================

def build_orchestrator_graph():
    """
    Assembles and compiles the LEXIS orchestrator LangGraph.

    GRAPH TOPOLOGY (Module 11 - Confirmation Agent + retry loopback):

        START -> classify_intent_node
                        |
              fan_out_router() [conditional, returns List[Send]]
                        |
            +-----------+-----------+
            |                       |       (up to N parallel)
      specialist_node         specialist_node
        (rights)                (filing)
            +-----------+-----------+
             All finish, scratchpad merged via operator.add reducer
                        |
               confirmation_node  <--- retry loopback from compile_response_node
                        |
              compile_response_node
                        |
         [if retry_target] -> Send back to specialist_node (loopback, max 3x)
                        |
                       END

    RETRY ROUTING:
    compile_response_node checks state["retry_target"].  If set (Confirmation
    Agent flagged a failing agent), compile re-dispatches to specialist_node
    for that intent instead of returning the final response.  Max 3 retries.

    RETURNS:
    A compiled LangGraph CompiledStateGraph, ready to call with .ainvoke().
    """
    builder = StateGraph(OrchestratorState)

    # -- Register nodes --------------------------------------------------------
    from agents.confirmation_agent.agent import confirmation_node as _confirmation_node
    builder.add_node("classify_intent_node", classify_intent_node)
    builder.add_node("specialist_node",       specialist_node)
    builder.add_node("confirmation_node",     _confirmation_node)   # NEW: Module 11
    builder.add_node("compile_response_node", compile_response_node)

    # -- Wiring ----------------------------------------------------------------
    # Entry -> classifier (always)
    builder.add_edge(START, "classify_intent_node")

    # Classifier -> fan-out router (conditional edge returns List[Send])
    # The fan_out_router either fans out to multiple specialist_node copies
    # (concurrent, one per intent) or routes directly to compile_response_node
    # if no clear intent was detected.
    builder.add_conditional_edges("classify_intent_node", fan_out_router)

    # Each specialist_node copy -> confirmation_node (Module 11 insertion)
    # Previously this went directly to compile_response_node.
    builder.add_edge("specialist_node", "confirmation_node")

    # confirmation_node -> compile_response_node (always)
    # compile_response_node checks retry_target and may loop back to specialist_node
    # via the Send returned in the now-activated loopback branch.
    builder.add_edge("confirmation_node", "compile_response_node")

    # compile_response_node -> END
    builder.add_edge("compile_response_node", END)

    return builder.compile()


# ── Module-level compiled graph (singleton) ───────────────────────────────────
# Import this in the API route with:  from agents.orchestrator.agent import orchestrator_graph
orchestrator_graph = build_orchestrator_graph()
