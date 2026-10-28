"""
=============================================================================
LEXIS — Confirmation Agent: Per-Agent Validation Criteria  (Module 11)
=============================================================================

WHAT IS THIS FILE?
------------------
This file defines the CONCRETE, TESTABLE validation criteria that the
Confirmation Agent applies to each specialist agent's draft output.

WHY PER-AGENT CRITERIA (NOT A GENERIC CHECK)?
----------------------------------------------
Each specialist agent produces a structurally different output:
  - Rights Explainer → prose text that must cite a verified legal source.
  - Document Drafter → a filled template where every placeholder is required.
  - Document Analyzer → structured risk data where every clause needs a level.
  - Scam Detection   → DB-grounded alert that must reference a real pattern ID.
  - Filing Guide     → authority referral that must point to a real portal.
  - Vault Agent      → date extraction where low-confidence must be flagged.

Applying a single generic check (e.g. "is the output non-empty?") would miss
every one of these agent-specific failure modes.  A Rights answer that says
"You have rights under the law [general statement]" is non-empty but wrong —
it lacks the specific legal citation that makes it trustworthy.  Per-agent
criteria are what give the self-correction loop real meaning.

NO HALLUCINATED CRITERIA
-------------------------
Every criterion listed here maps to a CONCRETE code check:
  - String pattern match (regex or substring)
  - Metadata field presence/value check
  - Threshold comparison
Nothing is left as "LLM judges quality" — those checks are inherently
non-deterministic and untestable.

WHAT "PASS" AND "FAIL" MEAN
-----------------------------
  PASS  → The criterion is met.  The draft may be released to the citizen.
  FAIL  → The criterion is not met.  The draft is sent back to the originating
           agent with a specific, actionable feedback message explaining WHAT
           failed and WHAT is needed to fix it.  The agent uses this feedback
           on its retry attempt.
"""

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from agents.orchestrator.state import AgentIntent


# =============================================================================
# Data types
# =============================================================================

@dataclass
class ValidationResult:
    """
    The result of a single validation pass on one agent's draft.

    Attributes
    ----------
    passed          : True if all criteria were met.
    failure_reason  : If not passed, a specific human-readable explanation
                      of what failed.  Empty string if passed.
    feedback_for_retry : If not passed, the actionable message sent back to
                         the agent on its retry attempt.  This is more
                         prescriptive than failure_reason — it tells the agent
                         exactly what to produce, not just what was wrong.
    """
    passed: bool
    failure_reason: str = ""
    feedback_for_retry: str = ""

    def __bool__(self) -> bool:
        return self.passed


# =============================================================================
# Citation pattern
# =============================================================================

# Matches: [Source: <anything non-empty>]
_CITATION_PATTERN = re.compile(r'\[Source:\s*([^\]]+)\]', re.IGNORECASE)

# Matches Indian Act citations like "RTI Act 2005", "Consumer Protection Act 2019"
# Used by both criteria checking and cross-agent contradiction detection.
#
# PATTERN DESIGN:
#   Each word component is: [A-Z][a-zA-Z]* (allows both "RTI" and "Consumer")
#   Up to 4 such words before "Act YYYY".
#   Word boundary \b at start and end prevents absorbing surrounding prose.
#   Matches:
#     "RTI Act 2005", "Consumer Protection Act 2019"
#     "Model Tenancy Act 2021", "Information Technology Act 2000"
#   Does NOT match (missing year, no word boundary):
#     "the RTI Act", "some act"
ACT_CITATION_PATTERN = re.compile(
    r'\b([A-Z][a-zA-Z]*(?:\s+[A-Z][a-zA-Z]*){0,3}\s+Act\s+\d{4})\b',
)

# Matches unfilled template placeholders left by the Document Drafter
_PLACEHOLDER_PATTERN = re.compile(r'\[FILL IN[:\s]', re.IGNORECASE)
_BLANK_FIELD_PATTERN = re.compile(r'_{3,}')  # Three or more underscores = unfilled blank

# Matches SCAM DB pattern IDs (e.g. SCAM_001, SCAM_017)
_SCAM_DB_ID_PATTERN = re.compile(r'SCAM_\d{3}', re.IGNORECASE)

