"""
=============================================================================
LEXIS — Admin Panel API Routes (Module 12)
=============================================================================

WHAT THIS FILE DOES
-------------------
Provides administrative endpoints for platform analytics, user management,
and confirmation agent moderation reviews.

SECURITY & AUTHENTICATION
-------------------------
Every single route in this module is protected by `require_role(["admin"])`
from Module 2.  There is NO separate auth mechanism — re-using the existing
role guard dependency guarantees a single source of truth for authorization.

DATA INTEGRITY
--------------
All analytics metrics are calculated strictly from real MongoDB records in:
  1. `reflection_logs` collection (Module 11 self-correction logs)
  2. `users` collection (Module 2 user documents)

No mock/dummy analytics numbers are generated — empty/zero states are returned
honestly if no log entries exist yet.
"""

import logging
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from api.dependencies.auth import require_role
from db.database import get_database

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin Panel"])

# Centralized guard for all routes in this router
admin_guard = Depends(require_role(["admin"]))


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic Schemas for Admin API
# ─────────────────────────────────────────────────────────────────────────────

class AgentMetric(BaseModel):
    agent_id: str
    total_queries: int
    passed_queries: int
    failed_queries: int
    fallback_queries: int
    retry_count_total: int
    contradiction_count: int


class AnalyticsOverviewResponse(BaseModel):
    total_sessions_logged: int
    total_agent_evaluations: int
    pass_rate_percentage: float
    fail_rate_percentage: float
    fallback_rate_percentage: float
    total_retries: int
    total_contradictions: int
    agents_evaluated: List[str]


class UserAdminOut(BaseModel):
    id: str
    phone: Optional[str] = None
    email: Optional[str] = None
    role: str
    is_active: bool
    created_at: str


class UserStatusUpdateResponse(BaseModel):
    message: str
    user_id: str
    is_active: bool


class ModerationItem(BaseModel):
    session_id: str
    timestamp: str
    agents_checked: List[str]
    pass_fail: str
    retry_count: int
    rejection_reason: str
    contradiction_caught: Optional[str] = None
    query_length: int
    response_length: int


# ─────────────────────────────────────────────────────────────────────────────
# 1. Analytics Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/analytics/overview",
    response_model=AnalyticsOverviewResponse,
    dependencies=[admin_guard],
    summary="Overview Usage & Reflection Analytics",
)
async def get_analytics_overview(db: Any = Depends(get_database)):
    """
    Returns platform-wide agent reflection metrics aggregated directly from
    the real `reflection_logs` collection.
    """
    collection = db["reflection_logs"]
    
    total_sessions_logged = await collection.count_documents({})
    
    if total_sessions_logged == 0:
        return AnalyticsOverviewResponse(
            total_sessions_logged=0,
            total_agent_evaluations=0,
            pass_rate_percentage=0.0,
            fail_rate_percentage=0.0,
            fallback_rate_percentage=0.0,
            total_retries=0,
            total_contradictions=0,
            agents_evaluated=[],
        )

    pipeline = [
        {
            "$group": {
                "_id": None,
                "total_evaluations": {"$sum": 1},
                "passes": {
                    "$sum": {"$cond": [{"$eq": ["$pass_fail", "pass"]}, 1, 0]}
                },
                "fails": {
                    "$sum": {"$cond": [{"$eq": ["$pass_fail", "fail"]}, 1, 0]}
                },
                "fallbacks": {
                    "$sum": {"$cond": [{"$eq": ["$pass_fail", "fallback"]}, 1, 0]}
                },
                "total_retries": {"$sum": "$retry_count"},
                "total_contradictions": {
                    "$sum": {
                        "$cond": [
                            {"$ne": [{"$ifNull": ["$contradiction_caught", None]}, None]},
                            1,
                            0
                        ]
                    }
                },
            }
        }
    ]

    agg_results = await collection.aggregate(pipeline).to_list(length=1)
    if not agg_results:
        return AnalyticsOverviewResponse(
            total_sessions_logged=0,
            total_agent_evaluations=0,
            pass_rate_percentage=0.0,
            fail_rate_percentage=0.0,
            fallback_rate_percentage=0.0,
            total_retries=0,
            total_contradictions=0,
            agents_evaluated=[],
        )

    data = agg_results[0]
    total_evals = data.get("total_evaluations", 0)
    passes = data.get("passes", 0)
    fails = data.get("fails", 0)
    fallbacks = data.get("fallbacks", 0)

    pass_rate = round((passes / total_evals) * 100, 2) if total_evals > 0 else 0.0
    fail_rate = round((fails / total_evals) * 100, 2) if total_evals > 0 else 0.0
    fallback_rate = round((fallbacks / total_evals) * 100, 2) if total_evals > 0 else 0.0

    distinct_agents = await collection.distinct("agents_checked")

    return AnalyticsOverviewResponse(
        total_sessions_logged=total_sessions_logged,
        total_agent_evaluations=total_evals,
        pass_rate_percentage=pass_rate,
        fail_rate_percentage=fail_rate,
        fallback_rate_percentage=fallback_rate,
        total_retries=data.get("total_retries", 0),
        total_contradictions=data.get("total_contradictions", 0),
        agents_evaluated=[str(a) for a in distinct_agents if a],
    )


