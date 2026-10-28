"""
=============================================================================
LEXIS — Scam Pattern Ingestion Pipeline (Module 8)
=============================================================================

PURPOSE
-------
Reads the curated scam_seed.json dataset, embeds each pattern's description
and keywords using the BGE-M3 pipeline (reused from Module 5), indexes the
vectors into a dedicated Qdrant collection (`scam_patterns`), and upserts the
full pattern records into the MongoDB `scam_patterns` collection.

WHY TWO STORES (QDRANT + MONGODB)?
-----------------------------------
  - Qdrant stores the embedding vectors + pattern ID only.
    It is used purely for SEMANTIC SIMILARITY SEARCH.
  - MongoDB stores the FULL pattern record (legal_reality, recommended_action,
    reporting_channels, source_ref, etc.).
    It is the AUTHORITATIVE SOURCE for alert content.

  Alert generation flow:
    Citizen query
      → embed → Qdrant search → matched pattern ID
      → MongoDB lookup by ID → return verified DB record
      → present legal_reality / recommended_action to citizen

  This ensures NO LLM can fabricate alert content: every field shown to the
  citizen is fetched directly from the admin-curated MongoDB document.

SEED DATASET NOTICE
--------------------
This seed JSON (17 patterns) is meant to be expanded by an admin via the
Admin Panel (Module 12).  Patterns should only be added/modified after
verification against official Indian law, MHA, UIDAI, RBI, or SEBI sources.
Each pattern's `source_ref` field must document the authoritative reference.
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

# Default seed file path (relative to backend root)
DEFAULT_SCAM_SEED_FILE = (
    Path(__file__).parent.parent.parent / "data" / "scam_patterns" / "scam_seed.json"
)

# Qdrant collection name for scam patterns (separate from legal_knowledge_base)
SCAM_COLLECTION_NAME = "scam_patterns"


class ScamIngestionPipeline:
    """
    Ingestion pipeline for the scam pattern seed dataset.

    On each run it:
      1. Loads the seed JSON.
      2. Embeds each pattern using BGE-M3 (description + keywords joined).
      3. Upserts vectors into Qdrant `scam_patterns` collection.
      4. Upserts the full pattern record into MongoDB `scam_patterns` collection.

    The pipeline is idempotent: running it twice on the same data
    overwrites existing vectors with the same IDs (upsert, not append).
    """

    def __init__(
        self,
        qdrant_client: Optional[QdrantClient] = None,
        embedder: Optional[BGEM3Embedder] = None,
        mongo_db=None,
    ):
        self.qdrant_client = qdrant_client or get_qdrant_client()
        self.embedder = embedder or BGEM3Embedder()
        self.mongo_db = mongo_db  # Motor async database object (None in sync seeding mode)
        self.collection_name = SCAM_COLLECTION_NAME

    def ingest_file(self, json_file_path: Path, recreate: bool = False) -> int:
        """
        Ingest scam patterns from a seed JSON file into Qdrant.
        Returns the count of successfully ingested patterns.

        NOTE: MongoDB upsert is performed via the async variant `ingest_file_async()`
        during application startup. This sync method handles Qdrant only,
        which is fine because Qdrant's Python client is synchronous.
        """
        if not json_file_path.exists():
            raise FileNotFoundError(f"Scam seed file not found: {json_file_path}")

        logger.info("Loading scam seed dataset from: %s", json_file_path)
        with open(json_file_path, "r", encoding="utf-8") as f:
            patterns: List[Dict] = json.load(f)

        if not patterns:
            logger.warning("No scam patterns found in seed file: %s", json_file_path)
            return 0

        # Ensure Qdrant collection exists (384-dim, Cosine distance)
        init_qdrant_collection(
            self.qdrant_client,
            self.collection_name,
            vector_size=384,
            recreate=recreate,
        )

        # Build embedding texts: combine description + keywords for richer signal
        texts_to_embed = []
        for p in patterns:
            kw_str = ", ".join(p.get("keywords", []))
            embed_text = (
                f"Scam: {p.get('name', '')}\n"
                f"Description: {p.get('description', '')}\n"
                f"Keywords: {kw_str}"
            )
            texts_to_embed.append(embed_text)

        logger.info(
            "Generating BGE-M3 embeddings for %d scam patterns...", len(texts_to_embed)
        )
        embeddings = self.embedder.embed_texts(texts_to_embed)

        # Build Qdrant points: store only pattern ID + name in payload (full data in Mongo)
        points = []
        for idx, (pattern, vector) in enumerate(zip(patterns, embeddings)):
            points.append(
                rest_models.PointStruct(
                    id=idx + 1,
                    vector=vector,
                    payload={
                        "pattern_id": pattern["id"],
                        "name": pattern.get("name", ""),
                        "severity": pattern.get("severity", "MEDIUM"),
                        # sequence index for secondary ordering
                        "seq": idx + 1,
                    },
                )
            )

        logger.info(
            "Upserting %d scam pattern vectors into Qdrant '%s'...",
            len(points),
            self.collection_name,
        )
        self.qdrant_client.upsert(collection_name=self.collection_name, points=points)

        logger.info(
            "Successfully ingested %d scam patterns into Qdrant '%s'",
            len(points),
            self.collection_name,
        )
        return len(points)

    def get_patterns_from_file(self, json_file_path: Path) -> List[Dict]:
        """Helper: load and return raw pattern list from JSON."""
        with open(json_file_path, "r", encoding="utf-8") as f:
            return json.load(f)


async def seed_scam_patterns_mongo(mongo_db, json_file_path: Path = None) -> int:
    """
    Async helper: upserts all scam patterns into MongoDB `scam_patterns` collection.
    Called during application startup via lifespan (if mongo_db is available).

    Each document is keyed by the pattern `id` field (e.g., "SCAM_001").
    This is the authoritative source used by ScamDetectionAgent for alert content.
    """
    if json_file_path is None:
        json_file_path = DEFAULT_SCAM_SEED_FILE

    if not json_file_path.exists():
        logger.warning("Scam seed file not found — MongoDB seeding skipped: %s", json_file_path)
        return 0

    with open(json_file_path, "r", encoding="utf-8") as f:
        patterns: List[Dict] = json.load(f)

    collection = mongo_db["scam_patterns"]
    count = 0
    from datetime import datetime, timezone

    now_iso = datetime.now(timezone.utc).isoformat()

    for pattern in patterns:
        doc = dict(pattern)
        doc.setdefault("status", "verified")
        doc.setdefault("is_active", True)
        doc.setdefault("report_count", 1)
        doc.setdefault("version", "1.0")
        doc.setdefault("provenance", "seed")
        doc.setdefault("first_observed", now_iso)
        doc.setdefault("last_observed", now_iso)
        doc.setdefault("created_at", now_iso)
        doc.setdefault("updated_at", now_iso)
        if "category" not in doc:
            p_name = doc.get("name", "").lower()
            if "arrest" in p_name:
                doc["category"] = "Digital Arrest"
            elif any(w in p_name for w in ["cbi", "officer", "police", "customs", "courier"]):
                doc["category"] = "Impersonation"
            elif any(w in p_name for w in ["upi", "qr", "payment"]):
                doc["category"] = "Payment/UPI"
            elif any(w in p_name for w in ["kyc", "aadhaar", "sim"]):
                doc["category"] = "KYC/Identity"
            elif "job" in p_name:
                doc["category"] = "Job/Employment"
            elif any(w in p_name for w in ["crypto", "invest", "stock"]):
                doc["category"] = "Investment"
            else:
                doc["category"] = "Other"

        await collection.update_one(
            {"id": pattern["id"]},
            {"$set": doc},
            upsert=True,
        )
        count += 1

    logger.info("Upserted %d scam patterns into MongoDB 'scam_patterns' collection.", count)
    return count


def seed_scam_knowledge_base(
    qdrant_client: Optional[QdrantClient] = None,
    force_recreate: bool = False,
    test_mode: bool = False,
    json_file_path: Optional[Path] = None,
) -> int:
    """
    Convenience function to seed the scam pattern dataset into Qdrant.
    Used at application startup and in test fixtures.
    """
    embedder = BGEM3Embedder(test_mode=test_mode)
    pipeline = ScamIngestionPipeline(qdrant_client=qdrant_client, embedder=embedder)
    seed_file = json_file_path or DEFAULT_SCAM_SEED_FILE
    return pipeline.ingest_file(seed_file, recreate=force_recreate)


if __name__ == "__main__":
    import asyncio
    logging.basicConfig(level=logging.INFO)
    print("Running LEXIS Scam Pattern Knowledge Base Ingestion...")
    count = seed_scam_knowledge_base(force_recreate=True)
    print(f"Done! Seeded {count} scam patterns into Qdrant 'scam_patterns' collection.")
    print("NOTE: MongoDB seeding requires a running Motor connection (done via app startup).")
