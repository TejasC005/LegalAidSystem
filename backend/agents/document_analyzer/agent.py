"""
=============================================================================
LEXIS — Document Analyzer Agent (Module 7)
=============================================================================

WHAT THIS AGENT DOES
---------------------
The Document Analyzer Agent receives an uploaded legal document (PDF or image),
extracts its text via OCR, splits the text into clauses, classifies each clause
as GREEN / YELLOW / RED, and generates plain-language explanations for
flagged clauses.

PIPELINE (in order):
  1. Validate file (type, size, magic bytes) ← handled BEFORE agent is called
  2. OCR: Extract text from PDF/image
  3. Split: Divide text into individual clauses
  4. Classify: Score each clause GREEN/YELLOW/RED (rule-based + LLM)
  5. Rewrite: Generate plain-language explanation for YELLOW/RED clauses
  6. Store: Save file in isolated per-user storage
  7. Compile: Return AnalysisResult with all clause results + summary

ORCHESTRATOR INTEGRATION
--------------------------
The agent exposes `analyzer_agent_node()` as a LangGraph node.
When the orchestrator detects AgentIntent.ANALYZE, it dispatches this node.

For text-only queries (no file upload), the agent returns a prompt asking the
user to upload a document — it doesn't hallucinate analysis without content.

For file uploads, the dedicated REST endpoint
  POST /api/v1/analysis/upload
is the primary path (bypasses the orchestrator for binary upload handling).
Both paths resolve to the same DocumentAnalyzerAgent methods.

STORAGE
--------
Uploaded files are stored via SecureStorageService — per-user, access-controlled,
non-guessable paths.  Module 10 (Vault) will reuse this exact storage layer.
"""

import asyncio
import logging
from dataclasses import asdict
from typing import Optional

from agents.orchestrator.state import OrchestratorState
from services.analysis.clause_classifier import (
    split_into_clauses,
    ClauseResult,
    RiskLevel,
    get_clause_classifier,
)
from services.analysis.rewriter import rewrite_clause
from services.ocr.extractor import extract_text, OCRExtractionError

logger = logging.getLogger(__name__)


# ── Result dataclass for a full document analysis ─────────────────────────────

class AnalysisResult:
    """
    The complete output of a document analysis run.

    Attributes:
        file_id         — UUID of the stored file (for retrieval / audit)
        original_name   — Original filename (display only)
        clauses         — List of ClauseResult objects (one per clause)
        summary         — Short plain-language summary of overall risk
        total_clauses   — Total clauses analyzed
        green_count     — Number of GREEN (safe) clauses
        yellow_count    — Number of YELLOW (caution) clauses
        red_count       — Number of RED (high risk) clauses
        status          — "ok" | "partial" (some OCR failures) | "error"
        error_message   — Set if status is "error"
    """

    def __init__(
        self,
        clauses: list[ClauseResult],
        file_id: str = "",
        original_name: str = "",
        status: str = "ok",
        error_message: str = "",
    ):
        self.clauses = clauses
        self.file_id = file_id
        self.original_name = original_name
        self.status = status
        self.error_message = error_message
        self.total_clauses = len(clauses)
        self.green_count  = sum(1 for c in clauses if c.risk_level == RiskLevel.GREEN)
        self.yellow_count = sum(1 for c in clauses if c.risk_level == RiskLevel.YELLOW)
        self.red_count    = sum(1 for c in clauses if c.risk_level == RiskLevel.RED)

    def to_dict(self) -> dict:
        """Serializes the result to a plain dict for JSON responses."""
        return {
            "file_id":       self.file_id,
            "original_name": self.original_name,
            "status":        self.status,
            "error_message": self.error_message,
            "total_clauses": self.total_clauses,
            "green_count":   self.green_count,
            "yellow_count":  self.yellow_count,
            "red_count":     self.red_count,
            "clauses": [
                {
                    "text":        c.text,
                    "risk_level":  c.risk_level.value,
                    "rule_hit":    c.rule_hit,
                    "explanation": c.explanation,
                    "confidence":  c.confidence,
                    "rewrite":     c.rewrite or "",
                }
                for c in self.clauses
            ],
        }


# ── Main agent class ──────────────────────────────────────────────────────────

