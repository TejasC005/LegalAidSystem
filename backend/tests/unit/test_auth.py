# backend/tests/unit/test_auth.py
"""
LEXIS — Unit Tests: Auth Endpoints (Module 2)
-----------------------------------------------
All external dependencies (MongoDB, Redis, Settings) are mocked.
No real DB connections, no real SMS, no .env required beyond conftest.py.

Run with:
    cd backend
    pytest tests/unit/test_auth.py -v

Tests:
  1. OTP flow success (send + verify → tokens issued)
  2. Wrong-role rejection (user token on admin route → 403)
  3. Rate limit triggers (send-otp too many times → 429)
  4. Anonymous session works (POST /auth/anonymous → valid token)
  5. Token refresh works (valid refresh token → new access + refresh)
"""

import json
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI, APIRouter
from bson import ObjectId

# ── Shared mock settings object ────────────────────────────────────────────────
# We build it once and reuse it everywhere so all patches point to the same object.
MOCK_SETTINGS = MagicMock()
MOCK_SETTINGS.SECRET_KEY = os.environ["SECRET_KEY"]   # set by conftest.py
MOCK_SETTINGS.JWT_ACCESS_EXPIRE_MINUTES = 15
MOCK_SETTINGS.JWT_REFRESH_EXPIRE_DAYS = 7
MOCK_SETTINGS.OTP_TTL_SECONDS = 300
MOCK_SETTINGS.OTP_MAX_ATTEMPTS = 3
MOCK_SETTINGS.OTP_RATE_LIMIT_MAX = 3
MOCK_SETTINGS.OTP_RATE_LIMIT_WINDOW_SECONDS = 60
MOCK_SETTINGS.ENVIRONMENT = "test"
MOCK_SETTINGS.APP_NAME = "LEXIS API"
MOCK_SETTINGS.APP_VERSION = "1.0.0"
MOCK_SETTINGS.BREVO_API_KEY = ""
MOCK_SETTINGS.BREVO_SENDER_EMAIL = "noreply@lexis.local"
MOCK_SETTINGS.BREVO_SENDER_NAME = "LEXIS"


# ─────────────────────────────────────────────────────────────────────────────
# Helper: build an isolated test FastAPI app
# ─────────────────────────────────────────────────────────────────────────────

def build_test_app(
    redis_get_value=None,
    redis_incr_value: int = 1,
    mongo_user: dict | None = None,
) -> FastAPI:
    """
    Creates a minimal FastAPI test app with the auth router mounted and
    MongoDB + Redis fully mocked via app.state.
    """
    test_app = FastAPI()

    from api.routes.auth import router as auth_router
    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(auth_router)
    test_app.include_router(api_v1)

    # ── Mock Redis ────────────────────────────────────────────────────────
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=redis_get_value)
    mock_redis.setex = AsyncMock(return_value=True)
    mock_redis.delete = AsyncMock(return_value=1)
    mock_redis.ttl = AsyncMock(return_value=250)
    mock_redis.incr = AsyncMock(return_value=redis_incr_value)
    mock_redis.expire = AsyncMock(return_value=True)

    # ── Mock MongoDB ──────────────────────────────────────────────────────
    mock_col = AsyncMock()
    mock_col.find_one = AsyncMock(return_value=mongo_user)
    mock_col.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
    mock_col.update_one = AsyncMock(return_value=MagicMock())

    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_col)

    mock_mongo = MagicMock()
    mock_mongo.__getitem__ = MagicMock(return_value=mock_db)

    test_app.state.settings = MOCK_SETTINGS
    test_app.state.mongo_client = mock_mongo
    test_app.state.mongo_db_name = "lexis_test"
    test_app.state.redis = mock_redis

    return test_app


# ─────────────────────────────────────────────────────────────────────────────
# All patches we need in every test — patching get_settings everywhere it's used
# ─────────────────────────────────────────────────────────────────────────────
SETTINGS_PATCHES = [
    "services.auth.jwt_service.settings",
    "services.auth.otp_service.settings",
]


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: OTP flow success
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_otp_flow_success():
    """
    Full OTP flow — send OTP then verify with correct code → tokens issued.
    """
    stored_otp = json.dumps({"otp": "123456", "attempts": 0}).encode()
    app = build_test_app(redis_get_value=stored_otp, redis_incr_value=1)

    with patch("services.auth.jwt_service.settings", MOCK_SETTINGS), \
         patch("services.auth.otp_service.settings", MOCK_SETTINGS), \
         patch("api.middleware.rate_limit.settings", MOCK_SETTINGS):

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            # 1. Send OTP
            r1 = await c.post("/api/v1/auth/send-otp", json={"phone": "+919876543210"})
            assert r1.status_code == 200, r1.text
            assert "OTP sent" in r1.json()["message"]

            # 2. Verify OTP with correct code
            r2 = await c.post("/api/v1/auth/verify-otp",
                              json={"phone": "+919876543210", "otp": "123456"})
            assert r2.status_code == 200, r2.text
            body = r2.json()
            assert "access_token" in body
            assert "refresh_token" in body
            assert body["token_type"] == "bearer"


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: Wrong-role rejected → HTTP 403
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wrong_role_rejected():
    """
    A user with role='user' hitting /auth/admin-only must get HTTP 403.
    """
    with patch("services.auth.jwt_service.settings", MOCK_SETTINGS):
        from services.auth.jwt_service import create_access_token
        token = create_access_token(user_id="user123", role="user")

    app = build_test_app()

    with patch("services.auth.jwt_service.settings", MOCK_SETTINGS):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get(
                "/api/v1/auth/admin-only",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert resp.status_code == 403
    assert "Access denied" in resp.json()["detail"]


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: Rate limit triggers → HTTP 429
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_otp_rate_limit_triggers():
    """
    When Redis INCR returns a value > OTP_RATE_LIMIT_MAX, the endpoint
    must return HTTP 429 before touching any OTP logic.
    """
    # INCR returns 4 → over the max of 3
    app = build_test_app(redis_incr_value=4)

    with patch("api.middleware.rate_limit.settings", MOCK_SETTINGS), \
         patch("services.auth.otp_service.settings", MOCK_SETTINGS):

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/v1/auth/send-otp", json={"phone": "+919876543210"})

    assert resp.status_code == 429
    assert "Too many OTP requests" in resp.json()["detail"]


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: Anonymous session returns a valid JWT
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_anonymous_session_works():
    """
    POST /auth/anonymous must return an access_token with role='anonymous'.
    """
    app = build_test_app()

    with patch("services.auth.jwt_service.settings", MOCK_SETTINGS):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/v1/auth/anonymous")

        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert "session_id" in body
        assert body["role"] == "anonymous"

        # Token must decode correctly
        from services.auth.jwt_service import decode_token
        payload = decode_token(body["access_token"])
        assert payload["role"] == "anonymous"
        assert payload["sub"].startswith("anon:")


# ─────────────────────────────────────────────────────────────────────────────
# Test 5: Token refresh returns a new access + refresh pair
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_token_refresh_works():
    """
    POST /auth/refresh with a valid refresh token must return a new token pair
    for the same user.
    """
    with patch("services.auth.jwt_service.settings", MOCK_SETTINGS):
        from services.auth.jwt_service import create_refresh_token, decode_token
        refresh_token = create_refresh_token(user_id="user456", role="user")

    app = build_test_app()

    with patch("services.auth.jwt_service.settings", MOCK_SETTINGS):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/v1/auth/refresh",
                                json={"refresh_token": refresh_token})

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "access_token" in body
        assert "refresh_token" in body

        payload = decode_token(body["access_token"])
        assert payload["sub"] == "user456"
        assert payload["role"] == "user"


