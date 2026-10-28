# backend/tests/unit/test_health.py
"""
LEXIS — Unit Tests: Health Endpoints (Module 1)
-------------------------------------------------
Tests both health endpoints without requiring real MongoDB or Redis
connections.  We use httpx.AsyncClient with the FastAPI TestClient
pattern and mock app.state so no external services are needed.

Run with:
    cd backend
    pytest tests/unit/test_health.py -v
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes.health import router as health_router


# ── Helpers ──────────────────────────────────────────────────────────────────

def build_test_app(mongo_ok: bool = True, redis_ok: bool = True) -> FastAPI:
    """
    Creates a minimal FastAPI app with only the health router,
    pre-loaded app.state so we don't need real DB connections.

    Args:
        mongo_ok:  If False, the mock Mongo client will raise on ping.
        redis_ok:  If False, the mock Redis client will raise on ping.
    """
    test_app = FastAPI()

    # Attach the health router under /api/v1 (matching production layout)
    from fastapi import APIRouter
    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(health_router)
    test_app.include_router(api_v1)

    # ── Mock settings ──────────────────────────────────────────────────────
    mock_settings = MagicMock()
    mock_settings.APP_NAME = "LEXIS API"
    mock_settings.APP_VERSION = "1.0.0"
    mock_settings.ENVIRONMENT = "test"

    # ── Mock MongoDB client ────────────────────────────────────────────────
    mock_mongo = MagicMock()
    if mongo_ok:
        mock_mongo.admin.command = AsyncMock(return_value={"ok": 1})
    else:
        mock_mongo.admin.command = AsyncMock(
            side_effect=Exception("Mongo connection refused")
        )

    # ── Mock Redis client ──────────────────────────────────────────────────
    mock_redis = AsyncMock()
    if redis_ok:
        mock_redis.ping = AsyncMock(return_value=True)
    else:
        mock_redis.ping = AsyncMock(
            side_effect=Exception("Redis connection refused")
        )

    # ── Store in app.state (mimics lifespan setup) ─────────────────────────
    test_app.state.settings = mock_settings
    test_app.state.mongo_client = mock_mongo
    test_app.state.mongo_db_name = "lexis_test"
    test_app.state.redis = mock_redis

    return test_app


# ── Test: GET /api/v1/health (liveness) ──────────────────────────────────────

@pytest.mark.asyncio
async def test_liveness_returns_ok():
    """Liveness endpoint should return 200 with status=ok."""
    app = build_test_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "LEXIS API"
    assert body["environment"] == "test"
    assert body["version"] == "1.0.0"
    assert "timestamp" in body


# ── Test: GET /api/v1/health/db (readiness) — both services healthy ──────────

@pytest.mark.asyncio
async def test_db_health_both_ok():
    """Readiness endpoint should return status=ok when both Mongo and Redis are up."""
    app = build_test_app(mongo_ok=True, redis_ok=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/health/db")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["mongodb"]["status"] == "ok"
    assert body["redis"]["status"] == "ok"


# ── Test: GET /api/v1/health/db — MongoDB down ───────────────────────────────

@pytest.mark.asyncio
async def test_db_health_mongo_down():
    """Readiness endpoint should return status=degraded when MongoDB is unreachable."""
    app = build_test_app(mongo_ok=False, redis_ok=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/health/db")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["mongodb"]["status"] == "error"
    assert "Mongo connection refused" in body["mongodb"]["message"]
    assert body["redis"]["status"] == "ok"


# ── Test: GET /api/v1/health/db — Redis down ─────────────────────────────────

@pytest.mark.asyncio
async def test_db_health_redis_down():
    """Readiness endpoint should return status=degraded when Redis is unreachable."""
    app = build_test_app(mongo_ok=True, redis_ok=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/health/db")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["mongodb"]["status"] == "ok"
    assert body["redis"]["status"] == "error"
    assert "Redis connection refused" in body["redis"]["message"]


# ── Test: GET /api/v1/health/db — Both services down ─────────────────────────

@pytest.mark.asyncio
async def test_db_health_both_down():
    """Readiness endpoint should return status=degraded when both services are down."""
    app = build_test_app(mongo_ok=False, redis_ok=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/health/db")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["mongodb"]["status"] == "error"
    assert body["redis"]["status"] == "error"