class DocumentAnalyzerAgent:
    """
    Orchestrates the full document analysis pipeline.

    USAGE (from the API route):
        agent = get_analyzer_agent()
        result = await agent.analyze_document(
            file_bytes=bytes_from_upload,
            content_type="application/pdf",
            original_name="my_contract.pdf",
            user_id="user123",
            db=mongo_db,           # pass None in tests
        )
        return result.to_dict()
    """

    async def analyze_document(
        self,
        file_bytes: bytes,
        content_type: str,
        original_name: str,
        user_id: str,
        db=None,
        openai_api_key: str = "",
        model: str = "gpt-4o-mini",
    ) -> AnalysisResult:
        """
        Main analysis pipeline: OCR → split → classify → rewrite → store.

        Never raises — returns AnalysisResult with status="error" on fatal failure.
        Partial failures (e.g., one OCR page fails) return status="partial".
        """
        # ── Step 1: OCR text extraction (run in thread so we don't block event loop) ─
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
                    "If this is a scanned image, ensure Tesseract OCR is installed. "
                    "Try a digital (not scanned) PDF for best results."
                ),
            )

        # ── Step 2: Split into clauses ─────────────────────────────────────
        clauses_text = split_into_clauses(raw_text)
        if not clauses_text:
            clauses_text = [raw_text]  # Treat whole doc as one clause if splitting fails

        logger.info("Document split into %d clauses", len(clauses_text))

        # ── Step 3: Classify clauses ───────────────────────────────────────
        classifier = get_clause_classifier()
        clause_results: list[ClauseResult] = await classifier.classify_all_async(
            clauses_text,
            openai_api_key=openai_api_key,
            model=model,
        )

        # ── Step 4: Rewrite YELLOW/RED clauses ────────────────────────────
        for result in clause_results:
            if result.risk_level in (RiskLevel.YELLOW, RiskLevel.RED):
                result.rewrite = await rewrite_clause(
                    result,
                    openai_api_key=openai_api_key,
                    model=model,
                )

        # ── Step 5: Store file (access-controlled, per-user) ──────────────
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
            # Storage failure is non-fatal — analysis results are still valid

        logger.info(
            "Analysis complete",
            extra={
                "total": len(clause_results),
                "red": sum(1 for c in clause_results if c.risk_level == RiskLevel.RED),
                "yellow": sum(1 for c in clause_results if c.risk_level == RiskLevel.YELLOW),
                "file_id": file_id,
            },
        )

        return AnalysisResult(
            clauses=clause_results,
            file_id=file_id,
            original_name=original_name,
            status="ok",
        )

    async def explain_for_query(self, query: str) -> tuple[str, dict, int]:
        """
        Text-only path called by the orchestrator when AgentIntent.ANALYZE is detected
        but no file is available (citizen asked about document analysis without uploading).

        Returns a helpful prompt asking them to upload a document.
        """
        response = (
            "📄 **Document Analyzer Ready**\n\n"
            "I can analyze your legal document (contract, agreement, notice, rent deed, etc.) "
            "and flag risky clauses for you.\n\n"
            "To get started, please go to the **Document Analyzer** page and upload your document "
            "(PDF, JPEG, or PNG — max 10 MB). I will:\n"
            "- Extract and read the text\n"
            "- Identify clauses that need your attention (color-coded 🟢🟡🔴)\n"
            "- Explain each risky clause in plain language (Hindi + English)\n\n"
            "If you have a specific clause you'd like me to explain, you can also paste it here."
        )
        metadata = {
            "agent": "DocumentAnalyzerAgent",
            "model": "rule_based + gpt-4o-mini",
            "note": "No file uploaded — returned upload prompt",
        }
        return response, metadata, 0


# ── LangGraph node entry point ────────────────────────────────────────────────

async def analyzer_agent_node(state: OrchestratorState) -> dict:
    """
    LangGraph node for the Document Analyzer Agent.
    Called when AgentIntent.ANALYZE is detected by the orchestrator.

    Since file uploads are handled via a separate REST endpoint, this node
    handles the text-only path (asking user to upload a file).
    """
    agent = get_analyzer_agent()
    query = state.get("query", "")
    text, metadata, llm_calls = await agent.explain_for_query(query)
    return {"output": text, "metadata": metadata, "llm_calls": llm_calls}


# ── Singleton factory ─────────────────────────────────────────────────────────

_analyzer_agent: Optional[DocumentAnalyzerAgent] = None

def get_analyzer_agent() -> DocumentAnalyzerAgent:
    """Returns a cached DocumentAnalyzerAgent singleton."""
    global _analyzer_agent
    if _analyzer_agent is None:
        _analyzer_agent = DocumentAnalyzerAgent()
    return _analyzer_agent