# ─────────────────────────────────────────────────────────────────────────────
# Test 6: Verify Firebase ID Token
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_verify_firebase_token_works():
    """
    POST /auth/verify-firebase-token with a valid token returns LEXIS access and refresh tokens.
    """
    app = build_test_app()
    mock_claims = {"uid": "fb_12345", "phone_number": "+919876543210"}

    with patch("api.routes.auth.verify_firebase_id_token", return_value=mock_claims), \
         patch("services.auth.jwt_service.settings", MOCK_SETTINGS):

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/v1/auth/verify-firebase-token", json={"id_token": "valid_fb_token"})

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "access_token" in body
        assert "refresh_token" in body
        assert body["role"] == "user"


# ─────────────────────────────────────────────────────────────────────────────
# Test 7: Email OTP flow success
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_email_otp_flow_success():
    """
    Full Email OTP flow — send OTP to email, then verify with correct code → tokens issued.
    """
    stored_otp = json.dumps({"otp": "654321", "attempts": 0}).encode()
    app = build_test_app(redis_get_value=stored_otp, redis_incr_value=1)

    from services.auth.email_provider import EmailSendResult

    MOCK_SETTINGS.BREVO_API_KEY = "xkeysib-mock-key"
    mock_res = EmailSendResult(success=True, message_id="msg-test-auth")

    with patch("services.auth.jwt_service.settings", MOCK_SETTINGS), \
         patch("services.auth.otp_service.settings", MOCK_SETTINGS), \
         patch("api.middleware.rate_limit.settings", MOCK_SETTINGS), \
         patch("services.auth.email_provider.BrevoEmailProvider.send_email", new_callable=AsyncMock, return_value=mock_res):

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            # 1. Send OTP to email
            r1 = await c.post("/api/v1/auth/send-otp", json={"email": "citizen@example.com"})
            assert r1.status_code == 200, r1.text
            assert "OTP sent" in r1.json()["message"]

            # 2. Verify OTP with correct code
            r2 = await c.post("/api/v1/auth/verify-otp",
                              json={"email": "citizen@example.com", "otp": "654321"})
            assert r2.status_code == 200, r2.text
            body = r2.json()
            assert "access_token" in body
            assert "refresh_token" in body
            assert body["role"] == "user"


# ─────────────────────────────────────────────────────────────────────────────
# Test 8: Email OTP rate limiting
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_email_otp_rate_limit_triggers():
    """
    When Redis INCR returns a value > OTP_RATE_LIMIT_MAX for email,
    the endpoint returns HTTP 429.
    """
    app = build_test_app(redis_incr_value=4)

    with patch("api.middleware.rate_limit.settings", MOCK_SETTINGS), \
         patch("services.auth.otp_service.settings", MOCK_SETTINGS):

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/v1/auth/send-otp", json={"email": "citizen@example.com"})

    assert resp.status_code == 429
    assert "Too many OTP requests" in resp.json()["detail"]


# ─────────────────────────────────────────────────────────────────────────────
# Test 9: Email OTP invalid code
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_email_otp_invalid_code_rejected():
    """
    Submitting an incorrect code for an email OTP returns HTTP 401.
    """
    stored_otp = json.dumps({"otp": "654321", "attempts": 0}).encode()
    app = build_test_app(redis_get_value=stored_otp, redis_incr_value=1)

    with patch("services.auth.jwt_service.settings", MOCK_SETTINGS), \
         patch("services.auth.otp_service.settings", MOCK_SETTINGS), \
         patch("api.middleware.rate_limit.settings", MOCK_SETTINGS):

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/v1/auth/verify-otp",
                                json={"email": "citizen@example.com", "otp": "000000"})

    assert resp.status_code == 401
    assert "Invalid or expired OTP" in resp.json()["detail"]


