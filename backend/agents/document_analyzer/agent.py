"""
=============================================================================
LEXIS — Document Analyzer Agent (Module 7)
=============================================================================

WHAT THIS AGENT DOES
---------------------
The Document Analyzer Agent receives an uploaded legal document (PDF or image),
extracts text via OCR, determines the document type (Aadhaar, PAN, Rental Deed,
Court Order, Contract), and executes specialized intelligence extraction:
  1. Identity Documents (Aadhaar/PAN):
     - Zero-shot extraction of Name, ID No, Address, DOB, Gender.
     - Inspects prior information in MongoDB profile and Redis session memory.
     - Performs intelligent non-destructive merge and conflict detection.
     - Persists verified identity to MongoDB user profile and Redis session memory.
  2. Court Orders / Judgments:
     - Extracts Court, Case No, Parties, Bench, Operative Verdict.
     - Translates verdict into simple everyday words in both English & Hindi.
     - Extracts actionable directions.
  3. Rental Agreements:
     - Extracts Landlord, Tenant, Rented Property, Monthly Rent, Security Deposit.
     - Generates plain-language rights and commitment summary.
     - Evaluates clauses for one-sided risks.
  4. General Contracts:
     - Splits into individual clauses, scores GREEN/YELLOW/RED, rewrites flagged clauses.
"""

import asyncio
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from agents.orchestrator.state import OrchestratorState
from services.analysis.clause_classifier import (
    split_into_clauses,
    ClauseResult,
    RiskLevel,
    get_clause_classifier,
)
from services.analysis.rewriter import rewrite_clause
from services.ocr.extractor import extract_text, OCRExtractionError
from services.analysis.doc_intelligence import (
    classify_document_type,
    extract_identity_info,
    extract_rental_agreement_info,
    extract_court_order_info,
    extract_general_legal_info,
)

logger = logging.getLogger(__name__)


# ── Result dataclass for a full document analysis ─────────────────────────────

