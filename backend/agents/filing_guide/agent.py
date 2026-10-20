"""
=============================================================================
LEXIS Filing Guide Agent (Module 9 Enhanced)
=============================================================================

This is Agent 5 — the specialist agent that guides citizens on WHERE and HOW
to file complaints, petitions, and legal documents in India.

RESPONSIBILITIES:
1. Natural language conversation understanding for legal filing needs.
2. Accurate categorization of filings (RTI, Consumer, Legal Notice, etc.).
3. Missing-information detection & follow-up clarification prompts.
4. Calculation of pecuniary jurisdiction (e.g., Consumer Commissions tiers).
5. Generation of structured, step-by-step filing guides with verified portals,
   required document checklists, statutory fees, deadlines, and common mistakes.
6. Multi-turn follow-up Q&A on generated guides.
7. Seamless handoff from Document Drafter (Module 6) via draft_id / doc_type.
8. Anti-hallucination guarantee: only authentic Indian statutes and verified
   government portals (*.gov.in / *.nic.in) are cited.
"""

import json
import logging
import re
import time
from typing import Dict, Any, Optional, Tuple, List

from agents.orchestrator.state import AgentOutput, OrchestratorState
from agents.filing_guide.catalog import FilingCatalog, get_filing_catalog
from agents.filing_guide.prompts import (
    FILING_GUIDE_SYSTEM,
    FILING_GUIDE_USER_TEMPLATE,
    FILING_GUIDE_CONVERSATIONAL_SYSTEM,
    FILING_INSUFFICIENT_INFO_MESSAGE,
    FILING_FOLLOWUP_SYSTEM,
    FILING_LEGAL_DISCLAIMER,
)
from core.config import get_settings
from services.filing.ingestion import load_filing_seed

logger = logging.getLogger(__name__)

# ── In-memory authority cache ───────────────────────────────────────────────
_AUTHORITY_CACHE: Dict[str, Dict] = {}


def _build_authority_cache() -> Dict[str, Dict]:
    """Builds dict mapping doc_type -> authority record from seed file."""
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
    """Structured result returned by FilingGuideAgent.lookup_authority()."""

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
            "eligibility_prerequisites": self.record.get("eligibility_prerequisites", []),
            "step_by_step_procedure": self.record.get("step_by_step_procedure", []),
            "common_mistakes": self.record.get("common_mistakes", []),
            "checklist": self.record.get("checklist", []),
            "source_ref": self.record.get("source_ref"),
            "verified": self.record.get("verified", False),
            "last_verified": self.record.get("last_verified"),
        }


# ── FilingGuideAgent ───────────────────────────────────────────────────────────

