"""
=============================================================================
LEXIS Filing Guide Agent (Module 9)
=============================================================================

This is Agent 5 — the 5th and final originally-scoped feature agent.

WHAT THIS AGENT DOES:
---------------------
Given a document type (RTI application, consumer complaint, legal notice),
it looks up the correct government authority to file with, returning:
  - Authority name and tier structure
  - Verified portal URL
  - Fee schedule (from statute)
  - Required documents checklist
  - Legal basis

HOW THE HANDOFF FROM DOCUMENT DRAFTER (MODULE 6) WORKS:
--------------------------------------------------------
This is the KEY design principle of Module 9.

When the citizen finishes drafting an RTI application in Module 6:
  1. The `user_drafts` MongoDB document stores `doc_type = "rti_application"`.
  2. The frontend document preview card passes `doc_type` and `draft_id`
     as URL query parameters to `/filing-guide?doc_type=rti_application&draft_id=...`.
  3. FilingGuideAgent.lookup_authority("rti_application", db) is called directly.
  4. No re-typing. No re-classification. No risk of the citizen describing
     their situation differently and getting routed to the wrong authority.

WHY THIS IS MEANINGFULLY DIFFERENT FROM A DISCONNECTED TOOL:
-------------------------------------------------------------
A disconnected tool would require the citizen to:
  a) Leave the drafter page.
  b) Navigate to a separate "filing guide" tool.
  c) Describe their situation again (e.g., "I want to file an RTI application
     about my pension not being processed").
  d) The new tool re-classifies the natural language → maps to doc_type.

The handoff skips all of a–d. The `doc_type` is authoritative structured data
already in the system (the output of the drafter session), NOT re-interpreted
natural language. This eliminates:
  - Re-entry burden on the citizen
  - Classification error risk (natural language → wrong authority)
  - Context loss between tools

NO-HALLUCINATION ARCHITECTURE:
-------------------------------
Unlike the Rights Explainer (LLM + RAG) or Scam Detection (DB-grounded alerts),
the Filing Guide uses EXACT-MATCH DB lookup only:

  doc_type key -> MongoDB filing_authorities record -> return structured data

There is NO semantic search for authorities (a "close enough" authority is
still a WRONG authority for a real person filing a legal document).
There is NO LLM generation of authority details (inventing a portal URL
or fee amount is a real-world harm).

The LLM is used ONLY in the orchestrator text-only path to FORMAT the
structured record into a readable response — with explicit instructions
not to add any facts beyond what the record contains.
"""

import json
import logging
import time
from typing import Dict, Any, Optional, Tuple

from agents.orchestrator.state import AgentOutput, OrchestratorState
from agents.filing_guide.prompts import FILING_GUIDE_SYSTEM, FILING_GUIDE_USER_TEMPLATE
from services.filing.ingestion import load_filing_seed

logger = logging.getLogger(__name__)

# ── In-memory authority cache (loaded from seed file at startup) ───────────────
# Mirrors the approach used by ScamDetectionAgent._pattern_cache.
# The cache is the seed file data — MongoDB is the source of truth for
# production, but the cache allows offline unit testing with no DB connection.
_AUTHORITY_CACHE: Dict[str, Dict] = {}


def _build_authority_cache() -> Dict[str, Dict]:
    """
    Builds a dict mapping doc_type -> authority record from the seed file.
    This is used as a fallback when MongoDB is unavailable (tests/offline).
    """
    try:
        entries = load_filing_seed()
        cache = {entry["doc_type"]: entry for entry in entries if "doc_type" in entry}
        logger.info("Filing authority in-memory cache built with %d entries", len(cache))
        return cache
    except Exception as exc:
        logger.error("Failed to build filing authority cache: %s", exc)
        return {}


# ── FilingAuthorityResult dataclass ───────────────────────────────────────────

class FilingAuthorityResult:
    """
    Structured result returned by FilingGuideAgent.lookup_authority().
    Always contains a `found` flag. If found=True, all fields are populated.
    If found=False, only `doc_type` and `not_found_message` are set.
    """

    def __init__(
        self,
        found: bool,
        doc_type: str,
        record: Optional[Dict] = None,
        not_found_message: str = "",
    ):
        self.found = found
        self.doc_type = doc_type
        self.record = record or {}
        self.not_found_message = not_found_message

    def to_dict(self) -> Dict[str, Any]:
        """Serializable representation for API responses."""
        if not self.found:
            return {
                "found": False,
                "doc_type": self.doc_type,
                "message": self.not_found_message,
            }
        return {
            "found": True,
            "doc_type": self.doc_type,
            "id": self.record.get("id"),
            "doc_type_name": self.record.get("doc_type_name"),
            "authority_name": self.record.get("authority_name"),
            "authority_short": self.record.get("authority_short"),
            "description": self.record.get("description"),
            "portal_url": self.record.get("portal_url"),
            "portal_name": self.record.get("portal_name"),
            "portal_scope": self.record.get("portal_scope"),
            "fee": self.record.get("fee"),
            "required_documents": self.record.get("required_documents", []),
            "filing_tiers": self.record.get("filing_tiers", []),
            "response_timeline": self.record.get("response_timeline"),
            "legal_basis": self.record.get("legal_basis"),
            "important_notes": self.record.get("important_notes", []),
            "source_ref": self.record.get("source_ref"),
            "verified": self.record.get("verified", False),
            "last_verified": self.record.get("last_verified"),
        }


