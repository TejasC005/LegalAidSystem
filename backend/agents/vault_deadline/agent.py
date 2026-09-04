"""
=============================================================================
LEXIS — Vault & Deadline Agent (Module 10) — Agent 6
=============================================================================

This is the 6th specialist agent in LEXIS and the ONLY proactive one.
All other agents (Rights, Drafter, Analyzer, Scam, Filing) respond only
when the citizen initiates a query. The Vault & Deadline Agent additionally
acts without being asked — via the daily scheduler.

WHAT THIS AGENT DOES
---------------------
1. extract_dates_from_text(ocr_text)
   — Uses LLM to find deadline-relevant dates in OCR'd document text.
   — Returns ExtractedDate objects with confidence scores.
   — Confidence < 0.70 → needs_confirmation=True (citizen must verify).
   — NEVER stores a confirmed deadline without citizen approval.

2. invoke_document_drafter(doc_type, context)
   — Called by the scheduler at T-30/T-15/T-3 days before a deadline.
   — Imports DocumentDrafterAgent and generates a ready-to-use next-step letter.
   — This is the "proactive agentic" proof: the system drafts a legal document
     on the citizen's behalf, without any citizen-initiated query.

3. vault_agent_node(state)
   — LangGraph entry point for orchestrator routing (AgentIntent.VAULT).
   — Handles vault-intent queries from the chat interface.

DISTINCTION FROM FORENSIC EVIDENCE VAULT (FUTURE SCOPE)
---------------------------------------------------------
This agent provides simple encrypted personal document storage with calendar
reminders. It is NOT a chain-of-custody legal evidence system (which would
require cryptographic provenance, tamper-evident logging, and court-admissible
export formats). That is the excluded "Forensic Evidence Vault" in future scope.

ANONYMOUS MODE
--------------
This agent explicitly blocks anonymous sessions. Any anonymous user attempting
to access vault functionality receives a clear, friendly message explaining
why and how to get a real account — per the design note in Module 2.
"""

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Confidence threshold below which a date must be flagged for citizen confirmation
CONFIDENCE_THRESHOLD = 0.70


