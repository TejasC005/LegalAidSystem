"""
╔══════════════════════════════════════════════════════════════════════════════╗
║          LEXIS Orchestrator — Shared State Schema (Module 4)                ║
╚══════════════════════════════════════════════════════════════════════════════╝

WHAT IS A LANGGRAPH STATE AND WHY DO WE NEED IT?
─────────────────────────────────────────────────
A LangGraph graph is a state machine.  A state machine is a program that:

  1. Holds a snapshot of all relevant data (the "state").
  2. Passes that snapshot through a series of processing steps (the "nodes").
  3. Each node reads what it needs from the state and writes its result back.
  4. A special rule ("edge") decides which node runs next.

Without a shared state, every node would have to pass data to the next node
explicitly — like passing a shopping bag from person to person where each
person can only see what the person before them put in.

With a shared state, every node reads from and writes to one central object,
like a whiteboard that everyone in the room can see and write on.  This is
why the same state is "shared across agents".

WHY NOT JUST USE if/else IN ONE FUNCTION?
─────────────────────────────────────────
If we classified the intent and then called each agent inside one big Python
function, the agents would run one after the other (sequentially).  The
second agent would only start after the first finished.  For 3 agents on one
query, the user would wait 3× as long.

A graph lets us ROUTE: after classification, we send the state to multiple
nodes that run at the SAME TIME (concurrently).  The user waits for the
slowest agent, not the sum of all agents.  This is not "just calling an LLM"
— it is orchestrating multiple LLM calls concurrently, with controlled state,
failure isolation, and a defined path to compile the results.

HOW CONCURRENT NODE EXECUTION DIFFERS FROM SEQUENTIAL
───────────────────────────────────────────────────────
Sequential (bad):  classify → agentA (3 s) → agentB (3 s) → agentC (3 s) = 9 s total
Concurrent (good): classify → agentA ╮
                             → agentB ├─ all run at once ─→ compile = ~3 s total
                             → agentC ╯

LangGraph achieves this via the Send API: a "router" function returns a list
of Send objects, each specifying a target node.  LangGraph schedules all of
them in the SAME super-step, which means they run in parallel.

WHY REDUCERS ARE REQUIRED FOR CONCURRENT WRITES
─────────────────────────────────────────────────
If two nodes try to write to the same state key at the same time, the last
one to finish would overwrite the first — you would lose data.  A "reducer"
is a function that tells LangGraph HOW to merge multiple writes to the same
key.

  Annotated[List[AgentOutput], operator.add]

means "when multiple nodes write to `scratchpad`, append all their lists
together" — like appending to a shared list, safe under any ordering.
"""

import operator
from enum import Enum
from typing import Annotated, Any, Dict, List, Optional

from typing_extensions import TypedDict

# ── Reducer for retry_counts dict ─────────────────────────────────────────────
# When multiple parallel nodes return retry_counts updates, we need to MERGE
# the dicts (not overwrite).  operator.add works for lists but not dicts.
# We define a custom reducer: merge two dicts, taking the MAX value per key.
# This is safe under concurrent writes: if two parallel nodes both increment
# the retry counter for the same intent, the higher value wins (conservative).
def _merge_retry_counts(a: Dict[str, int], b: Dict[str, int]) -> Dict[str, int]:
    merged = dict(a)
    for k, v in b.items():
        merged[k] = max(merged.get(k, 0), v)
    return merged


# ── Intent categories ─────────────────────────────────────────────────────────

class AgentIntent(str, Enum):
    """
    The six specialist agent categories that the orchestrator can route to.

    A single citizen query can match MORE THAN ONE intent.  For example:
    "My landlord is not returning my deposit and I want to file a complaint"
    matches both RIGHTS (tenant rights) and FILING (complaint filing guide).
    When that happens, both specialist nodes run concurrently.
    """
    RIGHTS  = "rights"    # Explain legal rights (Module 5)
    DRAFT   = "draft"     # Draft a legal document (Module 6)
    ANALYZE = "analyze"   # Analyze a document for risk (Module 7)
    SCAM    = "scam"      # Detect and explain a scam (Module 8)
    FILING  = "filing"    # Guide on where/how to file a complaint (Module 9)
    VAULT   = "vault"     # Vault & deadline management (Module 10)


# ── Per-agent output record ───────────────────────────────────────────────────

class AgentOutput(TypedDict):
    """
    One record written by a specialist node into the shared scratchpad.

    Each specialist node produces exactly ONE AgentOutput.  All of them are
    collected in the `scratchpad` list, which is then read by the compiler
    node to assemble the final response.

    `status` values:
      "ok"      — agent completed successfully
      "error"   — agent threw an exception (partial result: still included)
      "timeout" — agent hit its wall-clock limit (partial result: included)
    """
    intent:   str               # Which AgentIntent this result came from
    status:   str               # "ok" | "error" | "timeout"
    output:   str               # The agent's prose answer (or error description)
    metadata: Dict[str, Any]    # Extra info: latency_ms, model used, etc.


# ── Full orchestrator state ───────────────────────────────────────────────────