# ── FilingGuideAgent ───────────────────────────────────────────────────────────

class FilingGuideAgent:
    """
    Filing Guide Specialist Agent.

    Provides structured filing authority information for:
      - RTI Applications (rti_application)
      - Consumer Complaints (consumer_complaint)
      - Legal Demand Notices (legal_notice)

    Lookup chain (in order):
      1. MongoDB `filing_authorities` collection (production source of truth)
      2. In-memory cache from seed file (fallback for offline tests)
      3. Not found: returns a clear "not found" result (no fabrication)
    """

    # Known valid doc_types (for input validation)
    VALID_DOC_TYPES = {"rti_application", "consumer_complaint", "legal_notice"}

    def __init__(self, mongo_db=None):
        """
        Args:
            mongo_db: AsyncIOMotorDatabase instance (None for offline / test mode).
        """
        self._mongo_db = mongo_db
        # Build in-memory cache from seed file (used as offline fallback)
        if not _AUTHORITY_CACHE:
            _AUTHORITY_CACHE.update(_build_authority_cache())

    def _infer_doc_type_from_query(self, query: str) -> Optional[str]:
        """
        Infers document type from natural language query keywords.
        Used by the orchestrator text-only path.

        RTI and consumer complaint keywords are distinct; everything else
        defaults to legal_notice (the most general document type).
        """
        q = query.lower()
        if any(kw in q for kw in ["rti", "right to information", "public information officer", "pio"]):
            return "rti_application"
        if any(kw in q for kw in [
            "consumer", "consumer complaint", "defective product", "service deficiency",
            "consumer forum", "district forum", "ncdrc", "consumer court"
        ]):
            return "consumer_complaint"
        if any(kw in q for kw in [
            "legal notice", "demand notice", "landlord", "rent", "deposit",
            "notice", "contract breach"
        ]):
            return "legal_notice"
        return None

    async def lookup_authority(
        self,
        doc_type: str,
        mongo_db=None,
        collection_name: str = "filing_authorities",
    ) -> FilingAuthorityResult:
        """
        Core lookup: returns the filing authority record for the given doc_type.

        Tries MongoDB first (production), falls back to in-memory cache (tests).
        Returns FilingAuthorityResult(found=False) if not found — NEVER fabricates.

        HANDOFF NOTE:
        When called from the Document Drafter handoff, `doc_type` is the exact
        key from the user_drafts MongoDB record (e.g., "rti_application").
        This is authoritative structured data — not re-interpreted natural language.

        Args:
            doc_type: One of "rti_application", "consumer_complaint", "legal_notice"
            mongo_db: Optional database override (e.g., test injection)
            collection_name: MongoDB collection name

        Returns:
            FilingAuthorityResult
        """
        doc_type = doc_type.strip().lower()
        db = mongo_db or self._mongo_db

        # ── Attempt MongoDB lookup ────────────────────────────────────────────
        if db is not None:
            try:
                record = await db[collection_name].find_one(
                    {"doc_type": doc_type},
                    {"_id": 0}  # Exclude MongoDB internal _id from response
                )
                if record:
                    logger.info("Filing authority found in MongoDB for doc_type='%s'", doc_type)
                    return FilingAuthorityResult(found=True, doc_type=doc_type, record=record)
                else:
                    logger.warning(
                        "doc_type='%s' not found in MongoDB '%s'. Falling back to cache.",
                        doc_type, collection_name
                    )
            except Exception as exc:
                logger.error(
                    "MongoDB lookup failed for filing authority (doc_type='%s'): %s",
                    doc_type, exc
                )

        # ── Fallback: in-memory seed cache ───────────────────────────────────
        if doc_type in _AUTHORITY_CACHE:
            logger.info("Filing authority served from seed cache for doc_type='%s'", doc_type)
            return FilingAuthorityResult(
                found=True, doc_type=doc_type, record=_AUTHORITY_CACHE[doc_type]
            )

        # ── Not found ─────────────────────────────────────────────────────────
        logger.warning("No filing authority found for doc_type='%s'", doc_type)
        return FilingAuthorityResult(
            found=False,
            doc_type=doc_type,
            not_found_message=(
                f"No filing authority information is available for document type '{doc_type}'. "
                f"Currently supported types: {', '.join(sorted(self.VALID_DOC_TYPES))}. "
                "This data will be updated as more document types are added."
            )
        )

    async def explain_for_query(
        self,
        query: str,
        state: Optional[Dict] = None,
        mongo_db=None,
    ) -> Tuple[str, Dict[str, Any], int]:
        """
        Orchestrator text-only path.

        Infers doc_type from natural language, looks up the authority record,
        and formats a human-readable response.

        If an OpenAI API key is configured, uses the LLM to format the record
        (with strict no-hallucination prompt). Otherwise, uses template formatting.

        Returns: (output_text, metadata_dict, llm_calls_count)
        """
        # Infer doc_type from query keywords
        doc_type = self._infer_doc_type_from_query(query)

        if doc_type is None:
            return (
                (
                    "I can help you find the right authority to file your complaint with. "
                    "Please specify what type of document you want to file:\n\n"
                    "- **RTI Application** — to request information from a government body\n"
                    "- **Consumer Complaint** — for defective product or service deficiency\n"
                    "- **Legal Notice** — for landlord, deposit, or contract disputes\n\n"
                    "You can also go directly to the **Filing Guide** page to look up the "
                    "correct authority for your document type."
                ),
                {"agent": "FilingGuideAgent", "doc_type": None, "inferred": False},
                0,
            )

        db = mongo_db or self._mongo_db
        result = await self.lookup_authority(doc_type, mongo_db=db)

        if not result.found:
            return (
                result.not_found_message,
                {"agent": "FilingGuideAgent", "doc_type": doc_type, "found": False},
                0,
            )

        record = result.record

        # ── Template formatting (no LLM calls — consistent with no-hallucination principle) ─
        # The structured record is rendered into a readable markdown summary.
        output_lines = [
            f"**Filing Guide: {record.get('doc_type_name', doc_type)}**",
            "",
            f"**Authority:** {record.get('authority_short', record.get('authority_name', ''))}",
            "",
            f"{record.get('description', '')}",
            "",
        ]

        # Portal
        if record.get("portal_url"):
            output_lines.append(f"**Official Portal:** [{record['portal_name']}]({record['portal_url']})")
            if record.get("portal_scope"):
                output_lines.append(f"  _{record['portal_scope']}_")
            output_lines.append("")

        # Fee
        fee = record.get("fee", {})
        if fee:
            output_lines.append("**Fee:**")
            for k, v in fee.items():
                if k == "source" or not v:
                    continue
                if isinstance(v, list):
                    output_lines.append(f"  - {k}: {', '.join(str(i) for i in v)}")
                else:
                    output_lines.append(f"  - {k}: {v}")
            output_lines.append("")

        # Documents
        required_docs = record.get("required_documents", [])
        if required_docs:
            output_lines.append("**Documents Required:**")
            for doc in required_docs:
                output_lines.append(f"  - {doc}")
            output_lines.append("")

        # Legal basis
        if record.get("legal_basis"):
            output_lines.append(f"**Legal Basis:** {record['legal_basis']}")

        output_text = "\n".join(output_lines)

        metadata = {
            "agent": "FilingGuideAgent",
            "doc_type": doc_type,
            "found": True,
            "authority_id": record.get("id"),
            "authority_name": record.get("authority_name"),
            "portal_url": record.get("portal_url"),
            "verified": record.get("verified", False),
            "llm_used": False,
        }

        logger.info(
            "FilingGuideAgent resolved doc_type='%s' to authority='%s'",
            doc_type, record.get("authority_short")
        )
        return output_text, metadata, 0  # 0 LLM calls — template formatting


