"""
=============================================================================
LEXIS — Plain-Language Clause Rewriter (Module 7)
=============================================================================

PURPOSE
--------
For every YELLOW or RED clause, this service generates a short plain-language
explanation in English (with optional Hindi phrasing) that a citizen without
legal training can understand.

WHY ONLY YELLOW AND RED?
--------------------------
GREEN clauses are standard — rewriting them would add noise and confuse
users.  We only explain clauses that actually need attention.

TWO-TIER APPROACH
------------------
1. Template fallback (always available):
   Uses the rule_hit name from the classifier to look up a pre-written
   plain-language explanation.  Works offline, zero cost.

2. LLM rewrite (when API key is available):
   Asks the LLM to rewrite the specific clause in plain English/Hindi.
   The LLM is given the original clause text AND the risk classification
   as context so it can be specific rather than generic.
"""

import logging
from typing import Optional

from services.analysis.clause_classifier import ClauseResult, RiskLevel

logger = logging.getLogger(__name__)


# ── Template fallback rewrites (offline, free) ────────────────────────────────
# Maps rule_hit name → plain-language explanation template.
# Used when no LLM is available.
TEMPLATE_REWRITES = {
    "sole_arbitration_waiver": (
        "⚠️ इस खंड का मतलब: यह क्लॉज़ आपको अदालत में जाने से रोकता है। "
        "In English: This clause says that if there is a dispute, you can only go to a private arbitrator "
        "— not a court. This limits your legal options. Ask the other party to allow court access too."
    ),
    "unilateral_modification": (
        "⚠️ इस खंड का मतलब: दूसरी पार्टी बिना आपकी सहमति के शर्तें बदल सकती है। "
        "In English: The other party can change the rules of this agreement at any time without telling you first. "
        "This is an unfair term under the Consumer Protection Act 2019. Request a clause requiring written notice."
    ),
    "unlimited_liability_waiver": (
        "⚠️ In English: This clause says the other party is not responsible for ANY harm they cause you, "
        "no matter what. Under Indian law, you cannot legally sign away your right to compensation for personal injury "
        "caused by negligence. This clause may not be fully enforceable, but it is a red flag."
    ),
    "data_sharing_without_consent": (
        "⚠️ आपका डेटा बेचा जा सकता है। "
        "In English: This clause allows your personal information to be shared with or sold to other companies. "
        "Under the Digital Personal Data Protection Act 2023, you have rights over your data. "
        "Ask: which third parties? Can you opt out?"
    ),
    "non_compete_broad": (
        "⚠️ In English: This clause tries to stop you from working in your field globally or across all industries. "
        "Under Section 27 of the Indian Contract Act 1872, such broad non-competes are generally unenforceable in India. "
        "However, a narrow geographic/time-limited non-compete may still be valid."
    ),
    "auto_renewal": (
        "📅 In English: This agreement will renew automatically on the expiry date unless you actively cancel it. "
        "Mark your calendar before the cancellation deadline stated in this clause."
    ),
    "indemnification_broad": (
        "📋 In English: You are agreeing to pay the other party's legal costs and losses in certain situations. "
        "Check: is the scope limited to your own mistakes, or does it include third-party claims too? "
        "A broad indemnity clause can be very expensive."
    ),
    "liquidated_damages": (
        "💰 In English: If you break this agreement, you must pay a fixed penalty amount. "
        "Under Section 74 of the Indian Contract Act 1872, a court can reduce this penalty if it is disproportionate "
        "to the actual harm caused."
    ),
    "unilateral_termination": (
        "🔴 In English: The other party can cancel this agreement without giving any reason. "
        "Check whether you have the same right. If not, negotiate for at least 30 days' written notice."
    ),
    "governing_law_foreign": (
        "⚠️ In English: Disputes under this agreement would be handled under a foreign country's law. "
        "This means you may need to hire a lawyer in that country, which is very costly. "
        "Try to negotiate Indian governing law and jurisdiction."
    ),
    "security_deposit_no_return": (
        "💰 In English: Your security deposit or advance payment may not be returned. "
        "Under the Model Tenancy Act 2021 (for residential property), the landlord must return the deposit "
        "within one month of you vacating the property. Verify whether this clause is legally valid in your state."
    ),
    "data_collection_broad": (
        "📱 In English: This clause permits the other party to monitor your activities or collect data about you broadly. "
        "Ask: exactly what data is collected? Is there an opt-out? Under the DPDP Act 2023, you can request "
        "access to and deletion of your personal data."
    ),
    "ip_assignment_broad": (
        "💡 In English: Any work or ideas you create could automatically belong to the other party. "
        "Ensure the scope is limited to work specifically created under this contract — "
        "not everything you create during the contract period."
    ),
}

# Generic fallback for RED clauses with no matching template
GENERIC_RED_REWRITE = (
    "🔴 High Risk Clause — इस खंड में जोखिम है। "
    "In English: This clause was flagged as high risk. It may significantly limit your rights "
    "or impose major obligations on you. We strongly recommend consulting a lawyer before signing."
)

# Generic fallback for YELLOW clauses with no matching template
GENERIC_YELLOW_REWRITE = (
    "🟡 Caution Required — ध्यान दें। "
    "In English: This clause warrants careful attention. It may include conditions that are unusual "
    "or that require you to take action (e.g., cancel before a deadline). Read it carefully."
)


async def rewrite_clause(
    result: ClauseResult,
    openai_api_key: str = "",
    model: str = "gpt-4o-mini",
) -> str:
    """
    Generates a plain-language Hindi/English rewrite for a YELLOW or RED clause.
    """
    if result.risk_level == RiskLevel.GREEN:
        return ""

    from core.config import get_settings
    settings = get_settings()
    api_key = settings.GEMINI_API_KEY or openai_api_key

    # Try LLM rewrite first (most specific)
    if api_key and not api_key.startswith("sk-replace"):
        llm_rewrite = await _llm_rewrite(result, api_key, model)
        if llm_rewrite:
            return llm_rewrite

    # Template fallback
    if result.rule_hit and result.rule_hit in TEMPLATE_REWRITES:
        return TEMPLATE_REWRITES[result.rule_hit]

    # Generic fallback
    if result.risk_level == RiskLevel.RED:
        return GENERIC_RED_REWRITE
    return GENERIC_YELLOW_REWRITE


async def _llm_rewrite(
    result: ClauseResult,
    api_key: str,
    model: str,
) -> str:
    """
    Uses an LLM to produce a specific plain-language explanation for the clause.
    """
    from agents.document_analyzer.prompts import REWRITE_SYSTEM, REWRITE_USER
    from core.config import get_settings
    settings = get_settings()
    model_name = settings.GEMINI_MODEL_DEV if settings.GEMINI_API_KEY else model

    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        prompt = f"{REWRITE_SYSTEM}\n\n{REWRITE_USER.format(risk_level=result.risk_level.value.upper(), rule_explanation=result.explanation, clause_text=result.text[:1000])}"

        response = await client.aio.models.generate_content(
            model=model_name,
            contents=prompt,
        )
        return response.text.strip() if response.text else ""
    except Exception as exc:
        logger.warning("LLM clause rewrite failed: %s", exc)
        return ""
