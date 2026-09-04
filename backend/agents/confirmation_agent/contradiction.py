"""
=============================================================================
LEXIS — Confirmation Agent: Cross-Agent Contradiction Checker  (Module 11)
=============================================================================

WHAT IS THIS FILE?
------------------
This file implements the cross-agent contradiction detector.

WHAT IS A CROSS-AGENT CONTRADICTION AND HOW IS IT DIFFERENT FROM
SINGLE-AGENT VALIDATION?
-----------------------------------------------------------------
Single-agent validation (in criteria.py) checks ONE agent's output in
isolation against type-specific rules.  For example:
  "Does this Rights output have a citation?"

Cross-agent contradiction checking compares TWO OR MORE outputs against
EACH OTHER.  For example:
  Rights Agent output says "file under RTI Act 2005"
  Filing Guide output says "file under Consumer Protection Act 2019"

Both outputs pass their individual checks (both have citations, both have
portal URLs).  The contradiction only becomes visible when comparing them
side by side.  A citizen who reads both responses receives conflicting
instructions about which law governs their situation.

WHY THIS ONLY RUNS WHEN MULTIPLE AGENTS CONTRIBUTE
----------------------------------------------------
Single-agent queries cannot produce cross-agent contradictions — there is
only one output.  This check is only meaningful (and only runs) when 2+ agents
contributed results to the same request, which is the concurrent multi-agent
scenario proven in Module 6.

CONCRETE IMPLEMENTED RULE (RULE C1)
-------------------------------------
C1 — Legal Act Mismatch

When BOTH a Rights Explainer output AND a Filing Guide output are present
in the scratchpad, extract the primary Indian Act name from each using the
ACT_CITATION_PATTERN regex.  If both extractions succeed AND the first
matched Act from Rights ≠ the first matched Act from Filing, flag as a
contradiction.

WHY THIS IS TESTABLE:
  Mock Rights output with "...under Consumer Protection Act 2019..."
  Mock Filing output  with "...file under RTI Act 2005..."
  → Contradiction detected: "Consumer Protection Act 2019 vs RTI Act 2005"

  Mock both outputs with "...RTI Act 2005..."
  → No contradiction.  Test confirms the checker correctly returns None.

IMPORTANT: This rule does NOT flag contradictions when:
  - One or both outputs have no Act citation (cannot compare what isn't there)
  - One output uses a phrase like "in addition to" (additive, not contradictory)
  - The two Act names are the same (no conflict)
"""

import logging
import re
from dataclasses import dataclass
from typing import List, Optional

from agents.orchestrator.state import AgentIntent, AgentOutput

logger = logging.getLogger(__name__)

# ── Imported from criteria.py to reuse the same regex ────────────────────────
# Matches Indian Act names like "RTI Act 2005", "Consumer Protection Act 2019"
from agents.confirmation_agent.criteria import ACT_CITATION_PATTERN


@dataclass
class ContradictionResult:
    """
    The result of a cross-agent contradiction check.

    Attributes
    ----------
    has_contradiction : True if a contradiction was detected.
    description       : Human-readable explanation of the contradiction found,
                        or empty string if none.
    agents_involved   : Which agent intents were compared (e.g. ["rights", "filing"])
    """
    has_contradiction: bool
    description: str = ""
    agents_involved: List[str] = None

    def __post_init__(self):
        if self.agents_involved is None:
            self.agents_involved = []


def _extract_primary_act(text: str) -> Optional[str]:
    """
    Extracts the first Indian Act citation from text.

    Returns the Act name string (e.g. "RTI Act 2005") or None if no Act
    citation is found.

    Only the FIRST match is returned — this is the "primary" act the agent
    is directing the citizen to.  Secondary mentions (e.g. "unlike the RTI
    Act 2005, the Consumer Protection Act...") are not used in the comparison
    to avoid false positives from educational context.
    """
    match = ACT_CITATION_PATTERN.search(text)
    if match:
        return match.group(1).strip()
    return None


# ── Additive context phrases that negate a mismatch ──────────────────────────
# If either output contains one of these phrases, a different Act citation
# does NOT constitute a contradiction — it's providing supplementary context.
_ADDITIVE_PHRASES = [
    "in addition to",
    "alongside",
    "also applies",
    "together with",
    "combined with",
    "as well as",
]


