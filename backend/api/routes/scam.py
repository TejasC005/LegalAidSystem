"""
=============================================================================
LEXIS — Scam Detection API Routes (Module 8)
=============================================================================

Endpoints:
  POST /api/v1/scam/check    — Submit a description and receive a scam alert
  GET  /api/v1/scam/patterns — List all seeded scam pattern names

SECURITY
--------
All endpoints require JWT authentication (get_current_user dependency).
Both anonymous and authenticated users can use scam detection (no Vault
needed — this is a safety feature available to all).

GROUNDING GUARANTEE
-------------------
Every response from POST /api/v1/scam/check either:
  a) Contains a ScamAlertCard whose ALL fields trace to a real MongoDB entry
     (identified by `db_id`, e.g., "SCAM_001").
  b) Contains a safe fallback message with no fabricated facts.

The `db_id` field in every matched response is the traceability key.
An admin can query `db.scam_patterns.find_one({"id": db_id})` to see
the exact source record that generated the alert.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from api.dependencies.auth import get_current_user
from db.database import get_database

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scam", tags=["Scam Detection"])


# =============================================================================
# Request / Response Schemas
# =============================================================================

class ScamCheckRequest(BaseModel):
    """Request body for POST /api/v1/scam/check."""

    description: str = Field(
        ...,
        min_length=10,
        max_length=2000,
        description=(
            "Describe the suspicious situation, call, message, or demand "
            "in as much detail as possible. Min 10 chars, max 2000 chars."
        ),
        examples=["Someone called claiming to be from CBI and said I am under digital arrest. They asked me to stay on video call and pay 50000."],
    )


class ScamAlertCard(BaseModel):
    """
    Structured alert card returned when a scam pattern is matched.
    Every field is sourced from the MongoDB `scam_patterns` collection.
    The `db_id` field provides full traceability to the source DB record.
    """
    matched: bool
    db_id: Optional[str] = None           # e.g., "SCAM_001" — traceability
    pattern_name: Optional[str] = None
    severity: Optional[str] = None        # "CRITICAL" | "HIGH" | "MEDIUM"
    match_method: Optional[str] = None    # "keyword" | "semantic" | "none"
    confidence_score: Optional[float] = None
    description: Optional[str] = None
    legal_reality: Optional[str] = None
    recommended_action: Optional[str] = None
    reporting_channels: Optional[List[str]] = None
    source_ref: Optional[str] = None
    safe_fallback_message: Optional[str] = None
    checked_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class ScamCheckResponse(BaseModel):
    """Full response envelope for POST /api/v1/scam/check."""
    status: str                           # "matched" | "no_match" | "error"
    alert: ScamAlertCard
    message: str


class ScamPatternSummary(BaseModel):
    """Summary entry for GET /api/v1/scam/patterns."""
    id: str
    name: str
    severity: str
    keywords: List[str]


class ScamPatternsResponse(BaseModel):
    """Response for GET /api/v1/scam/patterns."""
    total: int
    patterns: List[ScamPatternSummary]


# =============================================================================
# POST /api/v1/scam/check — Main detection endpoint
# =============================================================================

@router.post(
    "/check",
    response_model=ScamCheckResponse,
    summary="Check a description against the scam pattern database",
    description=(
        "Submit a natural-language description of a suspicious situation. "
        "The agent uses a keyword fast-path + BGE-M3 semantic search to match "
        "against the curated scam pattern database. Returns a grounded alert card "
        "with legal reality and recommended action sourced from the DB — "
        "no LLM-generated content in the alert fields."
    ),
    status_code=status.HTTP_200_OK,
)
async def check_scam(
    payload: ScamCheckRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Run the scam detection pipeline against the citizen's description.

    Returns a ScamAlertCard with:
      - `matched=True` + full alert details (all from DB) if a pattern is found.
      - `matched=False` + safe_fallback_message if no confident match.

    The `db_id` in a matched response is the traceability key to the source
    MongoDB document in the `scam_patterns` collection.
    """
    from agents.scam_detection.agent import get_scam_agent

    description = payload.description.strip()
    user_id = current_user.get("sub", "anonymous")

    logger.info(
        "Scam check request",
        extra={"user_id": user_id, "description_len": len(description)},
    )

    try:
        # Get the scam agent, providing MongoDB for production DB grounding
        agent = get_scam_agent(mongo_db=db)
        result = await agent.check_scam(description)

        if result.matched:
            alert = ScamAlertCard(
                matched=True,
                db_id=result.db_id,
                pattern_name=result.pattern_name,
                severity=result.severity,
                match_method=result.match_method,
                confidence_score=round(result.confidence_score, 4),
                description=result.description,
                legal_reality=result.legal_reality,
                recommended_action=result.recommended_action,
                reporting_channels=result.reporting_channels,
                source_ref=result.source_ref,
            )
            response_status = "matched"
            message = (
                f"⚠️ Recognised scam: '{result.pattern_name}' (Severity: {result.severity}). "
                f"Read the alert carefully and follow the recommended steps."
            )
        else:
            alert = ScamAlertCard(
                matched=False,
                match_method="none",
                safe_fallback_message=result.safe_fallback_message,
            )
            response_status = "no_match"
            message = (
                "This description did not match a known scam pattern in our database. "
                "If you suspect fraud, call 1930 (National Cyber Helpline) immediately."
            )

        logger.info(
            "Scam check completed",
            extra={
                "user_id": user_id,
                "status": response_status,
                "db_id": result.db_id if result.matched else None,
                "match_method": result.match_method,
            },
        )

        return ScamCheckResponse(status=response_status, alert=alert, message=message)

    except Exception as exc:
        logger.error(
            "Scam check failed with exception",
            extra={"user_id": user_id, "error": str(exc)},
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Scam detection service encountered an error. Please try again.",
        )