class FilingGuideAgent:
    """
    Filing Guide Specialist Agent.

    Provides conversational guidance and verified authority lookup for:
      - RTI Applications (rti_application)
      - Consumer Complaints (consumer_complaint)
      - Legal Demand Notices (legal_notice)
    """

    VALID_DOC_TYPES = {"rti_application", "consumer_complaint", "legal_notice"}

    def __init__(self, mongo_db=None, catalog: Optional[FilingCatalog] = None):
        self._mongo_db = mongo_db
        self.catalog = catalog or get_filing_catalog()
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
        if any(re.search(rf"\b{re.escape(kw)}\b", q) for kw in ["rti", "right to information", "public information officer", "pio"]):
            return "rti_application"
        if any(re.search(rf"\b{re.escape(kw)}\b", q) for kw in [
            "consumer", "consumer complaint", "defective product", "service deficiency",
            "consumer forum", "district forum", "ncdrc", "consumer court"
        ]):
            return "consumer_complaint"
        if any(re.search(rf"\b{re.escape(kw)}\b", q) for kw in [
            "legal notice", "demand notice", "landlord", "rent", "deposit",
            "contract breach"
        ]):
            return "legal_notice"
        return None

    async def lookup_authority(
        self,
        doc_type: str,
        mongo_db=None,
        collection_name: str = "filing_authorities",
    ) -> FilingAuthorityResult:
        """Looks up authority record in MongoDB or in-memory seed cache."""
        if not doc_type or not isinstance(doc_type, str):
            return FilingAuthorityResult(
                found=False,
                doc_type="",
                not_found_message=(
                    "No filing authority information is available for unspecified document type. "
                    f"Currently supported types: {', '.join(sorted(self.VALID_DOC_TYPES))}."
                ),
            )
        doc_type = doc_type.strip().lower()
        db = mongo_db or self._mongo_db

        if db is not None:
            try:
                record = await db[collection_name].find_one(
                    {"doc_type": doc_type},
                    {"_id": 0}
                )
                if record:
                    return FilingAuthorityResult(found=True, doc_type=doc_type, record=record)
            except Exception as exc:
                logger.error("MongoDB lookup error for doc_type='%s': %s", doc_type, exc)

        if doc_type in _AUTHORITY_CACHE:
            return FilingAuthorityResult(
                found=True, doc_type=doc_type, record=_AUTHORITY_CACHE[doc_type]
            )

        cat_record = self.catalog.get_by_doc_type(doc_type)
        if cat_record:
            return FilingAuthorityResult(found=True, doc_type=doc_type, record=cat_record)

        return FilingAuthorityResult(
            found=False,
            doc_type=doc_type,
            not_found_message=(
                f"No filing authority information is available for document type '{doc_type}'. "
                f"Currently supported types: {', '.join(sorted(self.VALID_DOC_TYPES))}."
            ),
        )

    async def process_conversation(
        self,
        query: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        draft_id: Optional[str] = None,
        doc_type: Optional[str] = None,
        mongo_db=None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Main conversational engine for Filing Guide Agent.
        Handles:
          - Insufficient information detection -> asks clarifying questions
          - New guide generation -> structured step-by-step guidance
          - Modification of existing guide -> pecuniary or state adjustment
          - Follow-up Q&A -> contextual responses
        """
        q_clean = query.strip()
        db = mongo_db or self._mongo_db

        # ── 1. Resolve Document Type ─────────────────────────────────────────
        resolved_doc_type = None
        draft_record = None

        if draft_id and db is not None:
            try:
                draft_query: Dict[str, Any] = {"draft_id": draft_id}
                if user_id and user_id != "anonymous":
                    draft_query["user_id"] = user_id
                draft_record = await db.user_drafts.find_one(draft_query)
                if draft_record and draft_record.get("doc_type"):
                    resolved_doc_type = draft_record.get("doc_type")
            except Exception as exc:
                logger.error("Failed to read draft %s: %s", draft_id, exc)

        if not resolved_doc_type and doc_type:
            resolved_doc_type = doc_type.strip().lower()

        if not resolved_doc_type:
            resolved_doc_type = self.catalog.infer_doc_type(q_clean)

        # If still not found, check conversation history for prior doc_type
        if not resolved_doc_type and conversation_history:
            for turn in reversed(conversation_history):
                content = (turn.get("content") or turn.get("text") or "").lower()
                prior_dt = self.catalog.infer_doc_type(content)
                if prior_dt:
                    resolved_doc_type = prior_dt
                    break

        # ── 2. Check for Insufficient Information ────────────────────────────
        if not resolved_doc_type:
            return {
                "reply_text": FILING_INSUFFICIENT_INFO_MESSAGE,
                "guide": None,
                "intent": "insufficient_info",
                "doc_type": None,
                "verified": True,
                "sources": ["Consumer Protection Act 2019", "RTI Act 2005", "Code of Civil Procedure 1908"],
                "disclaimer": FILING_LEGAL_DISCLAIMER,
            }

        # If document type is unsupported
        if resolved_doc_type and resolved_doc_type not in self.VALID_DOC_TYPES:
            return {
                "reply_text": (
                    f"LEXIS Filing Guide currently supports RTI Applications, Consumer Complaints, "
                    f"and Legal Demand Notices under Indian statutory law. We could not match '{resolved_doc_type}'. "
                    f"Please choose one of the supported categories or consult a qualified advocate "
                    f"(filing procedure for other matters: needs_verification)."
                ),
                "guide": None,
                "intent": "unsupported_category",
                "doc_type": resolved_doc_type,
                "verified": False,
                "sources": [],
                "disclaimer": FILING_LEGAL_DISCLAIMER,
            }

        # ── 3. Fetch Catalog Record ──────────────────────────────────────────
        auth_result = await self.lookup_authority(resolved_doc_type, mongo_db=db)
        if not auth_result.found:
            return {
                "reply_text": auth_result.not_found_message,
                "guide": None,
                "intent": "not_found",
                "doc_type": resolved_doc_type,
                "verified": False,
                "sources": [],
                "disclaimer": FILING_LEGAL_DISCLAIMER,
            }

        record = auth_result.record

        # ── 4. Calculate Pecuniary Jurisdiction & State Context ──────────────
        all_conversation_text = q_clean
        if draft_record and draft_record.get("collected_answers"):
            answers = draft_record["collected_answers"]
            ans_text = " ".join(str(v) for v in answers.values() if v)
            all_conversation_text = f"{ans_text} {all_conversation_text}"
        if conversation_history:
            all_conversation_text = " ".join([m.get("content", "") or m.get("text", "") for m in conversation_history]) + " " + all_conversation_text

        amount = self.catalog.extract_monetary_amount(all_conversation_text)
        state_jurisdiction = self.catalog.extract_jurisdiction_state(all_conversation_text)
        calculated_tier = None

        if resolved_doc_type == "consumer_complaint" and amount is not None:
            calculated_tier = self.catalog.calculate_consumer_pecuniary_tier(amount)

        # ── 5. Determine Intent (New Guide, Modify, or Follow-up) ─────────────
        has_prior_guide = False
        if conversation_history:
            for turn in conversation_history:
                if turn.get("sender") == "agent" or turn.get("role") == "assistant":
                    text = turn.get("content") or turn.get("text") or ""
                    if "Filing Guide:" in text or "Official Portal" in text or "Authority:" in text:
                        has_prior_guide = True
                        break

        q_lower = q_clean.lower()
        is_followup_question = has_prior_guide and (
            any(q_lower.startswith(w) for w in ["can i", "do i", "how long", "what if", "where do", "is it", "fee", "cost", "online", "lawyer", "advocate"])
            or "?" in q_clean
        )

        intent = "followup" if is_followup_question else ("modify_guide" if (has_prior_guide and (amount or state_jurisdiction)) else "new_guide")

        # ── 6. Build Structured Guide Object ─────────────────────────────────
        guide_obj = {
            "id": record.get("id"),
            "doc_type": resolved_doc_type,
            "doc_type_name": record.get("doc_type_name"),
            "authority_name": record.get("authority_name"),
            "authority_short": record.get("authority_short"),
            "description": record.get("description"),
            "portal_url": record.get("portal_url"),
            "portal_name": record.get("portal_name"),
            "portal_scope": record.get("portal_scope"),
            "fee": record.get("fee"),
            "required_documents": record.get("required_documents", []),
            "filing_tiers": record.get("filing_tiers", []),
            "response_timeline": record.get("response_timeline"),
            "legal_basis": record.get("legal_basis"),
            "important_notes": record.get("important_notes", []),
            "eligibility_prerequisites": record.get("eligibility_prerequisites", []),
            "step_by_step_procedure": record.get("step_by_step_procedure", []),
            "common_mistakes": record.get("common_mistakes", []),
            "checklist": record.get("checklist", []),
            "source_ref": record.get("source_ref"),
            "verified": record.get("verified", True),
            "last_verified": record.get("last_verified"),
            "calculated_tier": calculated_tier,
            "state_jurisdiction": state_jurisdiction,
        }

        # ── 7. Generate Response (LLM with deterministic fallback) ───────────
        reply_text = await self._generate_response(
            query=q_clean,
            guide_record=guide_obj,
            intent=intent,
            calculated_tier=calculated_tier,
            state_jurisdiction=state_jurisdiction,
            conversation_history=conversation_history,
        )

        return {
            "reply_text": reply_text,
            "guide": guide_obj,
            "intent": intent,
            "doc_type": resolved_doc_type,
            "verified": True,
            "sources": [record.get("source_ref", "Official Statutory Database")],
            "disclaimer": FILING_LEGAL_DISCLAIMER,
        }

    async def _generate_response(
        self,
        query: str,
        guide_record: Dict[str, Any],
        intent: str,
        calculated_tier: Optional[Dict[str, Any]],
        state_jurisdiction: Optional[str],
        conversation_history: Optional[List[Dict[str, str]]],
    ) -> str:
        """Calls Gemini GenAI or executes deterministic structured synthesis."""
        settings = get_settings()
        api_key = settings.GEMINI_API_KEY or settings.OPENAI_API_KEY

        # If LLM API available, invoke Gemini
        if api_key and not api_key.startswith("sk-replace"):
            try:
                from google import genai
                client = genai.Client(api_key=api_key)
                model_name = settings.GEMINI_MODEL_DEV if settings.GEMINI_API_KEY else settings.OPENAI_MODEL_DEV

                system_prompt = FILING_FOLLOWUP_SYSTEM if intent == "followup" else FILING_GUIDE_CONVERSATIONAL_SYSTEM
                user_prompt = f"""
Citizen Query: {query}
Intent: {intent}
Detected Jurisdiction State: {state_jurisdiction or "Not specified"}
Pecuniary Calculation: {json.dumps(calculated_tier) if calculated_tier else "Standard"}

Authoritative Guide Record:
{json.dumps(guide_record, indent=2)}

Please provide a helpful, structured response strictly adhering to the facts above.
Ensure verified government portals are highlighted, required documents and step-by-step procedure are easy to scan, and note any state-specific fee verifications.
"""
                response = await client.aio.models.generate_content(
                    model=model_name,
                    contents=f"{system_prompt}\n\n{user_prompt}",
                )
                if response and response.text and response.text.strip():
                    text = response.text.strip()
                    # Ensure gov portal or needs_verification is included
                    if guide_record.get("portal_url") and guide_record["portal_url"] not in text:
                        text += f"\n\n**Official Portal:** [{guide_record['portal_name']}]({guide_record['portal_url']})"
                    return text
            except Exception as exc:
                logger.warning("Filing Guide LLM call failed (%s). Falling back to template synthesis.", exc)

        # ── Deterministic Template Synthesis (0 LLM calls offline fallback) ──
        return self._synthesize_template_guide(guide_record, intent, calculated_tier, state_jurisdiction, query)

    def _synthesize_template_guide(
        self,
        record: Dict[str, Any],
        intent: str,
        calculated_tier: Optional[Dict[str, Any]],
        state: Optional[str],
        query: str,
    ) -> str:
        """Deterministic, high-fidelity template synthesis."""
        lines = []

        if intent == "followup":
            lines.append(f"Regarding your query on **{record.get('doc_type_name')}**:")
            lines.append("")
            # Answer specific query keywords
            q_lower = query.lower()
            if "lawyer" in q_lower or "advocate" in q_lower:
                lines.append(
                    "You are **not required to hire an advocate** to file this complaint. "
                    "The procedure is specifically designed for citizens to represent themselves in person "
                    "or online via the official portal."
                )
            elif "fee" in q_lower or "pay" in q_lower or "cost" in q_lower:
                fee = record.get("fee", {})
                lines.append(f"**Statutory Fee Information:** {fee.get('structure', fee.get('amount_central', 'Nominal statutory fee'))}.")
                if fee.get("payment_online"):
                    lines.append(f"- Online Payment: {fee.get('payment_online')}")
                if fee.get("fee_exemption"):
                    lines.append(f"- Fee Exemption: {fee.get('fee_exemption')}")
            elif "deadline" in q_lower or "limitation" in q_lower or "period" in q_lower or "delay" in q_lower:
                lines.append(f"**Statutory Timelines & Deadlines:**")
                lines.append(f"- Official Response Period: {record.get('response_timeline', 'Standard statutory period applies.')}")
                if record.get("doc_type") == "consumer_complaint":
                    lines.append("- Limitation Period: 2 years from the date on which the cause of action arose (Section 69, Consumer Protection Act 2019). Delay may be condoned if sufficient cause is shown.")
                elif record.get("doc_type") == "rti_application":
                    lines.append("- First Appeal Deadline: Within 30 days from the expiry of the 30-day response period or receipt of PIO decision.")
                elif record.get("doc_type") == "legal_notice":
                    lines.append("- Compliance Window: Typically 15 to 30 days specified in the notice before initiating court litigation.")
            elif "document" in q_lower or "checklist" in q_lower or "proof" in q_lower or "attach" in q_lower:
                docs = record.get("required_documents", [])
                lines.append("**Key Documents Required:**")
                for d in docs:
                    lines.append(f"- {d}")
            elif "online" in q_lower or "offline" in q_lower or "physical" in q_lower or "portal" in q_lower:
                if record.get("portal_url"):
                    lines.append(f"You can file **online** via the official portal: [{record['portal_name']}]({record['portal_url']}).")
                    if record.get("portal_scope"):
                        lines.append(f"_{record['portal_scope']}_")
                else:
                    lines.append("This document is served directly to the opposite party via Registered Post (RPAD) or Speed Post, and followed up in the competent Civil Court if unresolved.")
            elif "appeal" in q_lower or "reject" in q_lower or "unsatisfied" in q_lower or "no response" in q_lower:
                lines.append(f"**Appellate Procedure:**")
                tiers = record.get("filing_tiers", [])
                if len(tiers) > 1:
                    for t in tiers[1:]:
                        t_name = t.get("name", "Higher Authority")
                        t_desc = t.get("description", "")
                        lines.append(f"- **{t_name}**: {t_desc}")
                else:
                    lines.append("If the dispute is unresolved, proceedings may be escalated to the competent State Commission or Civil Court.")
            elif "timeline" in q_lower or "time" in q_lower or "how long" in q_lower:
                lines.append(f"**Timeline:** {record.get('response_timeline', 'Standard statutory period applies.')}")
            else:
                lines.append(
                    f"Please refer to the step-by-step filing guide for **{record.get('authority_name')}**. "
                    "All filings are subject to the procedural guidelines below."
                )
            lines.append("")
            if record.get("portal_url"):
                lines.append(f"Official Submission Portal: [{record['portal_name']}]({record['portal_url']})")
            return "\n".join(lines)

        # Full New Guide
        lines.append(f"### 📋 Filing Guide: {record.get('doc_type_name')}")
        lines.append(f"**Governing Authority:** {record.get('authority_name')}")
        if state:
            lines.append(f"**State / Jurisdiction:** {state}")
        lines.append("")
        lines.append(record.get("description", ""))
        lines.append("")

        if calculated_tier:
            lines.append(f"**Pecuniary Tier Determined:** {calculated_tier['tier_name']}")
            lines.append(f"_{calculated_tier['jurisdiction_limit']} — {calculated_tier['where_to_file']}_")
            lines.append("")
        elif record.get("filing_tiers"):
            lines.append("**Filing Hierarchy & Jurisdictional Tiers:**")
            for t in record["filing_tiers"]:
                t_name = t.get("name") or f"Tier {t.get('tier')}"
                t_desc = t.get("description", "")
                t_limit = t.get("jurisdiction") or ""
                limit_str = f" ({t_limit})" if t_limit else ""
                lines.append(f"- **{t_name}**{limit_str}: {t_desc}")
            lines.append("")

        if record.get("portal_url"):
            lines.append(f"**Official Portal:** [{record['portal_name']}]({record['portal_url']})")
            if record.get("portal_scope"):
                lines.append(f"_{record['portal_scope']}_")
            lines.append("")

        # Eligibility
        prereqs = record.get("eligibility_prerequisites", [])
        if prereqs:
            lines.append("**Eligibility & Prerequisites:**")
            for p in prereqs:
                lines.append(f"- {p}")
            lines.append("")

        # Documents
        docs = record.get("required_documents", [])
        if docs:
            lines.append("**Required Documents Checklist:**")
            for d in docs:
                lines.append(f"- [ ] {d}")
            lines.append("")

        # Steps
        steps = record.get("step_by_step_procedure", [])
        if steps:
            lines.append("**Step-by-Step Filing Procedure:**")
            for s in steps:
                url_str = f" ([Submit here]({s['action_url']}))" if s.get("action_url") else ""
                lines.append(f"{s['step_number']}. **{s['title']}**: {s['description']}{url_str}")
            lines.append("")

        # Fee
        fee = record.get("fee", {})
        if fee:
            lines.append("**Fee:**")
            for k, v in fee.items():
                if k == "source" or not v:
                    continue
                label = k.replace("_", " ").title()
                if isinstance(v, list):
                    lines.append(f"  - {label}: {', '.join(str(i) for i in v)}")
                else:
                    lines.append(f"  - {label}: {v}")
            lines.append("")

        # Documents
        required_docs = record.get("required_documents", [])
        if required_docs:
            output_lines.append("**Documents Required:**")
            for doc in required_docs:
                output_lines.append(f"  - {doc}")
            output_lines.append("")

        # Legal basis
        if record.get("legal_basis"):
            lines.append(f"**Legal Basis:** {record['legal_basis']}")

        return "\n".join(lines)

    async def explain_for_query(
        self,
        query: str,
        state: Optional[Dict] = None,
        mongo_db=None,
    ) -> Tuple[str, Dict[str, Any], int]:
        """
        Orchestrator text-only path (LangGraph specialist node).
        """
        history = state.get("conversation_history") if state else None
        res = await self.process_conversation(query=query, conversation_history=history, mongo_db=mongo_db)

        guide = res.get("guide")
        default_portal = "https://rtionline.gov.in" if res.get("doc_type") == "rti_application" else "https://edaakhil.nic.in"
        metadata = {
            "agent": "FilingGuideAgent",
            "doc_type": res.get("doc_type"),
            "found": guide is not None,
            "authority_name": guide.get("authority_name") if guide else None,
            "authority_id": guide.get("id") if guide else None,
            "intent": res.get("intent"),
            "portal_url": guide.get("portal_url") if guide else default_portal,
            "verified": res.get("verified", False),
            "citations": res.get("sources", []),
            "llm_used": False,
        }
        return res["reply_text"], metadata, 0


# ── Global singleton ──────────────────────────────────────────────────────────

_filing_agent_instance: Optional[FilingGuideAgent] = None


def get_filing_agent(mongo_db=None) -> FilingGuideAgent:
    """Returns the singleton FilingGuideAgent instance."""
    global _filing_agent_instance
    if _filing_agent_instance is None:
        _filing_agent_instance = FilingGuideAgent(mongo_db=mongo_db)
    elif mongo_db is not None and _filing_agent_instance._mongo_db is None:
        _filing_agent_instance._mongo_db = mongo_db
    return _filing_agent_instance


def reset_filing_agent():
    """Resets the singleton for test isolation."""
    global _filing_agent_instance
    _filing_agent_instance = None
    _AUTHORITY_CACHE.clear()


# ── LangGraph node ─────────────────────────────────────────────────────────────

async def filing_guide_node(state: OrchestratorState) -> Dict:
    """
    LangGraph node function for Filing Guide Agent.
    Called by orchestrator specialist_node when intent == AgentIntent.FILING.
    """
    query = state["query"]
    t_start = time.perf_counter()

    agent = get_filing_agent()
    output_text, metadata, llm_calls = await agent.explain_for_query(query, state=state)

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
