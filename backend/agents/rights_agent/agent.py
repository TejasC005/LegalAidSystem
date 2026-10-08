"""
=============================================================================
LEXIS Rights Explainer Agent — Module 5: Reference Implementation
=============================================================================

BEGINNER-FRIENDLY CONCEPTUAL EXPLANATION: WHAT IS RAG & HOW DOES IT WORK?
-----------------------------------------------------------------------------
1. WHAT IS RAG (Retrieval-Augmented Generation)?
   RAG is a design pattern where an AI model does NOT answer questions purely
   from its pre-trained memory. Instead, when a user asks a question, the system
   FIRST searches a verified database (Retrieval) for factual documents, and
   THEN feeds those exact documents into the LLM along with the user's question
   to draft the answer (Generation).

2. WHY RETRIEVE BEFORE GENERATING INSTEAD OF ASKING THE LLM DIRECTLY?
   Large Language Models (LLMs) are probabilistic text prediction engines.
   If you ask an LLM directly: "What is Section 13 of the Model Tenancy Act?",
   the LLM might hallucinate a plausible-sounding legal section number or Act
   name that doesn't actually exist in Indian law.
   In legal applications, a hallucinated law or incorrect section number can
   cause severe real-world harm to a citizen.
   By retrieving real, verified legal text from our Qdrant vector database
   BEFORE generating, we constrain the LLM to summarize ONLY what was pulled
   from official legal sources. If retrieval returns no confident match, we
   refuse to answer rather than guess.

3. HOW DOES THE CITATION GET ATTACHED?
   Every document stored in our Qdrant vector database includes structured
   metadata fields: `act_name`, `section`, `title`, and `citation` (e.g.,
   "Model Tenancy Act 2021, Section 13 & 21").
   When a user query matches a chunk in Qdrant, we extract its `citation` field.
   We pass this citation to the LLM system prompt instructing it to append
   `[Source: <citation>]`. Finally, our code performs a mandatory output validation
   check: if the draft response lacks a verified citation back to a retrieved
   chunk, we automatically append the citation before delivering the response.

REFERENCE TEMPLATE NOTICE:
--------------------------
This Rights Agent is the REFERENCE IMPLEMENTATION for LEXIS specialist agents.
Modules 6-10 (Document Drafter, Document Analyzer, Scam Detection, Filing Guide,
Vault Agent) follow this exact structure: Vector Retrieval -> Safeguard Threshold ->
LLM Generation -> Output Citation Validation.
"""

import logging
import time
from typing import Dict, List, Optional, Tuple

from qdrant_client import QdrantClient

from agents.orchestrator.state import AgentOutput, OrchestratorState
from agents.rights_agent.prompts import (
    RIGHTS_EXPLAINER_SYSTEM,
    RIGHTS_EXPLAINER_USER_TEMPLATE,
    RIGHTS_SAFEGUARD_FALLBACK,
)
from core.config import get_settings
from db.qdrant_client import get_qdrant_client
from services.rag.embedder import BGEM3Embedder

logger = logging.getLogger(__name__)

# Minimum similarity score required to consider a retrieval match confident
CONFIDENCE_SCORE_THRESHOLD: float = 0.25