# ── Singleton factory ──────────────────────────────────────────────────────────

_filing_agent_instance: Optional[FilingGuideAgent] = None


def get_filing_agent(mongo_db=None) -> FilingGuideAgent:
    """Returns the singleton FilingGuideAgent instance."""
    global _filing_agent_instance
    if _filing_agent_instance is None:
        _filing_agent_instance = FilingGuideAgent(mongo_db=mongo_db)
    elif mongo_db is not None and _filing_agent_instance._mongo_db is None:
        # Inject DB if it was not available at construction time
        _filing_agent_instance._mongo_db = mongo_db
    return _filing_agent_instance


def reset_filing_agent():
    """Resets the singleton — used in unit tests for clean state."""
    global _filing_agent_instance
    _filing_agent_instance = None
    _AUTHORITY_CACHE.clear()


# ── LangGraph node ─────────────────────────────────────────────────────────────

async def filing_guide_node(state: OrchestratorState) -> Dict:
    """
    LangGraph node function for Filing Guide Agent.
    Called by orchestrator specialist_node when intent == AgentIntent.FILING.

    HANDOFF FROM DOCUMENT DRAFTER:
    --------------------------------
    When the user arrived here via the Document Drafter completion screen,
    the state["query"] will contain the natural language query.
    The filing agent infers doc_type from the query keywords.

    For the direct REST API handoff (POST /api/v1/filing/lookup?doc_type=...),
    the frontend passes the doc_type as a structured parameter — bypassing
    this node entirely and calling the REST endpoint directly.
    """
    query = state["query"]
    t_start = time.perf_counter()

    agent = get_filing_agent()
    output_text, metadata, llm_calls = await agent.explain_for_query(query)

    elapsed_ms = int((time.perf_counter() - t_start) * 1000)
    metadata["latency_ms"] = elapsed_ms

    output_record: AgentOutput = {
        "intent": "filing",
        "status": "ok",
        "output": output_text,
        "metadata": metadata,
    }

    return {
        "scratchpad": [output_record],
        "llm_calls_used": llm_calls,
    }
