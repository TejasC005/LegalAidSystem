"""
=============================================================================
LEXIS — Session Memory Store  (Module 11)
=============================================================================

WHAT IS THIS FILE?
------------------
This module implements the Redis-backed session memory store for LEXIS.

A "session" is one citizen's ongoing conversation identified by a unique
`session_id`.  The store persists:
  - Recent conversation turns (user messages + agent replies)
  - Cross-agent context (e.g. the doc_type a citizen mentioned earlier
    that the Filing Guide can reuse without re-asking)

WHY REDIS FOR SESSIONS?
-----------------------
Redis is an in-memory data store — reads and writes are microseconds, not
milliseconds.  Session data must be read at the START of every request
(to give agents context) and written at the END (to remember the result).
A MongoDB round-trip here would add 20–40 ms to every query.  Redis adds
~1 ms.  Sessions also have a natural TTL (e.g. 24 hours of inactivity) —
Redis's built-in key expiry handles this trivially.

WHY CONCURRENT-WRITE SAFETY MATTERS HERE
------------------------------------------
From Module 6 onward, LEXIS can dispatch 2+ specialist agents on one request
in parallel.  Each agent may want to update the session (e.g. store the
context it used).  Without a lock, two agents writing to the same Redis hash
key at the same moment could corrupt each other's data.

We protect against this with an asyncio.Lock keyed per session_id.  This is
an in-process lock — it prevents two coroutines in the SAME Python process
from writing the same session simultaneously.  In a multi-process deployment
(multiple uvicorn workers), a Redis-side lock (SETNX / Redlock) would be
required; that is flagged in the docstring below for Module 14 hardening.

DATA STRUCTURE
--------------
We store each session as a Redis Hash:
  Key:   lexis:session:{session_id}
  Fields:
    "turns"    → JSON list of {"role":"user"|"assistant", "content":"..."}
    "context"  → JSON dict of arbitrary cross-agent key-value pairs
    "created"  → ISO timestamp string
    "updated"  → ISO timestamp string

The entire hash expires after SESSION_TTL_SECONDS of inactivity (the TTL
is reset on every write).

PII HANDLING
------------
We store only the conversation turn content — which may contain the citizen's
description of their legal problem.  We do NOT store phone numbers, user_ids,
or JWT tokens in session memory.  The session_id is a random UUID generated
per-request (not derived from any user identifier).

    session_id = str(uuid4())  ← random, not user-derived
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
# Default session TTL: 24 hours.  Overridden via Settings.SESSION_TTL_SECONDS.
DEFAULT_SESSION_TTL_SECONDS: int = 86_400  # 24 hours

# Maximum number of turns to retain per session (rolling window).
# Older turns are dropped to keep the Redis entry bounded.
MAX_TURNS_PER_SESSION: int = 20

# Redis key prefix — keeps LEXIS keys namespaced and identifiable in monitoring.
SESSION_KEY_PREFIX: str = "lexis:session:"

# ── Per-session asyncio locks ─────────────────────────────────────────────────
# Maps session_id → asyncio.Lock.  Prevents concurrent writes within one process.
#
# ⚠  MULTI-PROCESS NOTE (for Module 14 hardening):
#    This lock is only effective within a single Python process.
#    In production with multiple uvicorn workers, replace with a Redis-based
#    distributed lock (e.g. redis-py's Redlock or SETNX pattern) to prevent
#    cross-process write races.
_session_locks: Dict[str, asyncio.Lock] = {}
_locks_dict_lock: asyncio.Lock = asyncio.Lock()  # Protects the dict itself


async def _get_session_lock(session_id: str) -> asyncio.Lock:
    """
    Returns (creating if necessary) the asyncio.Lock for a given session_id.

    We need a meta-lock on the _session_locks dict itself because two
    coroutines might try to create the same session_id's lock simultaneously
    — without protection, both would create different Lock objects and the
    individual locks would provide no mutual exclusion.
    """
    async with _locks_dict_lock:
        if session_id not in _session_locks:
            _session_locks[session_id] = asyncio.Lock()
        return _session_locks[session_id]


# =============================================================================
# SessionStore class
# =============================================================================

class SessionStore:
    """
    Redis-backed session memory store with concurrent-write safety.

    Usage
    -----
    This class is designed to be called with an injected redis client
    (the same redis.asyncio client the rest of LEXIS uses, stored in
    app.state.redis).  No connection is opened or closed here — the
    caller owns the connection lifecycle.

    Example
    -------
        store = SessionStore(redis_client=app.state.redis, ttl=86400)
        # Load context at the start of a request:
        history = await store.get_turns(session_id)
        ctx      = await store.get_context(session_id)
        # Write at the end:
        await store.add_turn(session_id, role="user", content=query)
        await store.add_turn(session_id, role="assistant", content=reply)
        await store.set_context(session_id, {"doc_type": "rti_application"})
    """

    def __init__(
        self,
        redis_client: Any = None,
        ttl: int = DEFAULT_SESSION_TTL_SECONDS,
    ):
        """
        Parameters
        ----------
        redis_client : redis.asyncio.Redis (or compatible)
            Async Redis client.  If None, all operations are no-ops and a
            warning is logged.  This allows tests to instantiate without Redis.
        ttl : int
            Time-to-live in seconds for session keys (resets on every write).
        """
        self._redis = redis_client
        self._ttl = ttl

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _key(self, session_id: str) -> str:
        """Returns the Redis key string for a given session_id."""
        return f"{SESSION_KEY_PREFIX}{session_id}"

    async def _redis_hget(self, key: str, field: str) -> Optional[str]:
        """Safe Redis HGET with None fallback when Redis is unavailable."""
        if not self._redis:
            return None
        try:
            value = await self._redis.hget(key, field)
            # redis-py returns bytes; decode to str
            if isinstance(value, bytes):
                value = value.decode("utf-8")
            return value
        except Exception as exc:
            logger.warning("SessionStore.hget failed for key=%s field=%s: %s", key, field, exc)
            return None

    async def _redis_hset_multi(self, key: str, mapping: Dict[str, str], ttl: int) -> None:
        """Safe Redis HSET + EXPIRE with error handling."""
        if not self._redis:
            return
        try:
            await self._redis.hset(key, mapping=mapping)
            await self._redis.expire(key, ttl)
        except Exception as exc:
            logger.warning("SessionStore.hset failed for key=%s: %s", key, exc)

    # ── Public API ────────────────────────────────────────────────────────────

    async def get_turns(self, session_id: str) -> List[Dict[str, str]]:
        """
        Returns the conversation turn history for this session.

        Returns an empty list if the session doesn't exist yet or Redis is
        unavailable (graceful degradation — agent still works, just without
        prior context).
        """
        raw = await self._redis_hget(self._key(session_id), "turns")
        if not raw:
            return []
        try:
            turns = json.loads(raw)
            if not isinstance(turns, list):
                return []
            return turns
        except json.JSONDecodeError:
            logger.warning("SessionStore: corrupt turns JSON for session %s", session_id)
            return []

    async def add_turn(
        self,
        session_id: str,
        role: str,
        content: str,
    ) -> None:
        """
        Appends one conversation turn to the session history.

        Concurrent-safe: acquires the per-session asyncio.Lock before
        read-modify-write to prevent race conditions when multiple agents
        update the same session simultaneously.

        Parameters
        ----------
        role    : "user" | "assistant"
        content : The message text.  MUST NOT contain phone numbers or PII
                  beyond what the citizen themselves typed.
        """
        lock = await _get_session_lock(session_id)
        async with lock:
            turns = await self.get_turns(session_id)
            turns.append({
                "role": role,
                "content": content,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            # Rolling window — drop oldest turns beyond the limit
            if len(turns) > MAX_TURNS_PER_SESSION:
                turns = turns[-MAX_TURNS_PER_SESSION:]

            key = self._key(session_id)
            now_iso = datetime.now(timezone.utc).isoformat()

            # Preserve created timestamp; set/update updated timestamp
            created = await self._redis_hget(key, "created") or now_iso
            await self._redis_hset_multi(key, {
                "turns":   json.dumps(turns),
                "created": created,
                "updated": now_iso,
            }, ttl=self._ttl)

        logger.debug(
            "SessionStore.add_turn: session=%s role=%s content_len=%d",
            session_id, role, len(content),
        )

    async def get_context(self, session_id: str) -> Dict[str, Any]:
        """
        Returns the cross-agent context dict for this session.

        Cross-agent context is arbitrary key-value data that one specialist
        agent produces and another can consume — e.g.:
          - Filing Guide stores {"doc_type": "rti_application"}
          - Document Drafter reads it on the next turn to skip re-asking
        """
        raw = await self._redis_hget(self._key(session_id), "context")
        if not raw:
            return {}
        try:
            ctx = json.loads(raw)
            return ctx if isinstance(ctx, dict) else {}
        except json.JSONDecodeError:
            return {}

    async def set_context(
        self,
        session_id: str,
        updates: Dict[str, Any],
    ) -> None:
        """
        Merges `updates` into the cross-agent context dict.

        Concurrent-safe: acquires the per-session lock before
        read-modify-write merge.

        Parameters
        ----------
        updates : Key-value pairs to merge into the context.
                  Existing keys are overwritten; unmentioned keys are preserved.
        """
        lock = await _get_session_lock(session_id)
        async with lock:
            ctx = await self.get_context(session_id)
            ctx.update(updates)

            key = self._key(session_id)
            now_iso = datetime.now(timezone.utc).isoformat()
            created = await self._redis_hget(key, "created") or now_iso
            await self._redis_hset_multi(key, {
                "context": json.dumps(ctx),
                "created": created,
                "updated": now_iso,
            }, ttl=self._ttl)

        logger.debug(
            "SessionStore.set_context: session=%s keys=%s",
            session_id, list(updates.keys()),
        )

    async def clear(self, session_id: str) -> None:
        """Deletes all session data for session_id (e.g. on logout)."""
        if not self._redis:
            return
        try:
            await self._redis.delete(self._key(session_id))
            logger.info("SessionStore.clear: session=%s deleted", session_id)
        except Exception as exc:
            logger.warning("SessionStore.clear failed for session %s: %s", session_id, exc)


# ── Singleton factory ─────────────────────────────────────────────────────────
# The session store needs a live Redis client, which is only available after
# the FastAPI lifespan hook runs.  So we use a lazy factory rather than a
# module-level singleton.

_session_store_instance: Optional[SessionStore] = None


def get_session_store(redis_client: Any = None, ttl: int = DEFAULT_SESSION_TTL_SECONDS) -> SessionStore:
    """
    Returns (creating if necessary) the application-wide SessionStore.

    In production, call this ONCE from the lifespan hook with the real
    redis_client.  Subsequent calls return the cached instance.

    In tests, create a fresh SessionStore(redis_client=None) directly —
    the None client causes all operations to be no-ops, so tests don't
    need a real Redis server.
    """
    global _session_store_instance
    if _session_store_instance is None:
        _session_store_instance = SessionStore(redis_client=redis_client, ttl=ttl)
    return _session_store_instance
