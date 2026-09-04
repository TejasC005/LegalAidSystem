"""
=============================================================================
LEXIS Filing Guide — MongoDB Seed Ingestion (Module 9)
=============================================================================

Reads the filing_seed.json authoritative data file and upserts each entry
into the MongoDB `filing_authorities` collection.

DESIGN: No Qdrant / vector store for this agent.
  - Unlike the Scam Detection Agent (which uses semantic search),
    Filing Guide uses structured exact-match lookup by doc_type.
  - There are only 3 document types (RTI, consumer_complaint, legal_notice).
  - Semantic matching is NOT used — a wrong authority recommendation is
    a real-world harm. Exact doc_type key → authority record is safe and
    deterministic. There is no "approximate filing authority".

NO-HALLUCINATION CONTRACT:
  Every entry in filing_seed.json contains only verified facts from:
    - Right to Information Act 2005
    - Consumer Protection Act 2019
    - Court Fees Act 1870
    - Official portals: rtionline.gov.in, edaakhil.nic.in, cic.gov.in
  Fields that could not be verified (e.g., state-specific court fees)
  are explicitly set to "needs_verification" — never to a plausible guess.
"""

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Seed file path ─────────────────────────────────────────────────────────────
SEED_FILE = Path(__file__).parent.parent.parent / "data" / "filing_authorities" / "filing_seed.json"


def load_filing_seed() -> list:
    """
    Loads and returns the parsed contents of filing_seed.json.
    Raises FileNotFoundError if the seed file is missing.
    """
    if not SEED_FILE.exists():
        raise FileNotFoundError(
            f"Filing authority seed file not found at {SEED_FILE}. "
            "Ensure backend/data/filing_authorities/filing_seed.json exists."
        )
    with open(SEED_FILE, "r", encoding="utf-8") as f:
        entries = json.load(f)
    logger.info("Loaded %d filing authority entries from seed file", len(entries))
    return entries


async def seed_filing_authorities(mongo_db, collection_name: str = "filing_authorities") -> int:
    """
    Upserts all filing authority entries from the seed file into MongoDB.

    Uses upsert by `doc_type` so re-running this on an already-populated
    collection is safe (idempotent — will update existing records, not duplicate).

    Args:
        mongo_db: AsyncIOMotorDatabase instance (from app.state)
        collection_name: MongoDB collection to upsert into

    Returns:
        Number of entries seeded/updated.
    """
    entries = load_filing_seed()
    collection = mongo_db[collection_name]

    count = 0
    for entry in entries:
        doc_type = entry.get("doc_type")
        if not doc_type:
            logger.warning("Skipping filing seed entry with missing doc_type: %s", entry.get("id"))
            continue

        await collection.update_one(
            {"doc_type": doc_type},
            {"$set": entry},
            upsert=True
        )
        count += 1
        logger.debug("Upserted filing authority for doc_type='%s' (id=%s)", doc_type, entry.get("id"))

    logger.info(
        "Filing authority seeding complete: %d/%d entries upserted into '%s'",
        count, len(entries), collection_name
    )
    return count