@router.get(
    "/analytics/agents",
    response_model=List[AgentMetric],
    dependencies=[admin_guard],
    summary="Per-Agent Analytics Breakdown",
)
async def get_agent_analytics(db: Any = Depends(get_database)):
    """
    Returns breakdown metrics for all 6 agents:
    rights, draft, analyze, scam, filing, vault.
    """
    ALL_AGENTS = ["rights", "draft", "analyze", "scam", "filing", "vault"]
    collection = db["reflection_logs"]

    pipeline = [
        {"$unwind": "$agents_checked"},
        {
            "$group": {
                "_id": "$agents_checked",
                "total_queries": {"$sum": 1},
                "passed_queries": {
                    "$sum": {"$cond": [{"$eq": ["$pass_fail", "pass"]}, 1, 0]}
                },
                "failed_queries": {
                    "$sum": {"$cond": [{"$eq": ["$pass_fail", "fail"]}, 1, 0]}
                },
                "fallback_queries": {
                    "$sum": {"$cond": [{"$eq": ["$pass_fail", "fallback"]}, 1, 0]}
                },
                "retry_count_total": {"$sum": "$retry_count"},
                "contradiction_count": {
                    "$sum": {
                        "$cond": [
                            {"$ne": [{"$ifNull": ["$contradiction_caught", None]}, None]},
                            1,
                            0
                        ]
                    }
                },
            }
        }
    ]

    results_map = {}
    async for doc in collection.aggregate(pipeline):
        agent_key = doc["_id"]
        results_map[agent_key] = AgentMetric(
            agent_id=agent_key,
            total_queries=doc.get("total_queries", 0),
            passed_queries=doc.get("passed_queries", 0),
            failed_queries=doc.get("failed_queries", 0),
            fallback_queries=doc.get("fallback_queries", 0),
            retry_count_total=doc.get("retry_count_total", 0),
            contradiction_count=doc.get("contradiction_count", 0),
        )

    # Ensure all 6 agents exist in output even if 0 activity
    agent_metrics = []
    for agent_id in ALL_AGENTS:
        if agent_id in results_map:
            agent_metrics.append(results_map[agent_id])
        else:
            agent_metrics.append(
                AgentMetric(
                    agent_id=agent_id,
                    total_queries=0,
                    passed_queries=0,
                    failed_queries=0,
                    fallback_queries=0,
                    retry_count_total=0,
                    contradiction_count=0,
                )
            )

    return agent_metrics