def check_rights_vs_filing_contradiction(
    rights_output: AgentOutput,
    filing_output: AgentOutput,
) -> ContradictionResult:
    """
    Rule C1 — Legal Act Mismatch between Rights Explainer and Filing Guide.

    Extracts the primary Act citation from each output and compares them.
    If they name DIFFERENT Acts AND neither output uses an additive phrase,
    this is a contradiction: the citizen is receiving conflicting legal
    authority guidance.

    Parameters
    ----------
    rights_output : AgentOutput from the Rights Explainer specialist node
    filing_output : AgentOutput from the Filing Guide specialist node

    Returns
    -------
    ContradictionResult with has_contradiction=True and a description if
    an Act mismatch is found; has_contradiction=False otherwise.
    """
    rights_text = rights_output.get("output", "")
    filing_text = filing_output.get("output", "")

    rights_act = _extract_primary_act(rights_text)
    filing_act = _extract_primary_act(filing_text)

    if not rights_act or not filing_act:
        # Cannot compare if one or both outputs have no Act citation.
        # This is NOT a contradiction — it just means the check is inconclusive.
        logger.debug(
            "C1 check: one or both outputs have no Act citation. rights_act=%s filing_act=%s",
            rights_act, filing_act,
        )
        return ContradictionResult(
            has_contradiction=False,
            agents_involved=["rights", "filing"],
        )

    # Normalize for comparison (case-insensitive, strip extra whitespace)
    rights_act_norm = re.sub(r'\s+', ' ', rights_act.lower().strip())
    filing_act_norm = re.sub(r'\s+', ' ', filing_act.lower().strip())

    if rights_act_norm == filing_act_norm:
        # Same Act — no contradiction
        logger.debug("C1 check: Acts match (%s). No contradiction.", rights_act)
        return ContradictionResult(
            has_contradiction=False,
            agents_involved=["rights", "filing"],
        )

    # Different Acts — check for additive phrases that negate contradiction
    combined_text = (rights_text + " " + filing_text).lower()
    is_additive = any(phrase in combined_text for phrase in _ADDITIVE_PHRASES)

    if is_additive:
        logger.debug(
            "C1 check: Different Acts (%s vs %s) but additive context detected — not a contradiction.",
            rights_act, filing_act,
        )
        return ContradictionResult(
            has_contradiction=False,
            agents_involved=["rights", "filing"],
        )

    # Genuine contradiction: different primary Acts, no additive context
    description = (
        f"Rights Explainer cited '{rights_act}' as the governing law, "
        f"but Filing Guide referenced '{filing_act}'.  "
        f"These may be inconsistent — verify which Act applies to the citizen's situation "
        f"before presenting both responses together."
    )

    logger.warning(
        "CONTRADICTION DETECTED (C1): rights_act='%s' filing_act='%s'",
        rights_act, filing_act,
        extra={
            "rule": "C1_legal_act_mismatch",
            "rights_act": rights_act,
            "filing_act": filing_act,
        },
    )

    return ContradictionResult(
        has_contradiction=True,
        description=description,
        agents_involved=["rights", "filing"],
    )


def run_contradiction_checks(scratchpad: List[AgentOutput]) -> Optional[ContradictionResult]:
    """
    Runs all applicable contradiction checks across the scratchpad entries.

    This is the main entry point called by the Confirmation Agent node.
    It inspects which agent outputs are present and applies the relevant
    cross-agent rules.

    Currently implemented rules:
      - C1: Rights vs Filing Act mismatch (runs when both are present)

    Future rules to add (as more cross-agent patterns emerge):
      - C2: Scam detection contradicts rights advice (e.g. "pay the fee" vs "never pay")
      - C3: Document Analyzer risk findings contradict Filing Guide advice

    Parameters
    ----------
    scratchpad : List of AgentOutput records from the current request.
                 Only processes records with status == "ok".

    Returns
    -------
    The first ContradictionResult that has has_contradiction=True,
    or None if all checks pass (no contradiction found).
    """
    # Build a lookup of successful outputs by intent
    ok_outputs = {
        r["intent"]: r
        for r in scratchpad
        if r.get("status") == "ok"
    }

    # Only run cross-agent checks when 2+ agents produced results
    if len(ok_outputs) < 2:
        return None

    # ── Rule C1: Rights vs Filing ─────────────────────────────────────────────
    if AgentIntent.RIGHTS.value in ok_outputs and AgentIntent.FILING.value in ok_outputs:
        result = check_rights_vs_filing_contradiction(
            rights_output=ok_outputs[AgentIntent.RIGHTS.value],
            filing_output=ok_outputs[AgentIntent.FILING.value],
        )
        if result.has_contradiction:
            return result

    # ── Add future rules here ─────────────────────────────────────────────────
    # e.g. Rule C2: Scam vs Rights, Rule C3: Analyzer vs Filing

    return None  # No contradiction found
