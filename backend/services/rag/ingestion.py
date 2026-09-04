"""
=============================================================================
LEXIS — Legal Knowledge Base Embedding & Ingestion Pipeline (Module 5)
=============================================================================
Reads legal documents/chunks, embeds them using BGE-M3 (BGEM3Embedder),
and indexes them into the Qdrant vector database collection (`legal_knowledge_base`).

This pipeline is decoupled from agent code so new legal documents can be added
to the knowledge base at any time without modifying agent logic.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from qdrant_client import QdrantClient
from qdrant_client.http import models as rest_models

from core.config import get_settings
from db.qdrant_client import get_qdrant_client, init_qdrant_collection
from services.rag.embedder import BGEM3Embedder

logger = logging.getLogger(__name__)

# Default seed dataset location relative to backend root
DEFAULT_SEED_FILE = Path(__file__).parent.parent.parent / "data" / "knowledge_base" / "rights_seed.json"


class LegalIngestionPipeline:
    """
    Ingestion pipeline for legal knowledge base documents.
    """

    def __init__(
        self,
        client: Optional[QdrantClient] = None,
        embedder: Optional[BGEM3Embedder] = None,
        collection_name: Optional[str] = None,
    ):
        settings = get_settings()
        self.client = client or get_qdrant_client()
        self.embedder = embedder or BGEM3Embedder()
        self.collection_name = collection_name or settings.QDRANT_COLLECTION_NAME

    def ingest_file(self, json_file_path: Path, recreate: bool = False) -> int:
        """
        Ingests a JSON array of legal document chunks into Qdrant.
        Returns the count of successfully ingested records.
        """
        if not json_file_path.exists():
            raise FileNotFoundError(f"Seed file not found at: {json_file_path}")

        logger.info("Loading legal seed dataset from: %s", json_file_path)
        with open(json_file_path, "r", encoding="utf-8") as f:
            records: List[Dict] = json.load(f)

        if not records:
            logger.warning("No records found in seed file: %s", json_file_path)
            return 0

        # Initialize Qdrant collection (384-dim, Cosine distance)
        init_qdrant_collection(self.client, self.collection_name, vector_size=384, recreate=recreate)

        # Extract text content for embedding
        texts_to_embed = [
            f"{r.get('topic', '')}: {r.get('title', '')}\nAct: {r.get('act_name', '')} {r.get('section', '')}\n{r.get('content', '')}"
            for r in records
        ]

        logger.info("Generating BGE-M3 embeddings for %d legal chunks...", len(texts_to_embed))
        embeddings = self.embedder.embed_texts(texts_to_embed)

        points = []
        for idx, (record, vector) in enumerate(zip(records, embeddings)):
            chunk_id = record.get("id", f"chunk_{idx+1}")

            payload = {
                "chunk_id": chunk_id,
                "topic": record.get("topic", ""),
                "act_name": record.get("act_name", ""),
                "section": record.get("section", ""),
                "title": record.get("title", ""),
                "content": record.get("content", ""),
                "source_doc": record.get("source_doc", ""),
                "citation": record.get("citation", ""),
            }

            # Use integer or string ID for Qdrant point struct
            points.append(
                rest_models.PointStruct(
                    id=idx + 1,
                    vector=vector,
                    payload=payload,
                )
            )

        logger.info("Upserting %d points into Qdrant collection '%s'...", len(points), self.collection_name)
        self.client.upsert(
            collection_name=self.collection_name,
            points=points,
        )

        logger.info("Successfully ingested %d legal chunks into '%s'", len(points), self.collection_name)
        return len(points)


def seed_starter_knowledge_base(
    client: Optional[QdrantClient] = None,
    force_recreate: bool = False,
    test_mode: bool = False,
) -> int:
    """
    Helper function to seed the starter legal dataset into Qdrant.
    Can be called on application boot or in test fixtures.
    """
    embedder = BGEM3Embedder(test_mode=test_mode)
    pipeline = LegalIngestionPipeline(client=client, embedder=embedder)
    return pipeline.ingest_file(DEFAULT_SEED_FILE, recreate=force_recreate)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Running LEXIS Legal Knowledge Base Ingestion...")
    count = seed_starter_knowledge_base(force_recreate=True)
    print(f"Done! Seeded {count} legal chunks into Qdrant.")
