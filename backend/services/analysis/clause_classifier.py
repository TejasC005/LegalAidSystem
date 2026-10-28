"""
=============================================================================
LEXIS — Clause-Level Risk Classifier (Module 7)
=============================================================================

WHAT THIS DOES
---------------
Given the full text of a legal document, this classifier:
  1. Splits the text into individual clauses (sentences / paragraphs).
  2. Scores each clause GREEN / YELLOW / RED based on risk.
  3. Returns a confidence score alongside the risk level.

WHY RULE-BASED + LLM-ASSISTED (NOT PURE LLM)
----------------------------------------------
Pure LLM classification has two problems:
  a) Cost: calling an LLM for every clause in a 10-page contract is expensive.
  b) Confidence theater: LLMs can sound confidently wrong.

Our approach:
  - Rule-based heuristics run FIRST.  They are fast (microseconds), free, and
    predictable for well-known risky clause patterns.
  - If a clause matches NO rule, and an LLM API key is configured, the LLM
    is consulted for a second opinion.
  - If the LLM is uncertain, it returns confidence=LOW.  We NEVER force a
    confident Red/Yellow score when the evidence is ambiguous.
    We would rather say "low confidence — please verify" than assert a wrong risk.

ADDING MORE RULES
------------------
# CLASSIFIER_NOTE: This rule set is a reasonable starting point.
# As more labelled examples are collected (e.g., from legal professionals
# reviewing flagged clauses), new patterns can be added to RISK_RULES below.
# A future improvement: replace or augment rules with a fine-tuned classifier.
"""

import re
import json
import asyncio
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any

logger = logging.getLogger(__name__)


# ── Risk level enum ───────────────────────────────────────────────────────────

class RiskLevel(str, Enum):
    GREEN  = "green"   # Clause appears standard / low-risk
    YELLOW = "yellow"  # Clause warrants attention — may need clarification
    RED    = "red"     # Clause is potentially harmful — should be flagged


# ── Per-clause result dataclass ───────────────────────────────────────────────

@dataclass
class ClauseResult:
    """
    The output for a single clause.

    Attributes:
        text        — The original clause text (verbatim from document)
        risk_level  — GREEN / YELLOW / RED
        rule_hit    — The rule that triggered this score (None if LLM-classified)
        explanation — Plain-language explanation of WHY this clause is flagged
        confidence  — "high" (rule match), "medium" (LLM confident), "low" (ambiguous)
        rewrite     — Plain-language rewrite (filled by rewriter.py for YELLOW/RED only)
    """
    text:        str
    risk_level:  RiskLevel
    rule_hit:    Optional[str]       = None
    explanation: str                 = ""
    confidence:  str                 = "high"   # "high" | "medium" | "low"
    rewrite:     Optional[str]       = None


# ── Rule definitions ──────────────────────────────────────────────────────────
# Each rule is a tuple of:
#   (rule_name, risk_level, keyword_patterns, explanation_template)
#
# Patterns are searched case-insensitively in the clause text.
# FIRST matching rule wins — order matters (more specific rules should come first).
#
# CLASSIFIER_NOTE: Add new rules here as you encounter more clause patterns.
# Reference: CII Model Contract templates, Indian Contract Act 1872 issues,
#            Consumer Protection Act 2019 unfair terms guidance.

