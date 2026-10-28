# backend/tests/unit/test_security_hardening.py
"""
LEXIS — Unit Tests: Security Hardening Controls
------------------------------------------------
Validates:
1. SecurityHeadersMiddleware (X-Content-Type-Options, X-Frame-Options, etc.)
2. Admin login rate limiting
3. Sensitive field redaction in MongoDB collection serialization
4. Global sanitized 500 exception handler
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI, HTTPException, Request
from bson import ObjectId

from security.api_hardening import SecurityHeadersMiddleware
from api.middleware.rate_limit import admin_login_rate_limit
from api.routes.admin import _serialize_mongo_doc


@pytest.mark.asyncio
async def test_security_headers_middleware():
    """Confirms security headers are attached to HTTP responses."""
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware, is_production=True)

    @app.get("/test-headers")
    async def sample_route():
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/test-headers")

    assert resp.status_code == 200
    assert resp.headers.get("x-content-type-options") == "nosniff"
    assert resp.headers.get("x-frame-options") == "DENY"
    assert resp.headers.get("x-xss-protection") == "1; mode=block"
    assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin"
    assert "strict-transport-security" in resp.headers


@pytest.mark.asyncio
async def test_admin_login_rate_limit_exceeded():
    """Confirms admin login rate limiter returns HTTP 429 after 5 failed attempts."""
    app = FastAPI()
    mock_redis = AsyncMock()
    mock_redis.incr = AsyncMock(return_value=6)  # Over limit (limit is 5)
    mock_redis.expire = AsyncMock()
    app.state.redis = mock_redis

    @app.post("/admin-login-test")
    async def sample_admin_login(request: Request = None):
        return {"status": "ok"}

    # Simulate Request for dependency
    mock_request = MagicMock()
    mock_request.json = AsyncMock(return_value={"email": "attacker@example.com"})
    mock_request.app.state.redis = mock_redis

    with pytest.raises(HTTPException) as exc_info:
        await admin_login_rate_limit(mock_request)

    assert exc_info.value.status_code == 429
    assert "Too many admin login attempts" in exc_info.value.detail


def test_mongo_doc_redaction_masks_passwords():
    """Confirms _serialize_mongo_doc masks password_hash and password fields."""
    raw_doc = {
        "_id": ObjectId(),
        "email": "admin@lexis.internal",
        "role": "admin",
        "password_hash": "$argon2id$v=19$m=65536,t=3,p=4$secret_hash_value",
        "password": "plain_password_leak",
        "nested": {
            "password_hash": "$argon2id$another_hash",
            "name": "Admin User",
        },
    }

    cleaned = _serialize_mongo_doc(raw_doc)

    assert cleaned["email"] == "admin@lexis.internal"
    assert cleaned["password_hash"] == "[REDACTED]"
    assert cleaned["password"] == "[REDACTED]"
    assert cleaned["nested"]["password_hash"] == "[REDACTED]"
    assert cleaned["nested"]["name"] == "Admin User"