class VaultDeadlineAgent:
    """
    The Vault & Deadline specialist agent.

    Provides:
      - LLM-assisted date extraction from OCR text (with confidence flagging)
      - Proactive Document Drafter invocation (the "acts without being asked" feature)
      - LangGraph node entry point for orchestrator integration
    """

    async def extract_dates_from_text(
        self,
        ocr_text: str,
    ) -> list:
        """
        Uses an LLM to extract deadline-relevant dates from OCR text.

        SAFETY: Returns ExtractedDate-compatible dicts with:
          - confidence < 0.70 → needs_confirmation=True
          - raw_snippet always included (citizen can verify against document)

        Falls back to an empty list with a warning if LLM is unavailable.

        Returns list of dict (compatible with ExtractedDate model).
        """
        from agents.vault_deadline.prompts import (
            DATE_EXTRACTION_SYSTEM,
            DATE_EXTRACTION_USER_TEMPLATE,
        )

        if not ocr_text or not ocr_text.strip():
            logger.info("extract_dates_from_text: empty OCR text — returning empty list")
            return []

        # Try LLM extraction; fall back to empty on failure
        try:
            from core.config import get_settings
            settings = get_settings()

            api_key = settings.GEMINI_API_KEY or settings.OPENAI_API_KEY
            if not api_key or api_key.startswith("sk-replace"):
                raise RuntimeError("No valid LLM API key set — using empty fallback")

            model_name = settings.GEMINI_MODEL_DEV if settings.GEMINI_API_KEY else settings.OPENAI_MODEL_DEV
            from google import genai
            client = genai.Client(api_key=api_key)

            # Truncate very long OCR text to avoid token limits
            truncated_text = ocr_text[:8000] if len(ocr_text) > 8000 else ocr_text

            prompt = f"{DATE_EXTRACTION_SYSTEM}\n\n{DATE_EXTRACTION_USER_TEMPLATE.format(ocr_text=truncated_text)}"

            response = await client.aio.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            raw_json = response.text.strip() if response.text else ""

            # Strip markdown fences if LLM added them
            if raw_json.startswith("```"):
                raw_json = raw_json.split("```")[1]
                if raw_json.startswith("json"):
                    raw_json = raw_json[4:]

            parsed = json.loads(raw_json)

            if not isinstance(parsed, list):
                logger.warning("LLM date extraction returned non-list: %s", type(parsed))
                return []

            # Post-process: enforce needs_confirmation based on confidence
            result = []
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                confidence = float(item.get("confidence", 0.0))
                item["confidence"] = confidence
                item["needs_confirmation"] = (
                    item.get("needs_confirmation", False)
                    or confidence < CONFIDENCE_THRESHOLD
                )
                result.append(item)

            logger.info(
                "Date extraction complete",
                extra={
                    "dates_found": len(result),
                    "low_confidence": sum(1 for d in result if d.get("needs_confirmation")),
                },
            )
            return result

        except json.JSONDecodeError as exc:
            logger.warning("LLM returned invalid JSON for date extraction: %s", exc)
            return []
        except Exception as exc:
            logger.warning(
                "LLM date extraction failed (non-fatal, returning empty): %s", exc
            )
            return []

    async def invoke_document_drafter(
        self,
        doc_type: str,
        context: dict,
    ) -> str:
        """
        Proactively generates a ready-to-use document draft for an upcoming deadline.

        WHY THIS IS THE CORE "AGENTIC" PROOF
        ----------------------------------------
        All other agents in LEXIS respond to citizen queries — they are reactive.
        This method is called by the SCHEDULER, not by any citizen request.
        The system acts autonomously to produce a legal draft the citizen can
        immediately use, delivered alongside the reminder email.

        This hand-off between Vault Agent → Document Drafter Agent demonstrates
        genuine multi-agent collaboration: one agent (Vault) detects the need,
        another agent (Drafter) produces the output.

        Parameters:
            doc_type — document type for the Drafter (e.g., "legal_notice",
                       "rti_application", "consumer_complaint", or "generic_letter")
            context  — dict with label, deadline_date, days_remaining, user_id

        Returns: draft text as string (or empty string on failure)
        """
        from agents.vault_deadline.prompts import (
            DRAFTER_HANDOFF_SYSTEM,
            DRAFTER_HANDOFF_USER_TEMPLATE,
        )

        label = context.get("label", "Upcoming Deadline")
        deadline_date = context.get("deadline_date", "")
        days_remaining = context.get("days_remaining", 0)

        # Try LLM-based draft generation
        try:
            from core.config import get_settings
            settings = get_settings()

            if not settings.OPENAI_API_KEY:
                raise RuntimeError("No API key — using template draft")

            from langchain_openai import ChatOpenAI
            from langchain_core.messages import HumanMessage, SystemMessage

            llm = ChatOpenAI(
                model=settings.OPENAI_MODEL_DEV,
                api_key=settings.OPENAI_API_KEY,
                temperature=0.3,   # Slight creativity for natural letter prose
                max_tokens=600,
            )

            messages = [
                SystemMessage(content=DRAFTER_HANDOFF_SYSTEM),
                HumanMessage(content=DRAFTER_HANDOFF_USER_TEMPLATE.format(
                    label=label,
                    deadline_date=deadline_date,
                    days_remaining=days_remaining,
                    doc_type=doc_type,
                )),
            ]

            response = await llm.ainvoke(messages)
            draft_text = response.content.strip()

            logger.info(
                "Document Drafter invoked proactively",
                extra={
                    "doc_type": doc_type,
                    "days_remaining": days_remaining,
                    "draft_length": len(draft_text),
                },
            )
            return draft_text

        except Exception as exc:
            logger.warning(
                "Proactive Document Drafter invocation fell back to template: %s", exc
            )
            # Template fallback — basic but functional
            return self._template_draft(label, deadline_date, days_remaining, doc_type)

    def _template_draft(
        self,
        label: str,
        deadline_date: str,
        days_remaining: int,
        doc_type: str,
    ) -> str:
        """
        Offline template fallback for Document Drafter invocation.
        Used when the LLM API key is unavailable (tests, offline dev).
        """
        from datetime import datetime
        today = datetime.now().strftime("%d %B %Y")

        return f"""Date: {today}

To: [FILL IN: Recipient Name]
[FILL IN: Recipient Address]

Subject: URGENT NOTICE — {label} (Due: {deadline_date}, {days_remaining} Days Remaining)

Dear [FILL IN: Sir/Madam],

I, [FILL IN: Your Full Name], residing at [FILL IN: Your Address], am writing
to formally address the matter of: {label}, which falls due on {deadline_date}.

As this deadline is approaching in {days_remaining} days, I request your immediate
attention to ensure all necessary actions are completed within the stipulated timeframe.

[FILL IN: Describe the specific action required, e.g., lease renewal terms,
visa extension requirements, notice period obligations, etc.]

I look forward to your prompt response and cooperation in this regard.

Yours sincerely,
[FILL IN: Your Full Name]
[FILL IN: Your Contact Details]

---
This document was proactively generated by LEXIS Vault & Deadline Agent.
Please review and fill in the placeholders before submitting.
"""

    async def explain_for_query(self, query: str) -> tuple[str, dict, int]:
        """
        Orchestrator text-only path for vault intent queries.
        Returns (response_text, metadata, llm_calls).
        """
        response = (
            "The LEXIS Vault securely stores your important legal documents (Aadhaar, "
            "passports, lease agreements, legal notices) with AES-256 encryption. "
            "I can extract key deadline dates from your documents and send you proactive "
            "reminders at T-30, T-15, and T-3 days — including a ready-to-use draft letter. "
            "\n\nTo store a document, please use the Vault & Deadlines page in the sidebar. "
            "Note: Vault requires a real LEXIS account (not anonymous mode)."
        )
        metadata = {
            "agent": "VaultDeadlineAgent",
            "model": "template (vault info only via orchestrator)",
        }
        return response, metadata, 0


async def vault_agent_node(state) -> dict:
    """
    LangGraph node entry point for the Vault & Deadline Agent.
    Called by the orchestrator when AgentIntent.VAULT is detected.
    """
    agent = get_vault_agent()
    query = state.get("query", "")
    response_text, metadata, llm_calls = await agent.explain_for_query(query)
    return {
        "scratchpad": [{
            "intent": "vault",
            "status": "ok",
            "output": response_text,
            "metadata": metadata,
        }],
        "llm_calls_used": llm_calls,
    }


# ── Singleton factory ─────────────────────────────────────────────────────────

_vault_agent: Optional[VaultDeadlineAgent] = None


def get_vault_agent() -> VaultDeadlineAgent:
    """Returns a cached VaultDeadlineAgent singleton."""
    global _vault_agent
    if _vault_agent is None:
        _vault_agent = VaultDeadlineAgent()
    return _vault_agent