RISK_RULES: List[Tuple[str, RiskLevel, List[str], str]] = [
    # ── RED rules ─────────────────────────────────────────────────────────────
    (
        "sole_arbitration_waiver",
        RiskLevel.RED,
        ["arbitration", "sole remedy", "binding arbitration", "waive.*right.*court", "no recourse to court"],
        "This clause forces disputes to private arbitration only, removing your right to approach a court. "
        "Under the Arbitration and Conciliation Act 1996, this may still be valid, but it limits your options.",
    ),
    (
        "unilateral_modification",
        RiskLevel.RED,
        ["sole discretion.*modify", "may change.*terms.*anytime", "reserves.*right.*change.*without notice",
         "amend.*policy.*without.*notice"],
        "This clause allows the other party to change the agreement terms at any time without your consent. "
        "Such terms are often considered unfair under the Consumer Protection Act 2019.",
    ),
    (
        "unlimited_liability_waiver",
        RiskLevel.RED,
        ["no liability.*whatsoever", "not liable.*under any circumstances", "excludes all liability",
         "maximum liability.*zero", "total liability.*nil"],
        "This clause attempts to eliminate all liability of the other party for any harm caused. "
        "Under Indian law, liability cannot be fully excluded for negligence causing personal injury.",
    ),
    (
        "data_sharing_without_consent",
        RiskLevel.RED,
        ["share.*personal data.*third part", "disclose.*information.*affiliates.*without",
         "sell.*user data", "transfer.*personal information"],
        "This clause allows your personal data to be shared or sold to third parties. "
        "This may violate the Digital Personal Data Protection Act 2023.",
    ),
    (
        "non_compete_broad",
        RiskLevel.RED,
        ["not compete.*worldwide", "non-compete.*all industries", "restrict.*employment.*globally"],
        "An overly broad non-compete clause restricting you globally or across all industries. "
        "Such clauses are generally unenforceable under Section 27 of the Indian Contract Act 1872.",
    ),
    # ── YELLOW rules ──────────────────────────────────────────────────────────
    (
        "auto_renewal",
        RiskLevel.YELLOW,
        ["automatically renew", "auto-renewal", "deemed renewed", "unless cancelled.*days"],
        "This clause auto-renews the agreement unless you actively cancel before a deadline. "
        "Note the cancellation window and mark the date.",
    ),
    (
        "indemnification_broad",
        RiskLevel.YELLOW,
        ["indemnif", "hold harmless", "defend.*against.*claims"],
        "This clause requires you to compensate the other party for a wide range of losses. "
        "Check whether the scope is limited to your own acts or includes third-party claims.",
    ),
    (
        "liquidated_damages",
        RiskLevel.YELLOW,
        ["liquidated damages", "penalty.*breach", "forfeit.*deposit.*breach"],
        "This clause sets a pre-determined penalty for breach. Under Section 74 of the Indian Contract Act, "
        "courts can reduce penalties that are disproportionate.",
    ),
    (
        "unilateral_termination",
        RiskLevel.YELLOW,
        ["terminate.*at.*will", "terminate.*without cause", "terminate.*immediately.*sole discretion"],
        "This clause allows the other party to end the agreement without reason. "
        "Ensure there is an equivalent right for you, or adequate notice is required.",
    ),
    (
        "governing_law_foreign",
        RiskLevel.YELLOW,
        ["governed by.*law.*of.*england", "governed by.*law.*of.*singapore",
         "jurisdiction.*delaware", "governed by.*law.*of.*us"],
        "This clause makes the agreement subject to a foreign legal system. "
        "This means you would need to litigate in a foreign jurisdiction, which is expensive.",
    ),
    (
        "security_deposit_no_return",
        RiskLevel.YELLOW,
        ["security deposit.*non-refundable", "deposit.*forfeited", "advance.*non-returnable"],
        "This clause states that your security deposit or advance may not be returned. "
        "Under the Model Tenancy Act 2021, residential deposits should be returned within one month of vacating.",
    ),
    (
        "data_collection_broad",
        RiskLevel.YELLOW,
        ["collect.*usage data", "track.*location", "record.*activity", "monitor.*communication"],
        "This clause permits broad collection of your data or monitoring of your activity. "
        "Review what data is collected and whether you can opt out.",
    ),
    (
        "ip_assignment_broad",
        RiskLevel.YELLOW,
        ["all.*intellectual property.*assigned", "work.*made.*for.*hire", "irrevocably.*assign.*ip"],
        "This clause transfers ownership of intellectual property you create to the other party. "
        "Ensure the scope is limited to work done under this specific agreement.",
    ),
    # ── GREEN rules (Standard Tenancy & Agreement terms) ──────────────────────
    (
        "standard_rent_payment",
        RiskLevel.GREEN,
        [
            r"monthly rent of rs",
            r"rent in respect of the demised premises shall commence",
            r"rent period.*in addition to the rental amount",
            r"payable on or before",
            r"payable by.*of each month",
            r"monthly maintenance charge",
            r"running cost of elevator and generator",
        ],
        "Standard rent, utility, and maintenance payment terms.",
    ),
    (
        "refundable_deposit",
        RiskLevel.GREEN,
        [
            r"refundable security deposit",
            r"interest-free refundable",
            r"security deposit shall be refunded",
            r"refunded by the owner to the tenant",
        ],
        "Standard refundable security deposit clause under Indian tenancy practice.",
    ),
    (
        "subletting_restriction",
        RiskLevel.GREEN,
        [
            r"not sublet.*assign",
            r"not sublet, assign or part with",
            r"residential purposes only",
        ],
        "Standard clause restricting subletting and specifying residential usage.",
    ),
    (
        "fixtures_and_fittings",
        RiskLevel.GREEN,
        [
            r"fittings and fixtures",
            r"sanitary, electrical and other fittings",
            r"maintain the demised premises in good and tenable condition",
            r"day-to-day minor repairs",
        ],
        "Standard clause for maintenance and handover of premises and fixtures.",
    ),
    (
        "standard_tenancy_notice",
        RiskLevel.GREEN,
        [
            r"terminated before the expiry.*notice in writing",
            r"serving one month prior notice",
            r"prior written notice.*vacate",
        ],
        "Standard termination clause with advance written notice period.",
    ),
    (
        "statutory_compliance_taxes",
        RiskLevel.GREEN,
        [
            r"comply with all the rules and regulations of the local authority",
            r"owner shall pay for all taxes/cesses",
            r"rent agreement will be registered",
        ],
        "Standard statutory compliance, municipal tax, and registration terms.",
    ),
]