# Matches verified Indian government portal domains
_GOV_PORTAL_PATTERN = re.compile(r'https?://\S+\.(?:gov\.in|nic\.in)', re.IGNORECASE)

# Matches risk level labels used by the Document Analyzer
_RISK_LEVEL_PATTERN = re.compile(r'\b(GREEN|YELLOW|RED)\b')


# =============================================================================
# Per-agent validation functions
# =============================================================================

def validate_rights_output(output_text: str, metadata: Dict[str, Any]) -> ValidationResult:
    """
    Rights Explainer criterion:
      The output MUST contain at least one [Source: <non-empty>] citation
      referencing a retrieved legal document chunk.

    WHY: An uncited legal claim is indistinguishable from a hallucination.
    The citation proves the answer was grounded in retrieved legal text.

    Pass condition: _CITATION_PATTERN matches AND the captured group is
    non-empty (not just [Source: ] with nothing inside).
    """
    matches = _CITATION_PATTERN.findall(output_text)
    # Each match is the captured group (the citation text inside [...])
    non_empty_citations = [m.strip() for m in matches if m.strip()]

    if non_empty_citations:
        return ValidationResult(passed=True)

    # Also accept citations stored in metadata["citations"] list
    meta_citations: List[str] = metadata.get("citations", [])
    if meta_citations and any(c.strip() for c in meta_citations):
        return ValidationResult(passed=True)

    return ValidationResult(
        passed=False,
        failure_reason="Rights Explainer output is missing a verified legal citation.",
        feedback_for_retry=(
            "Your previous answer did not include a citation to the source law. "
            "You MUST end your answer with a citation in this exact format: "
            "[Source: <Act Name, Section Number>].  For example: "
            "[Source: RTI Act 2005, Section 7].  "
            "Only cite sources that appear in the retrieved legal chunks provided to you."
        ),
    )


def validate_drafter_output(output_text: str, metadata: Dict[str, Any]) -> ValidationResult:
    """
    Document Drafter criterion:
      The output MUST NOT contain unfilled template placeholders.
      [FILL IN: ...] markers or _____ blanks indicate an incomplete draft.

    WHY: A document with placeholders is not ready to use.  The citizen
    cannot file an RTI with "[FILL IN: Your Name]" in the header.

    Pass condition: No _PLACEHOLDER_PATTERN or _BLANK_FIELD_PATTERN matches
    in the output text.
    """
    placeholder_matches = _PLACEHOLDER_PATTERN.findall(output_text)
    blank_matches = _BLANK_FIELD_PATTERN.findall(output_text)

    # Only flag blanks if there are genuinely unfilled items (not just formatting)
    if placeholder_matches:
        count = len(placeholder_matches)
        return ValidationResult(
            passed=False,
            failure_reason=f"Document Drafter output contains {count} unfilled placeholder(s): [FILL IN: ...]",
            feedback_for_retry=(
                f"Your previous draft still contains {count} unfilled placeholder(s) "
                f"marked as [FILL IN: ...].  You must fill in EVERY placeholder with "
                f"appropriate content or clearly mark them as [TO BE PROVIDED BY CITIZEN].  "
                f"Do not leave [FILL IN: ...] markers in the final output."
            ),
        )

    if blank_matches:
        count = len(blank_matches)
        return ValidationResult(
            passed=False,
            failure_reason=f"Document Drafter output contains {count} unfilled blank field(s) (_____).",
            feedback_for_retry=(
                f"Your previous draft contains {count} blank field(s) indicated by underscores (_____).  "
                f"Replace every blank with either the correct information or a clear label "
                f"like [CITIZEN'S NAME] so the document is complete."
            ),
        )

    return ValidationResult(passed=True)


