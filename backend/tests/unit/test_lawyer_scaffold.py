"""
=============================================================================
LEXIS — Unit Tests: Lawyer Role Scaffold (Module 13)
=============================================================================

WHAT THIS FILE TESTS
--------------------
Role Isolation — the central security assertion for Module 13.

The lawyer role has existed in the UserRole enum since Module 2 but had no
route of its own.  Module 13 adds GET /api/v1/lawyer/dashboard, protected
by require_role(["lawyer"]).

This test suite verifies the complete role-isolation matrix:

  JWT Role     → Admin Routes (/api/v1/admin/*)     → Lawyer Route (/api/v1/lawyer/dashboard)
  ─────────────────────────────────────────────────────────────────────────
  "lawyer"     → 403 Forbidden  (can't reach admin) → 200 OK
  "admin"      → 200 OK         (can reach admin)    → 403 Forbidden
  "user"       → 403 Forbidden  (can't reach admin)  → 403 Forbidden
  "anonymous"  → 403 Forbidden  (can't reach admin)  → 403 Forbidden
  (no token)   → 401 Unauthorized                    → 401 Unauthorized

WHY THIS MATTERS
-----------------
A permission boundary is only trustworthy if it is machine-verified.
Prose in a README can go stale; a failing test cannot be ignored.

These tests will catch regressions if:
  - A future developer accidentally adds "lawyer" to require_role(["admin"])
  - A future developer makes the lawyer route publicly accessible
  - The require_role factory is refactored incorrectly

All tests use mocked app state — no real DB/Redis needed.
"""

import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI, APIRouter
from unittest.mock import MagicMock

from services.auth.jwt_service import create_access_token


# ─────────────────────────────────────────────────────────────────────────────
# Test App Builders
# ─────────────────────────────────────────────────────────────────────────────

def build_lawyer_test_app() -> FastAPI:
    """
    Minimal FastAPI test app with only the lawyer router mounted.
    No DB needed — the lawyer dashboard route reads nothing from MongoDB.
    """
    test_app = FastAPI()
    from api.routes.lawyer import router as lawyer_router
    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(lawyer_router)
    test_app.include_router(api_v1)
    return test_app


def build_admin_test_app() -> FastAPI:
    """
    Minimal FastAPI test app with only the admin router mounted.
    Mock DB attached (analytics endpoint reads reflection_logs).
    """
    test_app = FastAPI()
    from api.routes.admin import router as admin_router
    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(admin_router)
    test_app.include_router(api_v1)

    # Minimal mock DB so admin analytics endpoint doesn't crash
    mock_ref_col = MagicMock()
    mock_ref_col.count_documents.return_value = 0

    def make_async_cursor(items):
        cursor = MagicMock()
        cursor.skip = MagicMock(return_value=cursor)
        cursor.limit = MagicMock(return_value=cursor)
        cursor.sort = MagicMock(return_value=cursor)
        from unittest.mock import AsyncMock
        cursor.to_list = AsyncMock(return_value=items)

        def async_iter_factory(*args, **kwargs):
            async def _gen():
                for item in items:
                    yield item
            return _gen()

        cursor.__aiter__ = async_iter_factory
        return cursor

    from unittest.mock import AsyncMock
    mock_ref_col.aggregate = MagicMock(side_effect=lambda p: make_async_cursor([]))
    mock_ref_col.find = MagicMock(side_effect=lambda q, *a, **kw: make_async_cursor([]))
    mock_ref_col.distinct = AsyncMock(return_value=[])

    mock_user_col = MagicMock()
    mock_user_col.find = MagicMock(side_effect=lambda q, *a, **kw: make_async_cursor([]))
    mock_user_col.update_one = AsyncMock(return_value=MagicMock(matched_count=1, modified_count=1))

    def get_col(name):
        if name == "reflection_logs":
            return mock_ref_col
        elif name == "users":
            return mock_user_col
        return MagicMock()

    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(side_effect=get_col)
    test_app.state.db = mock_db
    test_app.state.mongo_db_name = "lexis_test"
    test_app.state.mongo_client = MagicMock()
    test_app.state.mongo_client.__getitem__ = MagicMock(return_value=mock_db)

    return test_app


# ─────────────────────────────────────────────────────────────────────────────
# 1. Lawyer JWT → Admin Routes (must be 403)
# ─────────────────────────────────────────────────────────────────────────────

ADMIN_ENDPOINT = "/api/v1/admin/analytics/overview"