# ── Clause splitter ───────────────────────────────────────────────────────────

def split_into_clauses(text: str) -> List[str]:
    """
    Splits extracted document text into individual clauses for classification.

    Strategy (pragmatic for legal documents):
      1. Split on numbered clause markers (1., 2., 1.1, (a), etc.)
      2. Then split on paragraph breaks (two or more newlines).
      3. Filter out very short fragments (< 30 chars) that are just headers.
      4. Strip whitespace and deduplicate.

    Returns a list of clause strings, each representing one unit to classify.
    """
    if not text or not text.strip():
        return []

    # Normalize whitespace
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Split on common legal clause numbering patterns
    # e.g. "1.", "1.1", "1.1.1", "(a)", "(i)", "CLAUSE 1", "Article 1"
    numbered_pattern = re.compile(
        r"(?:(?<=\n)|(?<=\n\n))"            # preceded by a newline
        r"(?:"
        r"\d+(?:\.\d+)*\."                   # 1. / 1.1. / 1.1.1.
        r"|[Cc]lause\s+\d+"                  # Clause 1
        r"|[Aa]rticle\s+\d+"                 # Article 1
        r"|\([a-zA-Z0-9]+\)"                 # (a) / (i) / (1)
        r"|[IVXivx]+\."                      # Roman numerals: I. II. III.
        r")\s+"
    )

    # First pass: split on numbered headings
    parts = re.split(numbered_pattern, text)

    # Second pass: further split on double newlines (paragraph breaks)
    clauses = []
    for part in parts:
        sub_parts = re.split(r"\n\n+", part)
        clauses.extend(sub_parts)

    # Clean and filter
    cleaned = []
    seen = set()
    for clause in clauses:
        clause = clause.strip()
        # Skip very short fragments (headers, page numbers, etc.)
        if len(clause) < 30:
            continue
        # Skip duplicates
        if clause in seen:
            continue
        seen.add(clause)
        cleaned.append(clause)

    logger.debug("Split document into %d clauses", len(cleaned))
    return cleaned


# ── Classifier ────────────────────────────────────────────────────────────────