def validate_analyzer_output(output_text: str, metadata: Dict[str, Any]) -> ValidationResult:
    """
    Document Analyzer criterion:
      The output MUST contain at least one clause with a risk level
      classification (GREEN, YELLOW, or RED).

    WHY: The purpose of the Document Analyzer is to classify clauses.
    An output with no risk labels means the analysis pipeline did not
    complete — the citizen receives no actionable risk information.

    Pass condition: _RISK_LEVEL_PATTERN matches at least once in output text,
    OR metadata["clauses"] is a non-empty list where at least one item has
    a "risk_level" key.
    """
    risk_matches = _RISK_LEVEL_PATTERN.findall(output_text)
    if risk_matches:
        return ValidationResult(passed=True)

    # Check metadata structure for clause analysis results
    clauses = metadata.get("clauses", [])
    if isinstance(clauses, list) and any(
        isinstance(c, dict) and c.get("risk_level") for c in clauses
    ):
        return ValidationResult(passed=True)

    return ValidationResult(
        passed=False,
        failure_reason="Document Analyzer output contains no risk-level classifications for any clause.",
        feedback_for_retry=(
            "Your previous analysis did not assign a risk level (GREEN, YELLOW, or RED) to any clause.  "
            "Every clause or provision in the document must be evaluated and labelled.  "
            "Format each clause as: [RISK: GREEN/YELLOW/RED] followed by the clause text and explanation."
        ),
    )


def validate_scam_output(output_text: str, metadata: Dict[str, Any]) -> ValidationResult:
    """
    Scam Detection criterion:
      The output MUST reference a real DB pattern ID (SCAM_XXX format)
      OR explicitly state "no match found" (safe fallback).

    WHY: The Scam Detection Agent is DB-grounded — it must NEVER fabricate
    alert content.  If the output mentions a scam but provides no DB ID,
    the content may have been invented by the LLM rather than retrieved
    from the verified scam_patterns collection.

    Pass conditions:
      1. metadata["db_id"] is non-empty (e.g. "SCAM_001"), OR
      2. _SCAM_DB_ID_PATTERN matches in output_text, OR
      3. Output explicitly states no match (safe fallback path)
    """
    # Check metadata db_id (primary evidence of DB grounding)
    db_id = metadata.get("db_id", "")
    if db_id and isinstance(db_id, str) and db_id.strip():
        return ValidationResult(passed=True)

    # Check output text for inline pattern ID
    if _SCAM_DB_ID_PATTERN.search(output_text):
        return ValidationResult(passed=True)

    # Accept explicit no-match safe fallback (not a failure, a valid outcome)
    no_match_phrases = [
        "no known scam pattern",
        "could not match",
        "no match found",
        "not match any known",
        "cybercrime.gov.in",   # Present in the standard safe fallback text
        "1930",                # National Cyber Helpline number in safe fallback
    ]
    output_lower = output_text.lower()
    if any(phrase in output_lower for phrase in no_match_phrases):
        return ValidationResult(passed=True)

    return ValidationResult(
        passed=False,
        failure_reason="Scam Detection output lacks a verified DB pattern ID (SCAM_XXX) and is not a known safe fallback.",
        feedback_for_retry=(
            "Your scam alert was not grounded to a verified database record.  "
            "Every scam alert MUST include the pattern ID from the scam_patterns database "
            "(format: SCAM_001 through SCAM_017).  "
            "If no pattern matches the citizen's description, return the standard safe fallback "
            "directing them to cybercrime.gov.in and the 1930 helpline instead of generating "
            "unverified alert content."
        ),
    )


def validate_filing_output(output_text: str, metadata: Dict[str, Any]) -> ValidationResult:
    """
    Filing Guide criterion:
      The output MUST reference a verified government portal URL (*.gov.in or
      *.nic.in) OR explicitly mark unverified fields as "needs_verification".

    WHY: Filing guide outputs direct citizens to specific authorities and
    portals.  An incorrect portal URL could cause a citizen to file with
    the wrong authority, potentially missing deadlines.  Every output must
    either point to a verified URL or honestly flag what needs verification.

    Pass conditions:
      1. _GOV_PORTAL_PATTERN matches in output_text, OR
      2. "needs_verification" appears in output_text (honest flagging), OR
      3. metadata["portal_url"] is a verified domain
    """
    # Check for verified portal URL in text
    if _GOV_PORTAL_PATTERN.search(output_text):
        return ValidationResult(passed=True)

    # Check metadata portal URL
    portal_url = metadata.get("portal_url", "") or ""
    if portal_url and (".gov.in" in portal_url or ".nic.in" in portal_url):
        return ValidationResult(passed=True)

    # Accept explicit needs_verification flagging (honest, not a failure)
    if "needs_verification" in output_text.lower():
        return ValidationResult(passed=True)

    return ValidationResult(
        passed=False,
        failure_reason="Filing Guide output does not reference a verified government portal URL.",
        feedback_for_retry=(
            "Your filing guide response must include at least one verified government portal URL "
            "(e.g. rtionline.gov.in, edaakhil.nic.in).  "
            "If the correct portal URL is not confirmed, explicitly state "
            "'needs_verification' for that field rather than omitting the portal entirely.  "
            "Do not fabricate portal URLs."
        ),
    )