# ─────────────────────────────────────────────────────────────────────────────
# 2. User Management Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/users",
    response_model=List[UserAdminOut],
    dependencies=[admin_guard],
    summary="List All Users",
)
async def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Any = Depends(get_database),
):
    """
    Lists users registered in MongoDB with role and active status.
    """
    users_collection = db["users"]
    cursor = users_collection.find({}).skip(skip).limit(limit)

    users_list = []
    async for u in cursor:
        created_at_val = u.get("created_at")
        if isinstance(created_at_val, datetime):
            created_at_str = created_at_val.isoformat()
        else:
            created_at_str = str(created_at_val or "")

        users_list.append(
            UserAdminOut(
                id=str(u.get("_id")),
                phone=u.get("phone"),
                email=u.get("email"),
                role=str(u.get("role", "user")),
                is_active=bool(u.get("is_active", True)),
                created_at=created_at_str,
            )
        )

    return users_list


@router.patch(
    "/users/{user_id}/suspend",
    response_model=UserStatusUpdateResponse,
    dependencies=[admin_guard],
    summary="Suspend a User Account",
)
async def suspend_user(user_id: str, db: Any = Depends(get_database)):
    """
    Sets user `is_active = False`. Suspended users cannot authenticate.
    """
    from bson import ObjectId
    users_collection = db["users"]

    try:
        obj_id = ObjectId(user_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid user_id format: '{user_id}'",
        )

    result = await users_collection.update_one(
        {"_id": obj_id},
        {"$set": {"is_active": False, "updated_at": datetime.now(timezone.utc)}},
    )

    if result.matched_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with ID '{user_id}' not found.",
        )

    logger.info("Admin suspended user %s", user_id)
    return UserStatusUpdateResponse(
        message="User account suspended successfully.",
        user_id=user_id,
        is_active=False,
    )


@router.patch(
    "/users/{user_id}/reactivate",
    response_model=UserStatusUpdateResponse,
    dependencies=[admin_guard],
    summary="Reactivate a Suspended User Account",
)
async def reactivate_user(user_id: str, db: Any = Depends(get_database)):
    """
    Sets user `is_active = True`.
    """
    from bson import ObjectId
    users_collection = db["users"]

    try:
        obj_id = ObjectId(user_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid user_id format: '{user_id}'",
        )

    result = await users_collection.update_one(
        {"_id": obj_id},
        {"$set": {"is_active": True, "updated_at": datetime.now(timezone.utc)}},
    )

    if result.matched_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with ID '{user_id}' not found.",
        )

    logger.info("Admin reactivated user %s", user_id)
    return UserStatusUpdateResponse(
        message="User account reactivated successfully.",
        user_id=user_id,
        is_active=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Moderation Queue Endpoint
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/moderation/queue",
    response_model=List[ModerationItem],
    dependencies=[admin_guard],
    summary="Moderation Queue — Surfacing Confirmation Failures",
)
async def get_moderation_queue(
    limit: int = Query(50, ge=1, le=100),
    db: Any = Depends(get_database),
):
    """
    Surfaces reflection logs where pass_fail == 'fallback'
    (Confirmation Agent retries failed repeatedly up to max_retries).
    Requires human admin review.
    """
    collection = db["reflection_logs"]
    cursor = collection.find({"pass_fail": "fallback"}).sort("timestamp", -1).limit(limit)

    queue = []
    async for doc in cursor:
        queue.append(
            ModerationItem(
                session_id=str(doc.get("session_id", "")),
                timestamp=str(doc.get("timestamp", "")),
                agents_checked=doc.get("agents_checked", []),
                pass_fail=str(doc.get("pass_fail", "fallback")),
                retry_count=int(doc.get("retry_count", 0)),
                rejection_reason=str(doc.get("rejection_reason", "")),
                contradiction_caught=doc.get("contradiction_caught"),
                query_length=int(doc.get("query_length", 0)),
                response_length=int(doc.get("response_length", 0)),
            )
        )

    return queue