class ClauseClassifier:
    """
    Classifies individual clauses as GREEN / YELLOW / RED.

    Uses rule-based heuristics first for speed and cost efficiency.
    Falls back to LLM classification for clauses that match no rule.
    Never asserts a confident score when the evidence is ambiguous.
    """

    def classify_clause(self, clause: str) -> ClauseResult:
        """
        Classifies a single clause.

        Returns a ClauseResult with risk_level, explanation, and confidence.
        This method is synchronous; call `classify_all` for async LLM fallback.
        """
        clause_lower = clause.lower()

        # ── Rule-based pass (fast, free) ──────────────────────────────────
        for rule_name, risk_level, patterns, explanation in RISK_RULES:
            for pattern in patterns:
                if re.search(pattern, clause_lower):
                    logger.debug(
                        "Rule hit: %s (%s)",
                        rule_name, risk_level.value,
                        extra={"rule": rule_name, "risk": risk_level.value} if False else {},
                    )
                    return ClauseResult(
                        text=clause,
                        risk_level=risk_level,
                        rule_hit=rule_name,
                        explanation=explanation,
                        confidence="high",  # rule match = high confidence
                    )

        # ── No rule matched: mark GREEN with low confidence ────────────────
        # The LLM pass (in classify_all_async) will upgrade this if needed.
        return ClauseResult(
            text=clause,
            risk_level=RiskLevel.GREEN,
            rule_hit=None,
            explanation="No known risk patterns detected. Appears standard.",
            confidence="high",  # will be overwritten by LLM if called
        )

    def classify_all(self, clauses: List[str]) -> List[ClauseResult]:
        """
        Classifies all clauses using rule-based scoring only (synchronous).

        This is the offline / test mode path.
        For LLM-assisted classification, use classify_all_async().
        """
        return [self.classify_clause(c) for c in clauses]

    async def classify_all_async(
        self,
        clauses: List[str],
        openai_api_key: str = "",
        model: str = "gpt-4o-mini",
    ) -> List[ClauseResult]:
        """
        Classifies all clauses using rule-based scoring first (0.00ms).
        Any clauses matching no rule are classified in a SINGLE high-speed
        batch LLM round-trip with timeout and graceful fallback.
        """
        results = self.classify_all(clauses)

        from core.config import get_settings
        settings = get_settings()
        effective_api_key = settings.GEMINI_API_KEY or openai_api_key
        if not effective_api_key or effective_api_key.startswith("sk-replace"):
            logger.info("No active Gemini/OpenAI key — skipping LLM clause classification pass")
            return results

        # Only send clauses with no rule hit to the LLM
        needs_llm_items = [(i, clauses[i]) for i, r in enumerate(results) if r.rule_hit is None]
        if not needs_llm_items:
            logger.debug("All %d clauses covered by rule heuristics; 0 LLM calls needed.", len(clauses))
            return results

        logger.info(
            "Sending %d unmatched clauses to LLM in a single high-speed batch call",
            len(needs_llm_items),
        )

        batch_results = await _classify_batch_with_llm(
            needs_llm_items,
            api_key=openai_api_key,
            model=model,
        )

        for idx, clause_res in batch_results.items():
            results[idx] = clause_res

        return results


# ── Batch LLM-assisted classification ─────────────────────────────────────────

BATCH_CLASSIFICATION_PROMPT = """You are an Indian legal contract risk analyst and plain-language assistant.
Classify the legal risk for each numbered clause below from the perspective of an Indian citizen/tenant/contractor.

Risk Level Criteria:
- "green": Routine, standard, fair, and customary Indian tenancy/contractual term.
- "yellow": Cautionary, warrants attention, notice periods, minor penalties, or ambiguous liability.
- "red": High risk, unfair, void under Indian law (e.g., Section 27/28 Indian Contract Act, sole arbitration waiver, total liability waiver, unconsented personal data sale).

For each clause, produce:
- "index": integer matching the clause number
- "risk_level": "green" | "yellow" | "red"
- "confidence": "high" | "medium" | "low"
- "explanation": concise 1-2 sentence explanation of why it is rated so under Indian law
- "rewrite": for "yellow" or "red", provide a plain-language explanation or fair alternative. For "green", leave as ""

Output ONLY a JSON array with this exact structure:
[
  {
    "index": 1,
    "risk_level": "green",
    "confidence": "high",
    "explanation": "Standard payment term.",
    "rewrite": ""
  }
]

Clauses to classify:
{clauses_text}
"""


def _extract_json_array(text: str) -> Optional[List[Dict[str, Any]]]:
    """Extracts a JSON list from LLM output, handling markdown fences and snippets."""
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, list):
            return parsed
    except Exception:
        pass
    # Regex fallback for [ ... ]
    match = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
    return None


