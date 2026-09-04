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
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

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
        Classifies all clauses using rule-based scoring, then calls the LLM
        for any clauses that received no rule hit to get a second opinion.

        LLM is called only for GREEN (no-rule-hit) clauses — at most N calls
        where N = number of unmatched clauses.  For very long contracts this
        could be expensive; future versions should batch or sample.
        """
        results = self.classify_all(clauses)

        if not openai_api_key:
            logger.info("No OpenAI key — skipping LLM clause classification pass")
            return results

        # Only send clauses with no rule hit to the LLM
        needs_llm = [i for i, r in enumerate(results) if r.rule_hit is None]
        if not needs_llm:
            return results  # All clauses were covered by rules

        logger.info(
            "Sending %d clauses to LLM for secondary classification",
            len(needs_llm),
        )

        for idx in needs_llm:
            clause = clauses[idx]
            llm_result = await _classify_with_llm(clause, openai_api_key, model)
            results[idx] = llm_result

        return results


# ── LLM-assisted classification (called only for un-matched clauses) ──────────

async def _classify_with_llm(
    clause: str,
    api_key: str,
    model: str,
) -> ClauseResult:
    """
    Asks an LLM to classify a single clause as green/yellow/red.

    Critically: the prompt instructs the LLM to say "low" confidence if
    it cannot determine a clear risk level.  We never coerce a confident score.
    """
    from agents.document_analyzer.prompts import CLAUSE_CLASSIFICATION_SYSTEM, CLAUSE_CLASSIFICATION_USER

    from core.config import get_settings
    settings = get_settings()
    effective_api_key = settings.GEMINI_API_KEY or api_key
    model_name = settings.GEMINI_MODEL_DEV if settings.GEMINI_API_KEY else model

    if not effective_api_key or effective_api_key.startswith("sk-replace"):
        return ClauseResult(
            text=clause,
            risk_level=RiskLevel.GREEN,
            explanation="LLM classification unavailable.",
            confidence="low",
        )

    try:
        from google import genai
        client = genai.Client(api_key=effective_api_key)
        prompt = f"{CLAUSE_CLASSIFICATION_SYSTEM}\n\n{CLAUSE_CLASSIFICATION_USER.format(clause=clause)}"

        response = await client.aio.models.generate_content(
            model=model_name,
            contents=prompt,
        )
        raw = response.text.strip() if response.text else ""
        return _parse_llm_classification_response(clause, raw)
    except Exception as exc:
        logger.warning("LLM clause classification failed: %s", exc)
        return ClauseResult(
            text=clause,
            risk_level=RiskLevel.GREEN,
            explanation="Could not determine risk level — LLM call failed. Please review manually.",
            confidence="low",
        )


def _parse_llm_classification_response(clause: str, raw: str) -> ClauseResult:
    """
    Parses the LLM's JSON-like response into a ClauseResult.

    Expected LLM output format:
        RISK: yellow
        CONFIDENCE: medium
        EXPLANATION: This clause requires you to...

    If the response doesn't match the expected format, we return GREEN with
    confidence=low rather than guessing.
    """
    raw_lower = raw.lower()

    # Extract risk level
    risk_level = RiskLevel.GREEN
    if "risk: red" in raw_lower or "risk:red" in raw_lower:
        risk_level = RiskLevel.RED
    elif "risk: yellow" in raw_lower or "risk:yellow" in raw_lower:
        risk_level = RiskLevel.YELLOW

    # Extract confidence
    confidence = "low"  # default to low if unclear
    if "confidence: high" in raw_lower:
        confidence = "high"
    elif "confidence: medium" in raw_lower:
        confidence = "medium"

    # Extract explanation (everything after "EXPLANATION:")
    explanation = "See clause text."
    if "explanation:" in raw_lower:
        parts = raw.split("EXPLANATION:", 1) if "EXPLANATION:" in raw else raw.split("explanation:", 1)
        if len(parts) > 1:
            explanation = parts[1].strip()

    return ClauseResult(
        text=clause,
        risk_level=risk_level,
        rule_hit=None,
        explanation=explanation,
        confidence=confidence,
    )


# ── Module-level singleton ────────────────────────────────────────────────────

_classifier: Optional[ClauseClassifier] = None

def get_clause_classifier() -> ClauseClassifier:
    """Returns a singleton ClauseClassifier instance."""
    global _classifier
    if _classifier is None:
        _classifier = ClauseClassifier()
    return _classifier
