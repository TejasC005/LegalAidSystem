"""
=============================================================================
LEXIS Document Drafter Agent — Module 6
=============================================================================

Multi-turn legal document drafting agent.
Replicates the node & output structure of Rights Explainer Agent (Module 5),
extended for multi-turn conversational data collection & structured document assembly.

MULTI-TURN CONVERSATION FLOW:
-----------------------------
1. User provides query or answers previous question.
2. Agent inspects current draft session state (stored answers).
3. If questions remain -> return next question (status: "needs_info").
4. If all questions answered -> assemble final document template (status: "ok").
"""

import logging
import time
from typing import Dict, Any, List, Optional, Tuple

from agents.orchestrator.state import AgentOutput, OrchestratorState
from agents.document_drafter.templates import TEMPLATES, assemble_legal_notice, assemble_rti_application, assemble_consumer_complaint
from agents.document_drafter.prompts import DOCUMENT_DRAFTER_SYSTEM

logger = logging.getLogger(__name__)


class DocumentDrafterAgent:
    """
    Document Drafter Specialist Agent.
    Manages multi-turn questionnaire flow and document assembly.
    """

    def __init__(self):
        self.templates = TEMPLATES

    def match_template_type(self, query: str) -> str:
        """Determines the document template type based on user query keywords."""
        q = query.lower()
        if any(kw in q for kw in ["rti", "information act", "public information officer", "pio"]):
            return "rti_application"
        elif any(kw in q for kw in ["consumer", "defective", "unfair trade", "service deficiency", "forum", "product complaint"]):
            return "consumer_complaint"
        else:
            # Default to Legal Notice for general disputes (landlord, deposit, breach)
            return "legal_notice"

    async def process_turn(
        self,
        doc_type: str,
        collected_answers: Dict[str, Any],
        user_input: str = ""
    ) -> Tuple[str, Dict[str, Any], str]:
        """
        Executes one turn of document drafting logic.

        Returns: (response_text, updated_answers, status_str)
          - status_str = "needs_info" (more questions remain)
          - status_str = "ok" (document fully assembled)
        """
        if doc_type not in self.templates:
            doc_type = "legal_notice"

        template_info = self.templates[doc_type]
        questions = template_info["questions"]

        # Find first unanswered question
        unanswered_idx = None
        for idx, q in enumerate(questions):
            if q["key"] not in collected_answers or not str(collected_answers[q["key"]]).strip():
                unanswered_idx = idx
                break

        # If all questions answered -> Assemble Document!
        if unanswered_idx is None:
            assembler = template_info["assembler"]
            assembled_doc = assembler(collected_answers)
            response_text = (
                f"🎉 **{template_info['name']} Draft Complete!**\n\n"
                f"Here is your assembled document draft based on the details provided:\n\n"
                f"```text\n{assembled_doc}\n```\n\n"
                f"You can now download this document as a formatted **PDF** or **DOCX** file using the buttons below."
            )
            return response_text, collected_answers, "ok"

        # Ask next question
        next_q = questions[unanswered_idx]
        field_key = next_q["key"]
        field_prompt = next_q["question"]
        step_num = unanswered_idx + 1
        total_steps = len(questions)

        response_text = (
            f"📋 **Drafting {template_info['name']} (Step {step_num} of {total_steps})**\n\n"
            f"{field_prompt}"
        )
        return response_text, collected_answers, "needs_info"


# Singleton instance
_drafter_agent_instance: Optional[DocumentDrafterAgent] = None


def get_drafter_agent() -> DocumentDrafterAgent:
    global _drafter_agent_instance
    if _drafter_agent_instance is None:
        _drafter_agent_instance = DocumentDrafterAgent()
    return _drafter_agent_instance


async def drafter_agent_node(state: OrchestratorState) -> Dict:
    """
    LangGraph node function for Document Drafter Agent.
    Called by orchestrator specialist_node when intent == AgentIntent.DRAFT.

    SINGLE-SHOT ORCHESTRATOR vs. MULTI-TURN SESSION DESIGN:
    -------------------------------------------------------
    - In single-shot orchestrator queries (POST /api/v1/query), the user asks a legal question.
      If the classifier assigns 'draft' intent, this node initializes fresh context (empty answers {})
      and prompts the citizen to choose/start a document drafting session.
    - Full multi-turn question-and-answer collection with persistent state lives in MongoDB
      and is managed via the dedicated /api/v1/drafts/session endpoints.
    - This separation ensures the orchestrator state machine remains clean and non-blocking
      while enabling rich, stateful drafting wizards in the frontend UI.
    """
    query = state["query"]
    t_start = time.perf_counter()

    agent = get_drafter_agent()

    # Detect doc type from query
    doc_type = agent.match_template_type(query)

    # In single-shot orchestrator queries, initialize default context (Question 1)
    response_text, _, status = await agent.process_turn(doc_type, {}, user_input=query)

    elapsed_ms = int((time.perf_counter() - t_start) * 1000)

    output_record: AgentOutput = {
        "intent": "draft",
        "status": "ok" if status in ("ok", "needs_info") else "error",
        "output": response_text,
        "metadata": {
            "latency_ms": elapsed_ms,
            "agent": "DocumentDrafterAgent",
            "model": "template_clause_engine",
            "doc_type": doc_type,
            "draft_status": status,
        },
    }

    return {
        "scratchpad": [output_record],
        "llm_calls_used": 0,
    }