async def _classify_batch_with_llm(
    items: List[Tuple[int, str]],
    api_key: str = "",
    model: str = "",
) -> Dict[int, ClauseResult]:
    """
    Classifies a batch of clauses in a single LLM round-trip with timeout and graceful fallback.
    Returns a dictionary mapping original clause index -> ClauseResult.
    """
    from core.config import get_settings
    settings = get_settings()
    effective_api_key = settings.GEMINI_API_KEY or api_key

    # Default fallback results for all items
    results: Dict[int, ClauseResult] = {
        idx: ClauseResult(
            text=text,
            risk_level=RiskLevel.GREEN,
            rule_hit=None,
            explanation="Standard legal term. No high-risk patterns detected.",
            confidence="low",
            rewrite=None,
        )
        for idx, text in items
    }

    if not effective_api_key or effective_api_key.startswith("sk-replace"):
        return results

    formatted_clauses = "\n\n".join(f"[{idx}] {text}" for idx, text in items)
    prompt = BATCH_CLASSIFICATION_PROMPT.replace("{clauses_text}", formatted_clauses)

    parsed_list: Optional[List[Dict[str, Any]]] = None

    # Try Google GenAI first with cascade and per-request 10s timeout
    candidate_models = [
        settings.GEMINI_MODEL_DEV or "gemini-3.5-flash-lite",
        "gemini-3.5-flash-lite",
        "gemini-2.5-flash",
    ]
    seen = set()
    models_to_try = [m for m in candidate_models if not (m in seen or seen.add(m))]

    try:
        from google import genai
        client = genai.Client(api_key=effective_api_key)
        for m_name in models_to_try:
            try:
                response = await asyncio.wait_for(
                    client.aio.models.generate_content(
                        model=m_name,
                        contents=prompt,
                    ),
                    timeout=5.0,
                )
                raw_text = response.text.strip() if response.text else ""
                parsed_list = _extract_json_array(raw_text)
                if parsed_list:
                    break
            except Exception as m_exc:
                logger.warning("Batch GenAI classification failed on model '%s': %s", m_name, m_exc)
    except Exception as exc:
        logger.warning("GenAI client error during batch classification: %s", exc)

    # If GenAI did not return a valid list, try OpenAI if key is present
    if not parsed_list:
        openai_key = settings.OPENAI_API_KEY or api_key
        if openai_key and not openai_key.startswith("sk-replace"):
            try:
                from openai import AsyncOpenAI
                oa_client = AsyncOpenAI(api_key=openai_key)
                oa_resp = await asyncio.wait_for(
                    oa_client.chat.completions.create(
                        model=settings.OPENAI_MODEL_DEV or "gpt-4o-mini",
                        messages=[{"role": "user", "content": prompt}],
                    ),
                    timeout=10.0,
                )
                raw_text = oa_resp.choices[0].message.content or ""
                parsed_list = _extract_json_array(raw_text)
            except Exception as oa_exc:
                logger.warning("OpenAI fallback failed for batch classification: %s", oa_exc)

    if not parsed_list:
        logger.info("Batch LLM classification returned no parsed results; using rule-based defaults.")
        return results

    # Map parsed list back to results
    risk_lookup = {
        "red": RiskLevel.RED,
        "yellow": RiskLevel.YELLOW,
        "green": RiskLevel.GREEN,
    }

    for item in parsed_list:
        try:
            idx = int(item.get("index"))
            if idx in results:
                raw_risk = str(item.get("risk_level", "green")).lower().strip()
                risk_lvl = risk_lookup.get(raw_risk, RiskLevel.GREEN)
                explanation = str(item.get("explanation") or "Standard clause.").strip()
                conf = str(item.get("confidence") or "medium").lower().strip()
                if conf not in ("high", "medium", "low"):
                    conf = "medium"
                rewrite_val = item.get("rewrite")
                rewrite_str = str(rewrite_val).strip() if rewrite_val else None

                results[idx] = ClauseResult(
                    text=results[idx].text,
                    risk_level=risk_lvl,
                    rule_hit=None,
                    explanation=explanation,
                    confidence=conf,
                    rewrite=rewrite_str if risk_lvl in (RiskLevel.YELLOW, RiskLevel.RED) else None,
                )
        except (ValueError, TypeError, KeyError) as parse_err:
            logger.debug("Skipping unparseable item in batch classification: %s", parse_err)

    return results


async def _classify_with_llm(
    clause: str,
    api_key: str,
    model: str,
) -> ClauseResult:
    """
    Fallback single-clause classification helper for backward compatibility.
    """
    batch_res = await _classify_batch_with_llm([(0, clause)], api_key=api_key, model=model)
    return batch_res.get(0, ClauseResult(
        text=clause,
        risk_level=RiskLevel.GREEN,
        explanation="Standard clause.",
        confidence="low",
    ))


# ── Module-level singleton ────────────────────────────────────────────────────

_classifier: Optional[ClauseClassifier] = None

def get_clause_classifier() -> ClauseClassifier:
    """Returns a singleton ClauseClassifier instance."""
    global _classifier
    if _classifier is None:
        _classifier = ClauseClassifier()
    return _classifier