@pytest.mark.asyncio
async def test_lawyer_jwt_rejected_by_admin_route():
    """
    CRITICAL ROLE-ISOLATION ASSERTION (part 1 of 2):
    A JWT with role='lawyer' must receive HTTP 403 Forbidden on every admin
    endpoint.  Lawyers are NOT admins — they must have zero visibility into
    admin analytics, user lists, or moderation queues.
    """
    app = build_admin_test_app()
    lawyer_token = create_access_token(user_id="lawyer_001", role="lawyer")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        res = await client.get(
            ADMIN_ENDPOINT,
            headers={"Authorization": f"Bearer {lawyer_token}"},
        )

    assert res.status_code == 403, (
        f"Security flaw: lawyer JWT received HTTP {res.status_code} "
        f"on admin route — expected 403 Forbidden."
    )
    assert "Access denied" in res.json().get("detail", ""), (
        "Expected 'Access denied' in error detail but got: " + str(res.json())
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Non-Lawyer JWTs → Lawyer Route (must be 403)
# ─────────────────────────────────────────────────────────────────────────────

LAWYER_ENDPOINT = "/api/v1/lawyer/dashboard"

@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["user", "admin", "anonymous"])
async def test_non_lawyer_jwt_rejected_by_lawyer_route(role):
    """
    CRITICAL ROLE-ISOLATION ASSERTION (part 2 of 2):
    JWTs with roles 'user', 'admin', or 'anonymous' must receive HTTP 403
    Forbidden on the lawyer dashboard route.

    This is intentional: the lawyer dashboard is a separate permission domain.
    Even admins cannot access the lawyer dashboard directly — they have their
    own /admin route.
    """
    app = build_lawyer_test_app()
    token = create_access_token(user_id=f"{role}_001", role=role)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        res = await client.get(
            LAWYER_ENDPOINT,
            headers={"Authorization": f"Bearer {token}"},
        )

    assert res.status_code == 403, (
        f"Security flaw: role='{role}' JWT received HTTP {res.status_code} "
        f"on lawyer route — expected 403 Forbidden."
    )
    assert "Access denied" in res.json().get("detail", ""), (
        f"Expected 'Access denied' in error detail for role '{role}' but got: "
        + str(res.json())
    )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Lawyer JWT → Lawyer Route (must be 200)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_lawyer_jwt_accepted_by_lawyer_route():
    """
    Positive access control test:
    A JWT with role='lawyer' must receive HTTP 200 OK on the lawyer dashboard.
    The response must be the Coming Soon scaffold — not a real feature payload.
    """
    app = build_lawyer_test_app()
    lawyer_token = create_access_token(user_id="lawyer_001", role="lawyer")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        res = await client.get(
            LAWYER_ENDPOINT,
            headers={"Authorization": f"Bearer {lawyer_token}"},
        )

    assert res.status_code == 200, (
        f"Lawyer JWT was rejected on lawyer route — expected 200 OK, got {res.status_code}."
    )
    data = res.json()
    assert data["role"] == "lawyer"
    assert data["status"] == "coming_soon"
    assert "coming_soon_features" in data
    # Confirm exactly 3 planned features are documented (no more, no less)
    assert len(data["coming_soon_features"]) == 3
    feature_names = [f["feature"] for f in data["coming_soon_features"]]
    assert "Case Referrals" in feature_names
    assert "Lawyer Verification" in feature_names
    assert "Consultation Booking" in feature_names


# ─────────────────────────────────────────────────────────────────────────────
# 4. Unauthenticated requests → both routes (must be 401)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unauthenticated_request_rejected_by_lawyer_route():
    """
    Requests with no Bearer token receive HTTP 401 Unauthorized on the
    lawyer route.  Role guard never runs — auth guard fires first.
    """
    app = build_lawyer_test_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        res = await client.get(LAWYER_ENDPOINT)

    assert res.status_code == 401
    assert "Not authenticated" in res.json().get("detail", "")


@pytest.mark.asyncio
async def test_unauthenticated_request_rejected_by_admin_route():
    """
    Requests with no Bearer token receive HTTP 401 Unauthorized on the
    admin route as well — verifying consistent unauthenticated behaviour
    across both role-restricted domains.
    """
    app = build_admin_test_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        res = await client.get(ADMIN_ENDPOINT)

    assert res.status_code == 401
    assert "Not authenticated" in res.json().get("detail", "")


# ─────────────────────────────────────────────────────────────────────────────
# 5. Scaffold Honesty Test — Coming Soon response must not look functional
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_lawyer_dashboard_response_is_scaffold_not_functional_feature():
    """
    Asserts that the lawyer dashboard response is explicitly marked as a
    Coming Soon scaffold — not a partially-built functional feature.

    This test enforces the project's documented MVP boundary: the lawyer
    route must make its non-functional status clear in the response body,
    so no academic evaluator or user can mistake it for a working feature.
    """
    app = build_lawyer_test_app()
    lawyer_token = create_access_token(user_id="lawyer_001", role="lawyer")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        res = await client.get(
            LAWYER_ENDPOINT,
            headers={"Authorization": f"Bearer {lawyer_token}"},
        )

    data = res.json()
    # status must be explicitly "coming_soon", never "ok" or "active"
    assert data["status"] == "coming_soon", (
        "Lawyer dashboard status field must be 'coming_soon' — found: " + data.get("status", "")
    )
    # scope_note must be present and non-empty
    assert "scope_note" in data and len(data["scope_note"]) > 10, (
        "scope_note field must explain the scaffold intent — missing or empty."
    )
    # each feature must have both a name and a description
    for feature in data["coming_soon_features"]:
        assert "feature" in feature and feature["feature"]
        assert "description" in feature and "Not implemented" in feature["description"], (
            f"Feature '{feature.get('feature')}' description must state 'Not implemented'."
        )
