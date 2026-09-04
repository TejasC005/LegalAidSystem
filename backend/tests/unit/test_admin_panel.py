"""
=============================================================================
LEXIS — Unit Tests: Admin Panel Endpoints (Module 12)
=============================================================================

WHAT THIS FILE TESTS
--------------------
1. Strict Role Guarding (Non-Admin Rejection):
   Confirms that non-admin JWTs (user role, anonymous role, lawyer role)
   are rejected with HTTP 403 Forbidden on EVERY single admin route,
   even when the request body/parameters are otherwise well-formed.

2. Unauthenticated Rejection:
   Confirms requests without a Bearer token are rejected with HTTP 401 Unauthorized.

3. Analytics Data Honesty:
   Confirms real aggregation response formats with 0-data default states
   (no fake/mock placeholder numbers).

4. User Management Actions:
   Confirms listing, suspending (is_active=False), and reactivating (is_active=True).

5. Moderation Queue Filtering:
   Confirms that only fallback-status reflection entries are surfaced for human review.
"""

import os
import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI, APIRouter
from bson import ObjectId

from services.auth.jwt_service import create_access_token


# ─────────────────────────────────────────────────────────────────────────────
# Test App Setup Helper
# ─────────────────────────────────────────────────────────────────────────────

def build_test_admin_app(reflection_logs=None, users=None) -> FastAPI:
    """
    Builds a FastAPI app with admin_router mounted and MongoDB mocked.
    """
    test_app = FastAPI()

    from api.routes.admin import router as admin_router
    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(admin_router)
    test_app.include_router(api_v1)

    if reflection_logs is None:
        reflection_logs = []
    if users is None:
        users = []

    # Mock reflection_logs collection cursor / aggregate
    mock_ref_col = AsyncMock()
    mock_ref_col.count_documents = AsyncMock(return_value=len(reflection_logs))

    # Helper to build mock async cursor from list
    def make_async_cursor(items):
        cursor = MagicMock()
        cursor.skip = MagicMock(return_value=cursor)
        cursor.limit = MagicMock(return_value=cursor)
        cursor.sort = MagicMock(return_value=cursor)
        
        def async_iter_factory(*args, **kwargs):
            async def _gen():
                for item in items:
                    yield item
            return _gen()

        cursor.__aiter__ = async_iter_factory
        cursor.to_list = AsyncMock(return_value=items)
        return cursor

    mock_ref_col.aggregate = MagicMock(side_effect=lambda pipeline: make_async_cursor(reflection_logs))
    mock_ref_col.find = MagicMock(side_effect=lambda query, *args, **kwargs: make_async_cursor(reflection_logs))
    mock_ref_col.distinct = AsyncMock(return_value=["rights", "draft"])

    # Mock users collection
    mock_user_col = AsyncMock()
    mock_user_col.find = MagicMock(side_effect=lambda query, *args, **kwargs: make_async_cursor(users))
    mock_user_col.update_one = AsyncMock(return_value=MagicMock(matched_count=1, modified_count=1))

    # Mock DB mapping
    def get_collection(name):
        if name == "reflection_logs":
            return mock_ref_col
        elif name == "users":
            return mock_user_col
        return AsyncMock()

    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(side_effect=get_collection)

    mock_mongo = MagicMock()
    mock_mongo.__getitem__ = MagicMock(return_value=mock_db)

    # Attach to app.state (same structure expected by get_database dependency)
    test_app.state.mongo_client = mock_mongo
    test_app.state.mongo_db_name = "lexis_test"
    test_app.state.db = mock_db

    return test_app


# ─────────────────────────────────────────────────────────────────────────────
# 1. Mandatory Security Test: Non-Admin JWT Rejected on Every Admin Route
# ─────────────────────────────────────────────────────────────────────────────

ADMIN_ROUTES = [
    ("GET", "/api/v1/admin/analytics/overview"),
    ("GET", "/api/v1/admin/analytics/agents"),
    ("GET", "/api/v1/admin/users"),
    ("PATCH", f"/api/v1/admin/users/{ObjectId()}/suspend"),
    ("PATCH", f"/api/v1/admin/users/{ObjectId()}/reactivate"),
    ("GET", "/api/v1/admin/moderation/queue"),
]

@pytest.mark.asyncio
@pytest.mark.parametrize("method,endpoint", ADMIN_ROUTES)
async def test_non_admin_jwt_rejected_on_every_admin_route(method, endpoint):
    """
    CRITICAL SECURITY ASSERTION:
    Confirms a non-admin JWT ('user', 'anonymous', or 'lawyer' role) receives
    HTTP 403 Forbidden on EVERY admin endpoint.
    """
    app = build_test_admin_app()
    non_admin_roles = ["user", "anonymous", "lawyer"]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        for role in non_admin_roles:
            token = create_access_token(user_id="user_123", role=role)
            headers = {"Authorization": f"Bearer {token}"}

            if method == "GET":
                res = await client.get(endpoint, headers=headers)
            elif method == "PATCH":
                res = await client.patch(endpoint, headers=headers)

            assert res.status_code == 403, (
                f"Security flaw: Role '{role}' got HTTP {res.status_code} "
                f"instead of 403 Forbidden on {method} {endpoint}"
            )
            assert "Access denied" in res.json().get("detail", "")