class OrchestratorState(TypedDict):
    """
    The single shared state object that flows through every node in the graph.

    ┌─────────────────────────────────────────────────────────────────────┐
    │  FIELD                     │  WHO WRITES IT                        │
    ├─────────────────────────────────────────────────────────────────────┤
    │  query                     │  API layer (initial state)            │
    │  session_id                │  API layer (random UUID per request)  │
    │  conversation_history      │  API layer + memory module (M11)      │
    │  intents                   │  classify_intent_node                 │
    │  confidence                │  classify_intent_node                 │
    │  scratchpad                │  each specialist_node (via reducer)   │
    │  final_response            │  compile_response_node                │
    │  status                    │  compile_response_node                │
    │  llm_calls_used            │  classify + each specialist node      │
    │  llm_calls_limit           │  API layer (initial state)            │
    │  retry_target              │  Module 11 Confirmation Agent         │
    │  retry_counts              │  Module 11 Confirmation Agent         │
    │  retry_feedback            │  Module 11 Confirmation Agent         │
    │  contradiction_note        │  Module 11 Confirmation Agent         │
    └─────────────────────────────────────────────────────────────────────┘
    """

    # ── Input ────────────────────────────────────────────────────────────
    query: str
    """The raw citizen query string, as received from the frontend."""

    session_id: str
    """
    Random UUID identifying this conversation session.
    Used by the Session Memory Store (Module 11) to key Redis hashes.
    NOT derived from the user's phone or MongoDB _id — generated fresh
    per request via uuid4().
    """

    conversation_history: List[Dict[str, str]]
    """
    Prior turns in this session (list of {"role": "user"|"assistant", "content": "..."}).
    Passed to the LLM for context.  Empty list for first-turn queries.
    """

    # ── Classification outputs ───────────────────────────────────────────
    intents: List[AgentIntent]
    """
    Detected intents for this query (empty list = unclear, 1+ = route to those agents).
    Populated by classify_intent_node.  The fan_out_router reads this list
    to decide how many Send objects to create (one per intent).
    """

    confidence: float
    """
    Classifier confidence in [0.0, 1.0].  Below 0.4 → status = "unclear"
    even if intents were detected.
    """

    # ── Concurrent agent outputs (reducer = append-safe under parallelism) ─
    scratchpad: Annotated[List[AgentOutput], operator.add]
    """
    Outputs from all specialist nodes.  Each specialist appends ONE AgentOutput
    to this list.  The `operator.add` reducer means LangGraph APPENDS new
    entries instead of overwriting, making this safe when multiple agents
    run concurrently.

    This is the "shared scratchpad state across agents" from the project spec.
    """

    # ── Compiled result ──────────────────────────────────────────────────
    final_response: str
    """Human-readable, compiled response from all agent outputs."""

    status: str
    """
    Overall status of the request:
      "ok"      — all matched agents succeeded
      "partial" — at least one agent succeeded, at least one failed/timed out
      "unclear" — classifier could not determine intent with enough confidence
      "error"   — all agents failed or no agents were dispatched
    """

    # ── Cost / latency guardrails ─────────────────────────────────────────
    llm_calls_used: Annotated[int, operator.add]
    """
    Running count of LLM calls made during this request (classifier + all agents).

    Uses operator.add as a reducer so that when multiple specialist nodes run
    concurrently and each increments this counter, LangGraph SUMS all the
    increments instead of raising InvalidUpdateError for concurrent writes.
    """

    llm_calls_limit: int
    """
    Maximum LLM calls allowed per request.  Set by the API layer from settings.
    The compile_response_node checks this and stops dispatching if exceeded.
    Logged as a WARNING if any request approaches or exceeds this ceiling.
    """

    # ── Module 11: Retry / Loopback ──────────────────────────────────────
    retry_target: Optional[AgentIntent]
    """
    Set by the Confirmation Agent when an agent's output fails validation
    and has retries remaining.  compile_response_node routes back to
    specialist_node for this intent.

    None when no retry is needed (all agents passed, or cap reached).
    """

    retry_counts: Annotated[Dict[str, int], _merge_retry_counts]
    """
    Tracks how many times each specialist agent has been retried on this
    request.  Key = AgentIntent value string (e.g. "rights").
    Value = number of COMPLETED retries (0 = never retried).

    The Confirmation Agent checks this before requesting a retry:
        if retry_counts.get(intent, 0) >= MAX_RETRIES:
            → return honest fallback instead of routing back

    Uses _merge_retry_counts reducer (takes MAX per key) to be safe
    under concurrent writes from parallel agent nodes.
    """

    retry_feedback: str
    """
    Actionable feedback message sent back to the specialist agent on retry.
    Populated by the Confirmation Agent with the specific failure reason and
    what the agent must produce to pass.

    Empty string when no retry is needed.
    """

    contradiction_note: Optional[str]
    """
    Advisory note appended to the final response when the Confirmation Agent
    detects a cross-agent contradiction (e.g. Rights Agent and Filing Guide
    citing different governing Acts).

    None when no contradiction is detected.
    The note tells the citizen that two responses may be inconsistent and
    advises them to consult a legal professional.
    """

    confirmed_outputs: Optional[List[AgentOutput]]
    """
    The Confirmation Agent writes the validated (and possibly fallback-wrapped)
    agent outputs here instead of back to scratchpad.

    WHY A SEPARATE FIELD:
    scratchpad uses operator.add reducer -- writing back to it from the
    confirmation node would APPEND the approved outputs to the EXISTING
    scratchpad, doubling the entries.  confirmed_outputs has no reducer (plain
    replacement), so it safely overwrites.

    compile_response_node reads confirmed_outputs if non-None, otherwise
    falls back to scratchpad (for tests or code paths that bypass confirmation).
    """