class AnalysisResult:
    """
    The complete output of a document analysis run.

    Attributes:
        file_id                    — UUID of stored file (for retrieval / audit)
        original_name              — Original filename
        status                     — "ok" | "partial" | "error"
        error_message              — Set if status is "error"
        document_category          — "identity_document" | "court_document" | "agreement_contract" | "general_legal"
        document_type              — "aadhaar_card" | "pan_card" | "rental_agreement" | "court_judgment" | "contract" | "other"
        document_title             — Human-readable document title
        extracted_info             — Structured key-value details extracted from document
        plain_language_summary     — Simple explanation for citizens (English)
        plain_language_summary_hi  — Simple explanation for citizens (Hindi)
        key_actions                — Actionable checklist or operative directions
        memory_saved               — Whether details were saved to profile/memory
        prior_info_found           — Whether prior identity info already existed
        memory_action              — "created" | "merged" | "updated" | "conflict_detected" | "none"
        prior_info                 — Snapshot of prior identity before save
        changed_fields             — List of fields added or updated
        conflicts                  — List of field mismatches detected
        total_clauses              — Total clauses analyzed
        green_count                — Number of GREEN (safe) clauses
        yellow_count               — Number of YELLOW (caution) clauses
        red_count                  — Number of RED (high risk) clauses
        clauses                    — List of ClauseResult objects
    """

    def __init__(
        self,
        clauses: list[ClauseResult],
        file_id: str = "",
        original_name: str = "",
        status: str = "ok",
        error_message: str = "",
        document_category: str = "agreement_contract",
        document_type: str = "contract",
        document_title: str = "Legal Document",
        extracted_info: Optional[Dict[str, Any]] = None,
        plain_language_summary: str = "",
        plain_language_summary_hi: str = "",
        key_actions: Optional[List[str]] = None,
        memory_saved: bool = False,
        prior_info_found: bool = False,
        memory_action: str = "none",
        prior_info: Optional[Dict[str, Any]] = None,
        changed_fields: Optional[List[str]] = None,
        conflicts: Optional[List[Dict[str, Any]]] = None,
    ):
        self.clauses = clauses
        self.file_id = file_id
        self.original_name = original_name
        self.status = status
        self.error_message = error_message
        self.document_category = document_category
        self.document_type = document_type
        self.document_title = document_title
        self.extracted_info = extracted_info or {}
        self.plain_language_summary = plain_language_summary
        self.plain_language_summary_hi = plain_language_summary_hi
        self.key_actions = key_actions or []
        self.memory_saved = memory_saved
        self.prior_info_found = prior_info_found
        self.memory_action = memory_action
        self.prior_info = prior_info
        self.changed_fields = changed_fields or []
        self.conflicts = conflicts or []

        self.total_clauses = len(clauses)
        self.green_count = sum(1 for c in clauses if c.risk_level == RiskLevel.GREEN)
        self.yellow_count = sum(1 for c in clauses if c.risk_level == RiskLevel.YELLOW)
        self.red_count = sum(1 for c in clauses if c.risk_level == RiskLevel.RED)

    def to_dict(self) -> dict:
        """Serializes the result to a plain dict for JSON responses."""
        return {
            "file_id": self.file_id,
            "original_name": self.original_name,
            "status": self.status,
            "error_message": self.error_message,
            "document_category": self.document_category,
            "document_type": self.document_type,
            "document_title": self.document_title,
            "extracted_info": self.extracted_info,
            "plain_language_summary": self.plain_language_summary,
            "plain_language_summary_hi": self.plain_language_summary_hi,
            "key_actions": self.key_actions,
            "memory_saved": self.memory_saved,
            "prior_info_found": self.prior_info_found,
            "memory_action": self.memory_action,
            "prior_info": self.prior_info,
            "changed_fields": self.changed_fields,
            "conflicts": self.conflicts,
            "total_clauses": self.total_clauses,
            "green_count": self.green_count,
            "yellow_count": self.yellow_count,
            "red_count": self.red_count,
            "clauses": [
                {
                    "text": c.text,
                    "risk_level": c.risk_level.value,
                    "rule_hit": c.rule_hit,
                    "explanation": c.explanation,
                    "confidence": c.confidence,
                    "rewrite": c.rewrite or "",
                }
                for c in self.clauses
            ],
        }


# ── Prior Information Inspection & Memory Synchronization ─────────────────────