@pytest.mark.asyncio
@pytest.mark.parametrize("method,endpoint", ADMIN_ROUTES)
async def test_unauthenticated_request_rejected_on_every_admin_route(method, endpoint):
    """
    Confirms requests with missing Bearer token receive HTTP 401 Unauthorized.
    """
    app = build_test_admin_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        if method == "GET":
            res = await client.get(endpoint)
        elif method == "PATCH":
            res = await client.patch(endpoint)

        assert res.status_code == 401
        assert "Not authenticated" in res.json().get("detail", "")


# ─────────────────────────────────────────────────────────────────────────────
# 2. Analytics Overview Endpoints (Admin Access)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_analytics_overview_returns_honest_empty_state():
    """
    Admin token on empty DB returns HTTP 200 with zero counts (no fabricated numbers).
    """
    app = build_test_admin_app(reflection_logs=[])
    admin_token = create_access_token(user_id="admin_1", role="admin")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        res = await client.get(
            "/api/v1/admin/analytics/overview",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["total_sessions_logged"] == 0
        assert data["total_agent_evaluations"] == 0
        assert data["pass_rate_percentage"] == 0.0
        assert data["fail_rate_percentage"] == 0.0
        assert data["fallback_rate_percentage"] == 0.0
        assert data["total_retries"] == 0
        assert data["total_contradictions"] == 0
        assert data["agents_evaluated"] == []


@pytest.mark.asyncio
async def test_admin_analytics_agents_returns_all_6_agents():
    """
    Per-agent analytics endpoint returns breakdown for all 6 agents (rights, draft, analyze, scam, filing, vault).
    """
    app = build_test_admin_app()
    admin_token = create_access_token(user_id="admin_1", role="admin")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        res = await client.get(
            "/api/v1/admin/analytics/agents",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 6
        agent_ids = [item["agent_id"] for item in data]
        assert set(agent_ids) == {"rights", "draft", "analyze", "scam", "filing", "vault"}


# ─────────────────────────────────────────────────────────────────────────────
# 3. User Management Endpoints (Admin Access)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_list_users():
    """
    Admin user listing endpoint returns formatted list of users.
    """
    sample_users = [
        {"_id": ObjectId(), "phone": "+919876543210", "role": "user", "is_active": True, "created_at": "2026-08-29T10:00:00Z"},
        {"_id": ObjectId(), "phone": "+919123456789", "role": "admin", "is_active": True, "created_at": "2026-08-29T10:05:00Z"},
    ]
    app = build_test_admin_app(users=sample_users)
    admin_token = create_access_token(user_id="admin_1", role="admin")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        res = await client.get(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 2
        assert data[0]["phone"] == "+919876543210"
        assert data[1]["role"] == "admin"


@pytest.mark.asyncio
async def test_admin_suspend_and_reactivate_user():
    """
    Admin can suspend and reactivate a user.
    """
    user_id = str(ObjectId())
    app = build_test_admin_app()
    admin_token = create_access_token(user_id="admin_1", role="admin")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        # Suspend
        res = await client.patch(
            f"/api/v1/admin/users/{user_id}/suspend",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert res.status_code == 200
        assert res.json()["is_active"] is False

        # Reactivate
        res = await client.patch(
            f"/api/v1/admin/users/{user_id}/reactivate",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert res.status_code == 200
        assert res.json()["is_active"] is True


@pytest.mark.asyncio
async def test_admin_suspend_invalid_user_id_returns_400():
    """
    Malformed user_id string returns HTTP 400 Bad Request.
    """
    app = build_test_admin_app()
    admin_token = create_access_token(user_id="admin_1", role="admin")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        res = await client.patch(
            "/api/v1/admin/users/invalid-uuid-123/suspend",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert res.status_code == 400
        assert "Invalid user_id format" in res.json()["detail"]


# ─────────────────────────────────────────────────────────────────────────────
# 4. Moderation Queue Endpoint (Admin Access)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_moderation_queue_returns_fallback_logs():
    """
    Moderation queue surfaces reflection logs with pass_fail='fallback'.
    """
    sample_logs = [
        {
            "session_id": "sess-fallback-1",
            "timestamp": "2026-08-29T10:00:00Z",
            "agents_checked": ["rights"],
            "pass_fail": "fallback",
            "retry_count": 3,
            "rejection_reason": "Missing citation after 3 retries",
            "query_length": 50,
            "response_length": 250,
        }
    ]
    app = build_test_admin_app(reflection_logs=sample_logs)
    admin_token = create_access_token(user_id="admin_1", role="admin")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        res = await client.get(
            "/api/v1/admin/moderation/queue",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 1
        assert data[0]["session_id"] == "sess-fallback-1"
        assert data[0]["pass_fail"] == "fallback"
        assert data[0]["retry_count"] == 3
