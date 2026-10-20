"""
=============================================================================
LEXIS — Admin Scam Intelligence Knowledge Base API Routes
=============================================================================
Protected administrative endpoints for:
  - Curating, updating, activating, and deactivating scam patterns
  - Review queue moderation (approve, reject, merge citizen-discovered candidates)
  - Intelligence analytics and detection metrics
  - Citizen submission auditing

All endpoints require role='admin' via `require_role(["admin"])`.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from api.dependencies.auth import get_current_user, require_role
from db.database import get_database
from models.scam_intelligence import (
    CandidateApproveRequest,
    CandidateMergeRequest,
    CandidateRejectRequest,
    ScamAnalyticsResponse,
    ScamPatternCreateRequest,
    ScamPatternUpdateRequest,
)
from services.scam.intelligence_service import ScamIntelligenceService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/scam-intelligence", tags=["Admin Scam Intelligence"])

admin_guard = Depends(require_role(["admin"]))


# ─────────────────────────────────────────────────────────────────────────────
# 1. Analytics Endpoint
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/analytics",
    response_model=ScamAnalyticsResponse,
    dependencies=[admin_guard],
    summary="Get Scam Intelligence Overview Analytics",
)
async def get_scam_analytics(db=Depends(get_database)):
    """
    Returns platform-wide metrics on verified patterns, pending candidates,
    rejections, merges, and citizen detection outcomes.
    """
    service = ScamIntelligenceService(mongo_db=db)
    return await service.get_analytics()


# ─────────────────────────────────────────────────────────────────────────────
# 2. Pattern Management Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/patterns",
    dependencies=[admin_guard],
    summary="List Curated Scam Patterns",
)
async def list_patterns(
    q: Optional[str] = Query(None, description="Search term in name, description, keywords"),
    category: Optional[str] = Query(None, description="Filter by category"),
    status: Optional[str] = Query(None, description="Filter by status (verified, deactivated)"),
    severity: Optional[str] = Query(None, description="Filter by severity (CRITICAL, HIGH, MEDIUM)"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db=Depends(get_database),
):
    """
    Lists scam intelligence patterns with search, category/severity filtering, and pagination.
    """
    service = ScamIntelligenceService(mongo_db=db)
    total, patterns = await service.list_patterns(
        query=q,
        category=category,
        status=status,
        severity=severity,
        is_active=is_active,
        skip=skip,
        limit=limit,
    )
    return {
        "total": total,
        "patterns": patterns,
        "skip": skip,
        "limit": limit,
    }


@router.get(
    "/patterns/{pattern_id}",
    dependencies=[admin_guard],
    summary="Get Scam Pattern Details",
)
async def get_pattern(pattern_id: str, db=Depends(get_database)):
    """
    Fetches complete record of a scam pattern including legal reality, indicators, and version.
    """
    service = ScamIntelligenceService(mongo_db=db)
    pattern = await service.get_pattern(pattern_id)
    if not pattern:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scam pattern '{pattern_id}' not found.",
        )
    return pattern


@router.post(
    "/patterns",
    dependencies=[admin_guard],
    status_code=status.HTTP_201_CREATED,
    summary="Create or Curate a Scam Intelligence Pattern",
)
async def create_pattern(
    request: ScamPatternCreateRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Creates an admin-curated scam pattern and synchronizes with vector index & detection agent.
    """
    reviewer_id = current_user.get("sub", "admin")
    service = ScamIntelligenceService(mongo_db=db)
    created = await service.create_pattern(request, reviewer_id=reviewer_id)
    return {
        "message": "Scam pattern created and synchronized successfully.",
        "pattern": created,
    }