async def inspect_and_sync_identity(
    user_id: str,
    session_id: Optional[str],
    extracted: Dict[str, Any],
    db: Any = None,
    redis: Any = None,
) -> Dict[str, Any]:
    """
    Inspects existing identity information in MongoDB user profile and Redis session
    context before writing. Performs an intelligent non-destructive merge and
    detects conflicts/mismatches.
    """
    prior_info: Dict[str, Any] = {}
    prior_info_found = False
    conflicts: List[Dict[str, Any]] = []
    changed_fields: List[str] = []

    # 1. Inspect prior MongoDB profile
    is_real_user = db is not None and user_id and not user_id.startswith("anon:")
    if is_real_user:
        try:
            from bson import ObjectId
            if ObjectId.is_valid(user_id):
                user_doc = await db["users"].find_one({"_id": ObjectId(user_id)})
                if user_doc and user_doc.get("profile"):
                    prof = user_doc["profile"]
                    if isinstance(prof, dict) and (prof.get("full_name") or prof.get("address") or prof.get("id_number_masked")):
                        prior_info_found = True
                        prior_info = {
                            "name": prof.get("full_name"),
                            "address": prof.get("address"),
                            "city": prof.get("city"),
                            "dob": prof.get("date_of_birth"),
                            "id_type": prof.get("id_type"),
                            "id_number": prof.get("id_number_masked"),
                        }
        except Exception as exc:
            logger.warning("Error inspecting prior MongoDB profile: %s", exc)

    # 2. Inspect prior Redis context if not found in MongoDB
    if session_id and not prior_info_found and redis is not None:
        try:
            from core.memory.session_store import get_session_store
            store = get_session_store(redis_client=redis)
            ctx = await store.get_context(session_id)
            if ctx and ctx.get("citizen_identity"):
                prior_info_found = True
                prior_info = ctx["citizen_identity"]
        except Exception as exc:
            logger.warning("Error inspecting prior Redis context: %s", exc)

    # 3. Detect conflicts & merge non-destructively
    merged = dict(extracted)
    action = "created"

    if prior_info_found:
        action = "merged"
        prior_name = (prior_info.get("name") or "").strip()
        new_name = (extracted.get("name") or "").strip()
        if prior_name and new_name and prior_name.lower() != new_name.lower():
            conflicts.append({
                "field": "name",
                "prior": prior_name,
                "extracted": new_name,
                "description": f"Name on document ('{new_name}') differs from existing profile name ('{prior_name}').",
            })

        prior_dob = (prior_info.get("dob") or "").strip()
        new_dob = (extracted.get("dob_iso") or extracted.get("dob") or "").strip()
        if prior_dob and new_dob and prior_dob != new_dob:
            conflicts.append({
                "field": "date_of_birth",
                "prior": prior_dob,
                "extracted": new_dob,
                "description": f"Date of birth on document ('{new_dob}') differs from existing profile ('{prior_dob}').",
            })

        # Non-destructive address preservation:
        # If new document lacks an address (e.g., PAN card), preserve existing address from prior record
        if not extracted.get("address") and prior_info.get("address"):
            merged["address"] = prior_info["address"]
        if not extracted.get("city") and prior_info.get("city"):
            merged["city"] = prior_info["city"]

        # Track changed fields
        for k, v in merged.items():
            if v and v != prior_info.get(k):
                changed_fields.append(k)

        if conflicts:
            action = "conflict_detected"
        elif changed_fields:
            action = "updated" if set(changed_fields) == set(merged.keys()) else "merged"

    # 4. Synchronize to Redis SessionStore
    if session_id and redis is not None:
        try:
            from core.memory.session_store import get_session_store
            store = get_session_store(redis_client=redis)
            updates = {
                "citizen_identity": merged,
                "applicant_name": merged.get("name") or "",
                "sender_name": merged.get("name") or "",
                "complainant_name": merged.get("name") or "",
                "applicant_address": merged.get("address") or "",
                "sender_address": merged.get("address") or "",
                "complainant_address": merged.get("address") or "",
                "city": merged.get("city") or "",
                "forum_city": merged.get("city") or "",
            }
            await store.set_context(session_id, updates)
        except Exception as exc:
            logger.warning("Error saving to Redis SessionStore: %s", exc)

    # 5. Synchronize to MongoDB User Profile
    if is_real_user:
        try:
            from bson import ObjectId
            if ObjectId.is_valid(user_id):
                update_dict = {
                    "profile.full_name": merged.get("name"),
                    "profile.address": merged.get("address"),
                    "profile.city": merged.get("city"),
                    "profile.id_verified": True,
                    "profile.id_type": merged.get("id_type"),
                    "profile.id_number_masked": merged.get("id_number"),
                    "profile.updated_at": datetime.now(timezone.utc).isoformat(),
                }
                dob_iso = merged.get("dob_iso")
                if dob_iso:
                    update_dict["profile.date_of_birth"] = dob_iso
                await db["users"].update_one({"_id": ObjectId(user_id)}, {"$set": update_dict})
        except Exception as exc:
            logger.warning("Error updating MongoDB users profile: %s", exc)

    return {
        "memory_saved": True,
        "prior_info_found": prior_info_found,
        "memory_action": action,
        "prior_info": prior_info if prior_info_found else None,
        "changed_fields": changed_fields,
        "conflicts": conflicts,
        "merged_identity": merged,
        "merged_record": merged,
    }


# ── Main agent class ──────────────────────────────────────────────────────────

