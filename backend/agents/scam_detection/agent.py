"""
=============================================================================
LEXIS Scam Detection Agent — Module 8: Scam Detection Engine
=============================================================================

BEGINNER EXPLANATION: WHY MUST SCAM ALERTS BE GROUNDED IN THE DATABASE?
------------------------------------------------------------------------
Scam detection is safety-sensitive information. Here is what could go wrong
if we let an LLM generate alert content freely:

  Citizen says: "Someone called claiming to be from CBI and asked for money"
  LLM (without grounding): "This may be a digital arrest scam. CBI can arrest
    you under Section 120B if digital evidence is found against you. You should
    cooperate and pay the fine to resolve this quickly."

  That LLM response sounds authoritative but is COMPLETELY WRONG and HARMFUL.
  A citizen reading it might actually pay the fraudster believing it is legal.

  With DB-grounded alerts:
  ─ We retrieve the "Digital Arrest Scam" record from our curated MongoDB.
  ─ The legal_reality field says: "There is NO concept of 'digital arrest'
    in Indian law... no legitimate agency can arrest via phone."
  ─ The recommended_action says: "Disconnect the call immediately."
  ─ These facts were written by humans, checked against official MHA/UIDAI/RBI
    sources, and are stored in a database an admin can correct if wrong.
  ─ The LLM (if used) can only REFORMAT this text — it cannot INVENT new facts.

  Key principle: the LLM is a text formatter here, NOT the source of truth.
  The database is the source of truth.

MATCHING PIPELINE (TWO LAYERS):
---------------------------------
Layer 1 — KEYWORD/REGEX FAST PATH:
  Each pattern in the seed database has a `keywords` list.
  We compile these into a fast lookup (O(n) scan, no embedding needed).
  High-confidence keywords like "digital arrest", "CBI called", "UPI QR scan
  to receive money" are near-certain pattern indicators — no ambiguity.
  If a keyword match is found, we skip embedding and go straight to DB lookup.

Layer 2 — SEMANTIC SIMILARITY SEARCH (Qdrant + BGE-M3):
  If no keyword match, we embed the citizen's description via BGE-M3 and
  search the Qdrant `scam_patterns` collection.
  If similarity score ≥ SCAM_CONFIDENCE_THRESHOLD, we take the top match.
  If below threshold, we return a safe "not recognised" fallback.

DB GROUNDING STEP (SAFETY INVARIANT):
  Whether from keyword or semantic match, we take the matched `pattern_id`
  and fetch the FULL record from MongoDB `scam_patterns`.
  If the MongoDB record is missing (e.g., Qdrant and Mongo are out of sync),
  we return a safe fallback RATHER THAN fabricating alert content.
  This is the "grounding check" — it guarantees traceability.
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from qdrant_client import QdrantClient

from agents.orchestrator.state import AgentOutput, OrchestratorState
from core.config import get_settings
from db.qdrant_client import get_qdrant_client
from services.rag.embedder import BGEM3Embedder

logger = logging.getLogger(__name__)

# ── Thresholds ────────────────────────────────────────────────────────────────
# Minimum cosine similarity score for a semantic match to be considered valid.
# Below this, we return a "no match" safe response rather than guess.
SCAM_CONFIDENCE_THRESHOLD: float = 0.30

# Qdrant collection that stores scam pattern embeddings
SCAM_COLLECTION_NAME: str = "scam_patterns"

# Seed file path (for standalone in-process seeding in tests / startup)
SCAM_SEED_FILE = (
    Path(__file__).parent.parent.parent / "data" / "scam_patterns" / "scam_seed.json"
)

# Safe fallback shown when no pattern is confidently matched
NO_MATCH_RESPONSE = (
    "⚠️ This situation was not matched against any known scam pattern in our current database.\n\n"
    "This does NOT mean the situation is safe. If you suspect fraud, please:\n"
    "1. **Do not transfer any money or share any OTP.**\n"
    "2. **File a complaint** immediately at cybercrime.gov.in\n"
    "3. **Call the National Cyber Helpline: 1930**\n\n"
    "Our scam database is actively expanded by our administrators. "
    "If you believe this is a new scam pattern, please report it via our feedback system."
)


@dataclass
class ScamAlertResult:
    """
    Structured output from the Scam Detection Agent.

    Every field that displays to the citizen MUST trace to a seeded DB entry.
    The `db_id` field is the traceability key — an admin can look up exactly
    which database record generated this alert.
    """
    matched: bool
    db_id: str = ""                     # e.g., "SCAM_001" — traceability field
    pattern_name: str = ""
    severity: str = "MEDIUM"
    match_method: str = "none"          # "keyword" | "semantic" | "none"
    confidence_score: float = 0.0
    description: str = ""               # from DB: what this scam is
    legal_reality: str = ""             # from DB: factual legal position
    recommended_action: str = ""        # from DB: what to do
    reporting_channels: List[str] = field(default_factory=list)  # from DB
    source_ref: str = ""                # from DB: official reference
    safe_fallback_message: str = ""     # set when matched=False


class ScamDetectionAgent:
    """
    Scam Detection Specialist Agent.

    Two-layer matching pipeline with DB-grounding safety invariant.
    All alert content served from MongoDB — no LLM fabrication.
    """

    def __init__(
        self,
        qdrant_client: Optional[QdrantClient] = None,
        embedder: Optional[BGEM3Embedder] = None,
        mongo_db=None,
    ):
        self.qdrant_client = qdrant_client or get_qdrant_client()
        self.embedder = embedder or BGEM3Embedder()
        self.mongo_db = mongo_db  # Motor async DB instance (None in offline/test mode)

        # In-memory pattern cache: loaded from seed file for keyword matching
        # and as fallback when MongoDB is unavailable (tests / offline dev)
        self._pattern_cache: Dict[str, Dict] = {}
        self._keyword_map: List[Tuple[str, str]] = []  # (compiled_pattern_str, pattern_id)
        self._load_pattern_cache()
        self._ensure_qdrant_seeded()

    # =========================================================================
    # Startup helpers
    # =========================================================================

    def _ensure_qdrant_seeded(self) -> None:
        """
        Self-healing check: ensures the `scam_patterns` collection is initialized
        and seeded in self.qdrant_client. If missing or unseeded, seeds it automatically.
        """
        try:
            if self.qdrant_client is None:
                return
            collections = [c.name for c in self.qdrant_client.get_collections().collections]
            if SCAM_COLLECTION_NAME not in collections:
                from services.scam.ingestion import seed_scam_knowledge_base
                logger.info("ScamDetectionAgent: Collection '%s' missing. Auto-seeding now...", SCAM_COLLECTION_NAME)
                seed_scam_knowledge_base(
                    qdrant_client=self.qdrant_client,
                    force_recreate=False,
                    test_mode=getattr(self.embedder, "test_mode", False),
                )
        except Exception as exc:
            logger.warning(
                "ScamDetectionAgent: Could not auto-seed Qdrant collection '%s': %s",
                SCAM_COLLECTION_NAME,
                exc,
            )

    def _load_pattern_cache(self) -> None:
        """
        Loads the seed JSON into memory for:
          1. Keyword matching (no DB or Qdrant needed)
          2. Offline fallback when MongoDB is unavailable (dev / tests)

        This does NOT replace MongoDB as the source of truth for production —
        in production, fetched patterns always come from MongoDB.
        The cache is the fallback, not the primary path.
        """
        import json
        try:
            if not SCAM_SEED_FILE.exists():
                logger.warning("Scam seed file not found for cache load: %s", SCAM_SEED_FILE)
                return

            with open(SCAM_SEED_FILE, "r", encoding="utf-8") as f:
                patterns = json.load(f)

            self._pattern_cache.clear()
            self._keyword_map.clear()

            for p in patterns:
                if not p.get("is_active", True) or p.get("status") == "deactivated":
                    continue
                pid = p["id"]
                self._pattern_cache[pid] = p
                for kw in p.get("keywords", []):
                    kw_clean = kw.strip()
                    if not kw_clean:
                        continue
                    tokens = [re.escape(w) for w in kw_clean.split() if w.strip()]
                    if len(tokens) == 1:
                        # Single word: word-boundary match
                        pattern_str = r'\b' + tokens[0] + r'\b'
                    else:
                        # Multi-word: allow 0 to 2 intervening filler words (e.g. "scan a qr code", "bank account is frozen")
                        pattern_str = r'\b' + r'(?:\s+\w+){0,2}\s+'.join(tokens) + r'\b'
                    self._keyword_map.append((pattern_str, pid))

            logger.info(
                "ScamDetectionAgent: Loaded %d patterns (%d keywords) into cache.",
                len(self._pattern_cache),
                len(self._keyword_map),
            )
        except Exception as exc:
            logger.error("Failed to load scam pattern cache: %s", exc)

    def reload_intelligence(self) -> None:
        """
        Invalidates and reloads the in-memory pattern cache and keyword map.
        Called dynamically when an administrator creates, edits, activates,
        or deactivates a scam intelligence record.
        """
        self._load_pattern_cache()
        logger.info("ScamDetectionAgent: Intelligence cache reloaded dynamically.")

    async def sync_intelligence_from_mongo(self) -> int:
        """
        Asynchronously synchronizes the agent's in-memory keyword map and cache
        from active MongoDB `scam_patterns` records.
        """
        if self.mongo_db is None:
            self._load_pattern_cache()
            return len(self._pattern_cache)

        try:
            cursor = self.mongo_db["scam_patterns"].find(
                {"is_active": {"$ne": False}, "status": {"$ne": "deactivated"}},
                {"_id": 0}
            )
            active_patterns = await cursor.to_list(length=500)
            if not active_patterns:
                self._load_pattern_cache()
                return len(self._pattern_cache)

            self._pattern_cache.clear()
            self._keyword_map.clear()

            for p in active_patterns:
                pid = p["id"]
                self._pattern_cache[pid] = p
                for kw in p.get("keywords", []):
                    kw_clean = kw.strip()
                    if not kw_clean:
                        continue
                    tokens = [re.escape(w) for w in kw_clean.split() if w.strip()]
                    if len(tokens) == 1:
                        pattern_str = r'\b' + tokens[0] + r'\b'
                    else:
                        pattern_str = r'\b' + r'(?:\s+\w+){0,2}\s+'.join(tokens) + r'\b'
                    self._keyword_map.append((pattern_str, pid))

            logger.info(
                "ScamDetectionAgent: Synchronized %d active patterns from MongoDB into cache.",
                len(self._pattern_cache),
            )
            return len(self._pattern_cache)
        except Exception as exc:
            logger.warning("Could not sync patterns from MongoDB, using seed file: %s", exc)
            self._load_pattern_cache()
            return len(self._pattern_cache)

    # =========================================================================
    # Layer 1 — Keyword Matching
    # =========================================================================

    def _keyword_match(self, query: str) -> Optional[str]:
        """
        Scans the query for high-confidence keyword signals.
        Returns the matched pattern_id if found, else None.

        Keywords are compiled as regex patterns for exact sub-phrase matching
        (e.g., "digital arrest" doesn't match "digitally arrested" unless
        both variants are listed — this prevents false positives).
        """
        q_lower = query.lower()
        for keyword_pattern, pattern_id in self._keyword_map:
            if re.search(keyword_pattern, q_lower):
                logger.info(
                    "ScamDetectionAgent: Keyword match '%s' → pattern '%s'",
                    keyword_pattern,
                    pattern_id,
                )
                return pattern_id
        return None

    # =========================================================================
    # Layer 2 — Semantic Search (Qdrant + BGE-M3)
    # =========================================================================

    def _semantic_search(self, query: str, top_k: int = 3) -> List[Tuple[str, float]]:
        """
        Embeds the query and searches the Qdrant `scam_patterns` collection.
        Returns a list of (pattern_id, score) tuples, sorted by descending score.
        """
        try:
            self._ensure_qdrant_seeded()
            query_vector = self.embedder.embed_query(query)

            if hasattr(self.qdrant_client, "query_points"):
                response = self.qdrant_client.query_points(
                    collection_name=SCAM_COLLECTION_NAME,
                    query=query_vector,
                    limit=top_k,
                )
                hits = response.points
            elif hasattr(self.qdrant_client, "search"):
                hits = self.qdrant_client.search(
                    collection_name=SCAM_COLLECTION_NAME,
                    query_vector=query_vector,
                    limit=top_k,
                )
            else:
                logger.error("QdrantClient has no usable search method.")
                return []

            results = []
            for hit in hits:
                pid = getattr(hit, "payload", {}).get("pattern_id", "")
                score = getattr(hit, "score", 0.0)
                if pid:
                    results.append((pid, score))

            logger.info(
                "ScamDetectionAgent: Semantic search returned %d candidates (top score: %.3f)",
                len(results),
                results[0][1] if results else 0.0,
            )
            return results

        except Exception as exc:
            logger.error("ScamDetectionAgent: Qdrant search failed: %s", exc, exc_info=True)
            return []

    # =========================================================================
    # DB Grounding — SAFETY INVARIANT
    # =========================================================================

    async def _fetch_pattern_from_db(self, pattern_id: str) -> Optional[Dict]:
        """
        Fetches the full scam pattern record from MongoDB by pattern_id.

        SAFETY INVARIANT: If MongoDB is unavailable, we fall back to the
        in-memory seed cache (acceptable for dev/testing).
        In production, if neither MongoDB nor cache has the record, we
        return None and the caller will show the safe fallback — never
        fabricated content.
        """
        # Primary: MongoDB (production source of truth)
        if self.mongo_db is not None:
            try:
                doc = await self.mongo_db["scam_patterns"].find_one(
                    {"id": pattern_id}, {"_id": 0}
                )
                if doc:
                    if not doc.get("is_active", True) or doc.get("status") == "deactivated":
                        logger.info("ScamDetectionAgent: Pattern '%s' is inactive/deactivated in DB.", pattern_id)
                        return None
                    return doc
                logger.warning(
                    "ScamDetectionAgent: Pattern '%s' not found in MongoDB — "
                    "falling back to seed cache. Run ingestion to sync.",
                    pattern_id,
                )
            except Exception as exc:
                logger.error(
                    "ScamDetectionAgent: MongoDB lookup failed for '%s': %s. "
                    "Using seed cache fallback.",
                    pattern_id,
                    exc,
                )

        # Fallback: in-memory cache (seeded from JSON on startup)
        cached = self._pattern_cache.get(pattern_id)
        if cached and (not cached.get("is_active", True) or cached.get("status") == "deactivated"):
            return None
        return cached

    # =========================================================================
    # Main Detection Method
    # =========================================================================

    async def check_scam(self, description: str) -> ScamAlertResult:
        """
        Main entry point. Runs the two-layer matching pipeline and returns
        a ScamAlertResult fully grounded in the DB.

        Returns ScamAlertResult with matched=False and a safe fallback message
        if no confident match is found or if the DB record cannot be verified.
        """
        description = description.strip()

        if not description:
            return ScamAlertResult(
                matched=False,
                safe_fallback_message=NO_MATCH_RESPONSE,
            )

        # ── Layer 1: Keyword fast-path ──────────────────────────────────────
        matched_id: Optional[str] = self._keyword_match(description)
        match_method = "keyword"
        confidence = 1.0  # Keyword match is high confidence

        # ── Layer 2: Semantic search (if no keyword match) ──────────────────
        if matched_id is None:
            semantic_results = self._semantic_search(description)
            match_method = "semantic"
            confidence = 0.0

            for pid, score in semantic_results:
                if score >= SCAM_CONFIDENCE_THRESHOLD:
                    matched_id = pid
                    confidence = score
                    break

        # ── No match: return safe fallback (never fabricate) ─────────────────
        if matched_id is None:
            logger.info(
                "ScamDetectionAgent: No confident match for query (len=%d). Returning safe fallback.",
                len(description),
            )
            return ScamAlertResult(
                matched=False,
                match_method="none",
                safe_fallback_message=NO_MATCH_RESPONSE,
            )

        # ── DB Grounding: fetch full record from MongoDB/cache ────────────────
        pattern = await self._fetch_pattern_from_db(matched_id)

        if pattern is None:
            # SAFETY INVARIANT: DB record not found — show safe fallback,
            # never generate content from LLM or memory.
            logger.error(
                "ScamDetectionAgent: GROUNDING FAILURE — pattern '%s' matched but "
                "not found in DB or cache. Returning safe fallback to prevent fabrication.",
                matched_id,
            )
            return ScamAlertResult(
                matched=False,
                match_method=match_method,
                safe_fallback_message=(
                    "A potential scam pattern was detected but could not be verified "
                    "against our database. Please call the National Cyber Helpline: 1930."
                ),
            )

        # ── Return grounded alert ─────────────────────────────────────────────
        logger.info(
            "ScamDetectionAgent: Matched pattern '%s' ('%s') via %s (score=%.3f)",
            pattern["id"],
            pattern.get("name", ""),
            match_method,
            confidence,
        )

        return ScamAlertResult(
            matched=True,
            db_id=pattern["id"],
            pattern_name=pattern.get("name", ""),
            severity=pattern.get("severity", "MEDIUM"),
            match_method=match_method,
            confidence_score=confidence,
            description=pattern.get("description", ""),
            legal_reality=pattern.get("legal_reality", ""),
            recommended_action=pattern.get("recommended_action", ""),
            reporting_channels=pattern.get("reporting_channels", []),
            source_ref=pattern.get("source_ref", ""),
        )

    async def explain_for_query(self, query: str) -> Tuple[str, dict, int]:
        """
        Orchestrator-compatible entry point.
        Returns (output_text, metadata_dict, llm_calls_count).
        """
        result = await self.check_scam(query)

        if not result.matched:
            output_text = result.safe_fallback_message
            metadata = {
                "agent": "ScamDetectionAgent",
                "matched": False,
                "match_method": "none",
            }
        else:
            output_text = (
                f"🚨 **Scam Alert: {result.pattern_name}**\n\n"
                f"**Severity:** {result.severity}\n\n"
                f"**What this scam is:**\n{result.description}\n\n"
                f"**Legal Reality:**\n{result.legal_reality}\n\n"
                f"**What you should do:**\n{result.recommended_action}\n\n"
                f"**Report to:**\n" + "\n".join(f"• {r}" for r in result.reporting_channels) + "\n\n"
                f"*Reference: {result.source_ref}*\n"
                f"*Alert ID: {result.db_id} | Match: {result.match_method} | Confidence: {result.confidence_score:.0%}*"
            )
            metadata = {
                "agent": "ScamDetectionAgent",
                "matched": True,
                "db_id": result.db_id,
                "pattern_name": result.pattern_name,
                "severity": result.severity,
                "match_method": result.match_method,
                "confidence_score": result.confidence_score,
            }

        return output_text, metadata, 0  # No LLM calls — fully DB-grounded


# ── Global ScamDetectionAgent singleton ──────────────────────────────────────
_scam_agent_instance: Optional[ScamDetectionAgent] = None


def get_scam_agent(mongo_db=None, qdrant_client=None) -> ScamDetectionAgent:
    """Returns singleton instance of ScamDetectionAgent."""
    global _scam_agent_instance
    if _scam_agent_instance is None:
        _scam_agent_instance = ScamDetectionAgent(mongo_db=mongo_db, qdrant_client=qdrant_client)
    else:
        if mongo_db is not None and _scam_agent_instance.mongo_db is None:
            # Upgrade singleton with mongo_db reference once app is ready
            _scam_agent_instance.mongo_db = mongo_db
        if qdrant_client is not None and _scam_agent_instance.qdrant_client != qdrant_client:
            _scam_agent_instance.qdrant_client = qdrant_client
            _scam_agent_instance._ensure_qdrant_seeded()
    return _scam_agent_instance


def reset_scam_agent() -> None:
    """Reset singleton (used in tests to ensure clean state)."""
    global _scam_agent_instance
    _scam_agent_instance = None