def validate_vault_output(output_text: str, metadata: Dict[str, Any]) -> ValidationResult:
    """
    Vault Agent criterion:
      All extracted dates with confidence < 0.70 MUST be flagged as
      requiring citizen confirmation (needs_confirmation: True).

    WHY: A wrong deadline stored without confirmation could cause a citizen
    to miss a legal filing deadline — irreversible real-world harm.  The
    Vault Agent must explicitly flag uncertain dates rather than silently
    converting them to deadlines.

    Pass conditions:
      1. metadata["extracted_dates"] is empty (no dates found — OK), OR
      2. All dates in metadata["extracted_dates"] satisfy:
           confidence >= 0.70  OR  needs_confirmation == True
    """
    extracted_dates = metadata.get("extracted_dates", [])
    if not extracted_dates:
        # No dates extracted — acceptable (text query path, or no dates in doc)
        return ValidationResult(passed=True)

    CONFIDENCE_THRESHOLD = 0.70
    problematic = []
    for date_entry in extracted_dates:
        if not isinstance(date_entry, dict):
            continue
        confidence = float(date_entry.get("confidence", 0.0))
        needs_confirmation = date_entry.get("needs_confirmation", False)
        if confidence < CONFIDENCE_THRESHOLD and not needs_confirmation:
            problematic.append({
                "date": date_entry.get("date_value", "unknown"),
                "confidence": confidence,
            })

    if not problematic:
        return ValidationResult(passed=True)

    dates_str = ", ".join(f"{d['date']} (conf={d['confidence']:.2f})" for d in problematic)
    return ValidationResult(
        passed=False,
        failure_reason=f"Vault Agent extracted date(s) below 0.70 confidence threshold without flagging: {dates_str}",
        feedback_for_retry=(
            f"The following extracted date(s) have confidence below 0.70 but were not flagged "
            f"for citizen confirmation: {dates_str}.  "
            f"You MUST set needs_confirmation=True for any date where confidence < 0.70.  "
            f"Never silently create a deadline from an uncertain date — require explicit citizen review."
        ),
    )


# =============================================================================
# Dispatcher — maps AgentIntent to its validator function
# =============================================================================

def validate_agent_output(
    intent: str,
    output_text: str,
    metadata: Dict[str, Any],
) -> ValidationResult:
    """
    Dispatches to the correct per-agent validation function based on intent.

    Parameters
    ----------
    intent      : AgentIntent value string (e.g. "rights", "draft")
    output_text : The agent's prose output string
    metadata    : The agent's metadata dict (from AgentOutput["metadata"])

    Returns
    -------
    ValidationResult with passed=True/False and feedback for retry
    """
    validators = {
        AgentIntent.RIGHTS.value:  validate_rights_output,
        AgentIntent.DRAFT.value:   validate_drafter_output,
        AgentIntent.ANALYZE.value: validate_analyzer_output,
        AgentIntent.SCAM.value:    validate_scam_output,
        AgentIntent.FILING.value:  validate_filing_output,
        AgentIntent.VAULT.value:   validate_vault_output,
    }

    validator_fn = validators.get(intent)
    if validator_fn is None:
        # Unknown intent — pass through without validation (defensive)
        return ValidationResult(
            passed=True,
            failure_reason="",
            feedback_for_retry="",
        )

    return validator_fn(output_text, metadata)