class DocumentAnalyzerAgent:
    """
    Orchestrates the intelligent multi-document analysis pipeline.
    """

    async def analyze_document(
        self,
        file_bytes: bytes,
        content_type: str,
        original_name: str,
        user_id: str,
        db=None,
        session_id: Optional[str] = None,
        redis=None,
        openai_api_key: str = "",
        model: str = "gpt-4o-mini",
    ) -> AnalysisResult:
        """
        Main analysis pipeline:
          1. OCR Text extraction (PyMuPDF / Tesseract / Gemini Multimodal fallback)
          2. Document categorization (Identity / Court / Rental / Contract)
          3. Specialized entity extraction & prior memory synchronization
          4. Clause risk review (for agreements & contracts)
          5. Secure per-user file storage
          6. Return enriched AnalysisResult
        """
        # ── Step 1: OCR text extraction ──────────────────────────────────────
        try:
            raw_text = await asyncio.to_thread(extract_text, file_bytes, content_type)
            logger.info(
                "OCR extraction complete",
                extra={"chars": len(raw_text), "content_type": content_type},
            )
        except OCRExtractionError as exc:
            logger.error("OCR extraction failed: %s", exc)
            return AnalysisResult(
                clauses=[],
                file_id="",
                original_name=original_name,
                status="error",
                error_message=f"Could not extract text from this file: {exc}",
            )

        if not raw_text.strip():
            return AnalysisResult(
                clauses=[],
                file_id="",
                original_name=original_name,
                status="error",
                error_message=(
                    "No readable text was found in this document. "
                    "Ensure the image or PDF has legible printed text."
                ),
            )

        # ── Step 2: Document Categorization ──────────────────────────────────
        category, doc_type, doc_title = await classify_document_type(
            raw_text, api_key=openai_api_key, model=model
        )
        logger.info(
            "Document categorized as category=%s doc_type=%s title=%s",
            category, doc_type, doc_title,
        )

        extracted_info: Dict[str, Any] = {}
        plain_summary = ""
        plain_summary_hi = ""
        key_actions: List[str] = []
        memory_meta = {
            "memory_saved": False,
            "prior_info_found": False,
            "memory_action": "none",
            "prior_info": None,
            "changed_fields": [],
            "conflicts": [],
        }
        clause_results: List[ClauseResult] = []

        # ── Step 3: Specialized Intelligence & Memory Sync ───────────────────
        if category == "identity_document":
            extracted_info = await extract_identity_info(
                raw_text, doc_type=doc_type, api_key=openai_api_key, model=model
            )
            # Prior information inspection & memory sync
            sync_res = await inspect_and_sync_identity(
                user_id=user_id,
                session_id=session_id,
                extracted=extracted_info,
                db=db,
                redis=redis,
            )
            memory_meta.update(sync_res)
            # Use merged identity for response
            if sync_res.get("merged_identity"):
                extracted_info = sync_res["merged_identity"]

            id_label = extracted_info.get("id_type") or "Identity Document"
            name_label = extracted_info.get("name") or "Citizen"
            plain_summary = (
                f"Verified Indian National Identity Card ({id_label}). "
                f"Details for {name_label} have been synchronized to your session memory and profile. "
                "The Document Drafter will automatically use these details."
            )
            plain_summary_hi = (
                f"सत्यापित भारतीय पहचान दस्तावेज ({id_label})। "
                f"{name_label} का विवरण आपकी प्रोफाइल और ड्राफ्टर मेमोरी में सुरक्षित कर दिया गया है।"
            )

        elif category == "court_document":
            extracted_info = await extract_court_order_info(
                raw_text, api_key=openai_api_key, model=model
            )
            plain_summary = extracted_info.get("plain_language_summary", "")
            plain_summary_hi = extracted_info.get("plain_language_summary_hi", "")
            key_actions = extracted_info.get("key_actions", [])

        elif doc_type == "rental_agreement":
            extracted_info = await extract_rental_agreement_info(
                raw_text, api_key=openai_api_key, model=model
            )
            plain_summary = extracted_info.get("plain_language_summary", "")
            plain_summary_hi = extracted_info.get("plain_language_summary_hi", "")

        else:
            extracted_info = await extract_general_legal_info(
                raw_text, api_key=openai_api_key, model=model
            )
            plain_summary = extracted_info.get("plain_language_summary", "")
            plain_summary_hi = extracted_info.get("plain_language_summary_hi", "")
            key_actions = extracted_info.get("key_deadlines_or_actions", [])

        # ── Step 4: Clause Analysis (For Agreements & Contracts) ─────────────
        # Only analyze contract clauses for agreements or general legal documents
        if category in ("agreement_contract", "general_legal"):
            clauses_text = split_into_clauses(raw_text)
            if not clauses_text:
                clauses_text = [raw_text]

            classifier = get_clause_classifier()
            clause_results = await classifier.classify_all_async(
                clauses_text,
                openai_api_key=openai_api_key,
                model=model,
            )

            # Rewrite YELLOW/RED clauses (skip if already generated during batch classification)
            for result in clause_results:
                if result.risk_level in (RiskLevel.YELLOW, RiskLevel.RED) and not result.rewrite:
                    result.rewrite = await rewrite_clause(
                        result,
                        openai_api_key=openai_api_key,
                        model=model,
                    )

        # ── Step 5: Store file (access-controlled, per-user) ──────────────────
        file_id = ""
        try:
            from services.storage.secure_storage import get_storage_service
            storage = get_storage_service()
            meta = await storage.store_file(
                db=db,
                user_id=user_id,
                content_bytes=file_bytes,
                original_name=original_name,
                content_type=content_type,
                collection="user_uploads",
            )
            file_id = meta.file_id
        except Exception as store_exc:
            logger.error("File storage failed (non-fatal): %s", store_exc)

        logger.info(
            "Document analysis complete: category=%s total_clauses=%d file_id=%s",
            category, len(clause_results), file_id,
        )

        return AnalysisResult(
            clauses=clause_results,
            file_id=file_id,
            original_name=original_name,
            status="ok",
            document_category=category,
            document_type=doc_type,
            document_title=doc_title,
            extracted_info=extracted_info,
            plain_language_summary=plain_summary,
            plain_language_summary_hi=plain_summary_hi,
            key_actions=key_actions,
            memory_saved=memory_meta.get("memory_saved", False),
            prior_info_found=memory_meta.get("prior_info_found", False),
            memory_action=memory_meta.get("memory_action", "none"),
            prior_info=memory_meta.get("prior_info"),
            changed_fields=memory_meta.get("changed_fields", []),
            conflicts=memory_meta.get("conflicts", []),
        )

    async def explain_for_query(self, query: str) -> tuple[str, dict, int]:
        """
        Text-only path called by the orchestrator when AgentIntent.ANALYZE is detected
        but no file is available.
        """
        response = (
            "📄 **Document Analyzer Ready**\n\n"
            "I can analyze any legal document or credential for you:\n"
            "- **Identity Cards (Aadhaar / PAN):** Automatically extract your name and address, "
            "save them to memory, and pre-fill document drafting forms.\n"
            "- **Court Judgments & Orders:** Extract verdicts (e.g. Bail Granted/Dismissed) "
            "and explain them in simple everyday words (Hindi + English).\n"
            "- **Rental & Business Agreements:** Identify key commitments, deposits, and color-code risky clauses (🟢🟡🔴).\n\n"
            "To get started, please go to the **Document Analyzer** page and upload your file (PDF, JPEG, or PNG)."
        )
        metadata = {
            "agent": "DocumentAnalyzerAgent",
            "model": "rule_based + doc_intelligence",
            "note": "No file uploaded — returned upload prompt",
        }
        return response, metadata, 0


# ── LangGraph node entry point ────────────────────────────────────────────────

async def analyzer_agent_node(state: OrchestratorState) -> dict:
    agent = get_analyzer_agent()
    query = state.get("query", "")
    text, metadata, llm_calls = await agent.explain_for_query(query)
    return {"output": text, "metadata": metadata, "llm_calls": llm_calls}


# ── Singleton factory ─────────────────────────────────────────────────────────

_analyzer_agent: Optional[DocumentAnalyzerAgent] = None

def get_analyzer_agent() -> DocumentAnalyzerAgent:
    global _analyzer_agent
    if _analyzer_agent is None:
        _analyzer_agent = DocumentAnalyzerAgent()
    return _analyzer_agent