# =============================================================================
# GET /api/v1/scam/patterns — List all seeded patterns (admin/user view)
# =============================================================================

@router.get(
    "/patterns",
    response_model=ScamPatternsResponse,
    summary="List all seeded scam patterns",
    description=(
        "Returns the names, severities, and keywords of all scam patterns "
        "currently in the database. Useful for admin verification that seeding "
        "completed successfully, and for users to understand what LEXIS detects."
    ),
    status_code=status.HTTP_200_OK,
)
async def list_scam_patterns(
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    """
    List all scam patterns from MongoDB.

    Falls back to the in-memory seed cache if MongoDB is unavailable
    (useful in development without a running database).
    """
    import json
    from pathlib import Path

    patterns_data: List[Dict[str, Any]] = []

    # Try MongoDB first
    try:
        cursor = db["scam_patterns"].find({}, {"_id": 0, "id": 1, "name": 1, "severity": 1, "keywords": 1})
        patterns_data = await cursor.to_list(length=100)
    except Exception as exc:
        logger.warning("Could not read scam patterns from MongoDB (%s). Using seed file.", exc)

    # Fallback to seed file
    if not patterns_data:
        seed_path = (
            Path(__file__).parent.parent.parent.parent
            / "data" / "scam_patterns" / "scam_seed.json"
        )
        try:
            with open(seed_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            patterns_data = [
                {"id": p["id"], "name": p["name"], "severity": p["severity"], "keywords": p.get("keywords", [])}
                for p in raw
            ]
        except Exception as exc2:
            logger.error("Could not load scam seed file: %s", exc2)
            patterns_data = []

    summaries = [
        ScamPatternSummary(
            id=p.get("id", ""),
            name=p.get("name", ""),
            severity=p.get("severity", "MEDIUM"),
            keywords=p.get("keywords", []),
        )
        for p in patterns_data
    ]

    return ScamPatternsResponse(total=len(summaries), patterns=summaries)