class RightsAgent:
    """
    Rights Explainer Specialist Agent powered by Qdrant + BGE-M3 RAG.
    """

    def __init__(
        self,
        qdrant_client: Optional[QdrantClient] = None,
        embedder: Optional[BGEM3Embedder] = None,
        collection_name: Optional[str] = None,
    ):
        settings = get_settings()
        self.qdrant_client = qdrant_client or get_qdrant_client()
        self.embedder = embedder or BGEM3Embedder()
        self.collection_name = collection_name or settings.QDRANT_COLLECTION_NAME

    def retrieve_relevant_chunks(
        self, query: str, top_k: int = 3
    ) -> List[Tuple[Dict, float]]:
        """
        Embeds the query via BGE-M3 and searches Qdrant for matching legal chunks.
        Returns a list of tuples: (payload_dict, score_float).
        """
        try:
            query_vector = self.embedder.embed_query(query)

            # qdrant-client 1.19+ uses query_points(); older versions used search()
            if hasattr(self.qdrant_client, "query_points"):
                response = self.qdrant_client.query_points(
                    collection_name=self.collection_name,
                    query=query_vector,
                    limit=top_k,
                )
                search_results = response.points
            elif hasattr(self.qdrant_client, "search"):
                search_results = self.qdrant_client.search(
                    collection_name=self.collection_name,
                    query_vector=query_vector,
                    limit=top_k,
                )
            else:
                logger.error("QdrantClient has neither 'query_points' nor 'search' method.")
                return []

            results = []
            for hit in search_results:
                payload = getattr(hit, "payload", {}) or {}
                score = getattr(hit, "score", 0.0)
                results.append((payload, score))

            logger.info(
                "Qdrant retrieval complete for query",
                extra={"query_len": len(query), "num_results": len(results)},
            )
            return results

        except Exception as exc:
            logger.error("Error retrieving chunks from Qdrant: %s", exc, exc_info=True)
            return []

    async def explain_rights(self, query: str) -> Tuple[str, List[str], str]:
        """
        Main execution flow:
        1. Retrieve chunks from Qdrant.
        2. Evaluate confidence score against threshold.
        3. If low confidence -> return honest safeguard fallback.
        4. If confident -> draft plain-language response.
        5. Output validation check -> enforce citation presence.

        Returns (response_text, list_of_citations, status_string).
        """
        retrieved = self.retrieve_relevant_chunks(query, top_k=3)

        # Filter chunks meeting the confidence score threshold
        confident_chunks = [
            payload for payload, score in retrieved if score >= CONFIDENCE_SCORE_THRESHOLD
        ]

        # ── Safeguard: Refuse unverified answers if no confident match ───────
        if not confident_chunks:
            logger.warning("No confident legal chunks retrieved for query: '%s'", query)
            return RIGHTS_SAFEGUARD_FALLBACK, [], "no_confident_match"

        # Format context for LLM prompt
        context_blocks = []
        valid_citations = []
        for idx, chunk in enumerate(confident_chunks, 1):
            citation = chunk.get("citation") or f"{chunk.get('act_name', 'Legal Act')} {chunk.get('section', '')}"
            valid_citations.append(citation)
            block = (
                f"[Chunk {idx}]\n"
                f"Topic: {chunk.get('topic', '')}\n"
                f"Act & Section: {chunk.get('act_name', '')} {chunk.get('section', '')}\n"
                f"Title: {chunk.get('title', '')}\n"
                f"Content: {chunk.get('content', '')}\n"
                f"Citation: {citation}\n"
            )
            context_blocks.append(block)

        context_str = "\n".join(context_blocks)

        # ── Call LLM to draft answer ──────────────────────────────────────────
        draft_response = await self._generate_answer(query, context_str, confident_chunks)

        # ── Minimal Output Check: Verify presence of real citation reference ──
        validated_response = self._validate_and_attach_citation(draft_response, valid_citations)

        return validated_response, valid_citations, "ok"

    async def _generate_answer(self, query: str, context_str: str, chunks: List[Dict]) -> str:
        """Calls LLM or falls back to template synthesis if API key missing."""
        from core.config import get_settings
        settings = get_settings()

        api_key = settings.GEMINI_API_KEY or settings.OPENAI_API_KEY
        if not api_key or api_key.startswith("sk-replace"):
            primary = chunks[0]
            citation = primary.get("citation", "Legal Knowledge Base")
            return (
                f"Based on Indian law regarding **{primary.get('topic', 'Citizen Rights')}**:\n\n"
                f"{primary.get('content', '')}\n\n"
                f"**Key Provision:** {primary.get('act_name', '')} ({primary.get('section', '')})\n\n"
                f"[Source: {citation}]"
            )

        try:
            model_name = settings.GEMINI_MODEL_DEV if settings.GEMINI_API_KEY else settings.OPENAI_MODEL_DEV
            from google import genai
            client = genai.Client(api_key=api_key)

            prompt = f"{RIGHTS_EXPLAINER_SYSTEM}\n\n{RIGHTS_EXPLAINER_USER_TEMPLATE.format(query=query, context=context_str)}"

            res = await client.aio.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            return res.text.strip() if res.text else ""

        except Exception as exc:
            logger.error("LLM call failed in RightsAgent: %s. Using template synthesis.", exc)
            primary = chunks[0]
            citation = primary.get("citation", "Legal Knowledge Base")
            return (
                f"Based on Indian law regarding **{primary.get('topic', 'Citizen Rights')}**:\n\n"
                f"{primary.get('content', '')}\n\n"
                f"[Source: {citation}]"
            )

    def _validate_and_attach_citation(self, draft: str, valid_citations: List[str]) -> str:
        """
        Minimal Output Check:
        Verifies that the generated response contains a reference to at least one
        of the retrieved valid citations. If missing, appends the primary citation.
        """
        if not valid_citations:
            return draft

        # Check if any valid citation appears in the draft
        has_citation = any(cit.lower() in draft.lower() for cit in valid_citations)

        if not has_citation:
            primary_citation = valid_citations[0]
            logger.warning(
                "Minimal output check: Draft answer lacked citation. Attaching primary citation: '%s'",
                primary_citation,
            )
            draft = f"{draft}\n\n[Source: {primary_citation}]"

        return draft


# ── Global RightsAgent instance ───────────────────────────────────────────────
_rights_agent_instance: Optional[RightsAgent] = None


def get_rights_agent() -> RightsAgent:
    """Returns singleton instance of RightsAgent."""
    global _rights_agent_instance
    if _rights_agent_instance is None:
        _rights_agent_instance = RightsAgent()
    return _rights_agent_instance


async def rights_agent_node(state: OrchestratorState) -> Dict:
    """
    LangGraph node function for Rights Explainer Agent.
    Called by orchestrator specialist_node when intent == AgentIntent.RIGHTS.
    """
    query = state["query"]
    t_start = time.perf_counter()

    agent = get_rights_agent()
    response_text, citations, status = await agent.explain_rights(query)

    retrieved = agent.retrieve_relevant_chunks(query, top_k=3)

    verification_status = "unverified"

    for payload, score in retrieved:
        if score >= CONFIDENCE_SCORE_THRESHOLD:
            verification_status = payload.get(
                "verification_status",
                "unverified"
            )
            break

    from core.config import get_settings
    llm_calls = 1 if (get_settings().OPENAI_API_KEY and status == "ok") else 0

    elapsed_ms = int((time.perf_counter() - t_start) * 1000)

    output_record: AgentOutput = {
        "intent": "rights",
        "status": "ok" if status == "ok" else "error",
        "output": response_text,
        "metadata": {
            "latency_ms": elapsed_ms,
            "citations": citations,
            "verification_status": verification_status,
            "agent": "RightsExplainerAgent",
            "model": "gpt-4o-mini / BGE-M3",
        },
    }

    return {
        "scratchpad": [output_record],
        "llm_calls_used": llm_calls,
    }