@router.patch(
    "/patterns/{pattern_id}",
    dependencies=[admin_guard],
    summary="Update Scam Intelligence Pattern",
)
async def update_pattern(
    pattern_id: str,
    request: ScamPatternUpdateRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Updates an existing scam pattern, increments version, and updates Qdrant & agent cache.
    """
    reviewer_id = current_user.get("sub", "admin")
    service = ScamIntelligenceService(mongo_db=db)
    updated = await service.update_pattern(pattern_id, request, reviewer_id=reviewer_id)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scam pattern '{pattern_id}' not found.",
        )
    return {
        "message": "Scam pattern updated successfully.",
        "pattern": updated,
    }


@router.post(
    "/patterns/{pattern_id}/activate",
    dependencies=[admin_guard],
    summary="Activate Scam Pattern",
)
async def activate_pattern(
    pattern_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Activates pattern and indexes into Qdrant for active citizen detection.
    """
    reviewer_id = current_user.get("sub", "admin")
    service = ScamIntelligenceService(mongo_db=db)
    success = await service.activate_pattern(pattern_id, reviewer_id=reviewer_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scam pattern '{pattern_id}' not found.",
        )
    return {
        "message": f"Scam pattern '{pattern_id}' activated and indexed into vector search.",
        "pattern_id": pattern_id,
        "is_active": True,
    }


@router.post(
    "/patterns/{pattern_id}/deactivate",
    dependencies=[admin_guard],
    summary="Deactivate Scam Pattern",
)
async def deactivate_pattern(
    pattern_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Deactivates pattern, excluding it from active matching without deleting intelligence data.
    """
    reviewer_id = current_user.get("sub", "admin")
    service = ScamIntelligenceService(mongo_db=db)
    success = await service.deactivate_pattern(pattern_id, reviewer_id=reviewer_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scam pattern '{pattern_id}' not found.",
        )
    return {
        "message": f"Scam pattern '{pattern_id}' deactivated and removed from active detection.",
        "pattern_id": pattern_id,
        "is_active": False,
    }


@router.delete(
    "/patterns/{pattern_id}",
    dependencies=[admin_guard],
    summary="Delete Scam Pattern",
)
async def delete_pattern(pattern_id: str, db=Depends(get_database)):
    """
    Permanently deletes a scam pattern and its vectors.
    """
    service = ScamIntelligenceService(mongo_db=db)
    success = await service.delete_pattern(pattern_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scam pattern '{pattern_id}' not found.",
        )
    return {
        "message": f"Scam pattern '{pattern_id}' deleted successfully.",
        "pattern_id": pattern_id,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3. Review Queue Endpoints (Citizen Candidate Verification)
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/review-queue",
    dependencies=[admin_guard],
    summary="List Candidate Reports in Review Queue",
)
async def list_review_queue(
    status_filter: Optional[str] = Query("candidate", alias="status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db=Depends(get_database),
):
    """
    Lists pending candidate records waiting for admin review.
    """
    service = ScamIntelligenceService(mongo_db=db)
    total, candidates = await service.list_review_queue(status=status_filter or "candidate", skip=skip, limit=limit)
    return {
        "total": total,
        "candidates": candidates,
        "skip": skip,
        "limit": limit,
    }


@router.post(
    "/review-queue/{candidate_id}/approve",
    dependencies=[admin_guard],
    summary="Approve Candidate into Verified Intelligence",
)
async def approve_candidate(
    candidate_id: str,
    request: CandidateApproveRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Promotes candidate report into a trusted verified scam pattern.
    Indexes vector into Qdrant and updates agent detection cache.
    """
    reviewer_id = current_user.get("sub", "admin")
    service = ScamIntelligenceService(mongo_db=db)
    created_pattern = await service.approve_candidate(candidate_id, request, reviewer_id=reviewer_id)
    if not created_pattern:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Candidate '{candidate_id}' not found in review queue.",
        )
    return {
        "message": f"Candidate '{candidate_id}' successfully approved and added to pattern library.",
        "pattern": created_pattern,
    }


@router.post(
    "/review-queue/{candidate_id}/reject",
    dependencies=[admin_guard],
    summary="Reject Candidate Report",
)
async def reject_candidate(
    candidate_id: str,
    request: CandidateRejectRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Rejects candidate report with reviewer rationale.
    """
    reviewer_id = current_user.get("sub", "admin")
    service = ScamIntelligenceService(mongo_db=db)
    success = await service.reject_candidate(candidate_id, request, reviewer_id=reviewer_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Candidate '{candidate_id}' not found.",
        )
    return {
        "message": f"Candidate '{candidate_id}' marked as rejected.",
        "candidate_id": candidate_id,
    }


@router.post(
    "/review-queue/{candidate_id}/merge",
    dependencies=[admin_guard],
    summary="Merge Candidate into Existing Verified Pattern",
)
async def merge_candidate(
    candidate_id: str,
    request: CandidateMergeRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Merges duplicate candidate into an existing pattern, updating report counts and identifiers.
    """
    reviewer_id = current_user.get("sub", "admin")
    service = ScamIntelligenceService(mongo_db=db)
    success = await service.merge_candidate(candidate_id, request, reviewer_id=reviewer_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Candidate '{candidate_id}' or target pattern '{request.target_pattern_id}' not found.",
        )
    return {
        "message": f"Candidate '{candidate_id}' merged into pattern '{request.target_pattern_id}'.",
        "candidate_id": candidate_id,
        "target_pattern_id": request.target_pattern_id,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 4. Submission Audit Logs
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/submissions",
    dependencies=[admin_guard],
    summary="List Citizen Submission Logs",
)
async def list_submissions(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db=Depends(get_database),
):
    """
    Lists citizen upload and analysis audit logs.
    """
    col = db["scam_submissions"]
    total = await col.count_documents({})
    cursor = col.find({}).sort("created_at", -1).skip(skip).limit(limit)

    submissions = []
    async for s in cursor:
        s["_id"] = str(s.get("_id", ""))
        submissions.append(s)

    return {
        "total": total,
        "submissions": submissions,
        "skip": skip,
        "limit": limit,
    }
