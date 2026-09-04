"""
=============================================================================
LEXIS — Confirmation Agent: Reflection Logger  (Module 11)
=============================================================================

WHAT IS THIS FILE?
------------------
This module writes a structured log entry to MongoDB for every Confirmation
Agent validation pass.  These logs are queryable by the Admin Dashboard
(Module 12) to understand:
  - How often agents fail their initial validation check
  - Which agents fail most frequently and why
  - How many retries are typically needed
  - Whether any cross-agent contradictions were caught in production

WHY MONGODB FOR REFLECTION LOGS (NOT JUST PYTHON LOGGING)?
-----------------------------------------------------------
Python's structured JSON logger (set up in Module 1) writes to stdout —
useful for real-time debugging but not designed for historical queries.
The Admin Dashboard needs to query "how many Rights Agent rejections
happened today?" or "list all sessions with contradiction catches this week".
That requires persistent, queryable storage.  MongoDB's flexible document
model suits this well — we don't know in advance exactly what fields future
reflection entries might need.

PII SCRUBBING (REQUIRED BY DESIGN)
------------------------------------
Reflection logs MUST NOT contain personally identifiable information.
The session_id is a random UUID, NOT derived from the user's phone number or
MongoDB _id.  We explicitly exclude:
  - Phone numbers (not in state during the agent execution path)
  - user_id (not in agent state — only in the auth layer)
  - The text of the citizen's query and agent outputs (may contain PII)
    → We log lengths and intent names only, not content

The only "personal" data in a reflection log is the session_id, which is
a random UUID that expires with the session.  It cannot be used to
re-identify a citizen without access to the Redis session store.

WHAT IS LOGGED
--------------
  session_id        : Random UUID (not user-derived)
  timestamp         : UTC ISO timestamp
  agents_checked    : List of intent names (e.g. ["rights", "filing"])
  pass_fail         : "pass" | "fail" | "contradiction" | "fallback"
  retry_count       : How many retries had occurred before this check
  rejection_reason  : What failed (criterion description), no output text
  contradiction     : Contradiction description if caught, else null
  query_length      : Character count of query (not the query itself)
  response_length   : Character count of compiled response (not content)
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# MongoDB collection name for reflection logs (overridden by settings)
DEFAULT_REFLECTION_LOG_COLLECTION: str = "reflection_logs"


# =============================================================================
# PII Scrubbing
# =============================================================================

def _scrub_pii(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Removes any fields that could identify a citizen.

    This is a defensive layer — the log entries built in this module are
    already designed to exclude PII, but this function adds a final guard
    in case a caller accidentally includes a forbidden field.

    Forbidden field names (case-insensitive):
      phone, phone_number, user_id, user_phone, email, name, address,
      query, output, content, response  (text content fields)
    """
    FORBIDDEN_KEYS = {
        "phone", "phone_number", "phonenumber",
        "user_id", "userid", "user_phone",
        "email", "name", "address",
        "query", "output", "content", "response",
        "raw_query", "raw_output", "citizen_query",
    }
    return {
        k: v
        for k, v in data.items()
        if k.lower() not in FORBIDDEN_KEYS
    }


# =============================================================================
# Reflection Log Writer
# =============================================================================

class ReflectionLogger:
    """
    Writes structured, PII-scrubbed reflection log entries to MongoDB.

    The MongoDB client is injected (not created here) so this class can
    be used without a live DB during testing — when db is None, all writes
    are no-ops and a debug message is logged instead.
    """

    def __init__(
        self,
        db: Any = None,
        collection_name: str = DEFAULT_REFLECTION_LOG_COLLECTION,
    ):
        """
        Parameters
        ----------
        db              : Motor async database object (app.state.db).
                          If None, all writes are logged to stdout only.
        collection_name : MongoDB collection name for reflection logs.
        """
        self._db = db
        self._collection_name = collection_name

    async def log_reflection_pass(
        self,
        session_id: str,
        agents_checked: List[str],
        pass_fail: str,
        retry_count: int,
        rejection_reason: Optional[str] = None,
        contradiction: Optional[str] = None,
        query_length: int = 0,
        response_length: int = 0,
    ) -> None:
        """
        Writes one reflection log entry.

        Parameters
        ----------
        session_id        : Random UUID for this session (NOT user_id, NOT phone)
        agents_checked    : Intent names checked (e.g. ["rights", "filing"])
        pass_fail         : One of "pass" | "fail" | "contradiction" | "fallback"
        retry_count       : Number of retries already consumed before this pass
        rejection_reason  : Short description of why validation failed (no output text)
        contradiction     : Description of cross-agent contradiction if caught
        query_length      : Character length of citizen's query (not the query itself)
        response_length   : Character length of compiled response (not content)
        """
        if pass_fail not in ("pass", "fail", "contradiction", "fallback"):
            logger.warning(
                "ReflectionLogger: unexpected pass_fail value '%s' — defaulting to 'fail'",
                pass_fail,
            )
            pass_fail = "fail"

        # Build the log entry — only metadata, no content
        entry: Dict[str, Any] = {
            "session_id": session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agents_checked": agents_checked,
            "pass_fail": pass_fail,
            "retry_count": retry_count,
            "rejection_reason": rejection_reason or "",
            "contradiction_caught": contradiction or None,
            "query_length": query_length,
            "response_length": response_length,
        }

        # Final PII scrub (defensive)
        entry = _scrub_pii(entry)

        # ── Structured Python log (always) ────────────────────────────────────
        log_method = logger.warning if pass_fail in ("fail", "contradiction", "fallback") else logger.info
        log_method(
            "REFLECTION_PASS session=%s pass_fail=%s agents=%s retry_count=%d reason=%s contradiction=%s",
            session_id,
            pass_fail,
            agents_checked,
            retry_count,
            rejection_reason or "none",
            contradiction or "none",
            extra={
                "reflection_session_id": session_id,
                "reflection_pass_fail": pass_fail,
                "reflection_agents": agents_checked,
                "reflection_retry_count": retry_count,
            },
        )

        # ── MongoDB write (when DB is available) ──────────────────────────────
        if self._db is None:
            logger.debug("ReflectionLogger: no DB — skipping MongoDB write for session %s", session_id)
            return

        try:
            collection = self._db[self._collection_name]
            await collection.insert_one(entry)
        except Exception as exc:
            # Logging failures must never crash the main request path
            logger.error(
                "ReflectionLogger: MongoDB write failed for session %s: %s",
                session_id, exc,
                exc_info=False,  # Don't include full traceback — this is a non-critical side effect
            )


# ── Singleton factory ─────────────────────────────────────────────────────────
_reflection_logger_instance: Optional[ReflectionLogger] = None


def get_reflection_logger(
    db: Any = None,
    collection_name: str = DEFAULT_REFLECTION_LOG_COLLECTION,
) -> ReflectionLogger:
    """
    Returns (creating if necessary) the application-wide ReflectionLogger.

    In tests, use ReflectionLogger(db=None) directly — writes go to
    Python logging only, no MongoDB needed.
    """
    global _reflection_logger_instance
    if _reflection_logger_instance is None:
        _reflection_logger_instance = ReflectionLogger(db=db, collection_name=collection_name)
    return _reflection_logger_instance
