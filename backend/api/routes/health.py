# backend/api/routes/health.py
"""
LEXIS — Health Check Endpoints (Module 1)
-------------------------------------------
Two endpoints registered under the /api/v1 router:

  GET /api/v1/health
      Liveness probe.  Returns immediately — just confirms the process
      is alive and the API is reachable.  Load balancers call this every
      few seconds; it must never touch the database.

  GET /api/v1/health/db
      Readiness probe.  Actively pings MongoDB and Redis to confirm both
      connections are healthy.  Returns individual status for each so you
      can tell exactly which service is down.
"""

import logging
import time

from fastapi import APIRouter, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["Health"])


# ── Response models (typed, so auto-docs are clean) ─────────────────────────

class LivenessResponse(BaseModel):
    status: str
    service: str
    environment: str
    version: str
    timestamp: float


class DBStatusDetail(BaseModel):
    status: str          # "ok" | "error"
    message: str


class ReadinessResponse(BaseModel):
    status: str          # "ok" | "degraded"
    mongodb: DBStatusDetail
    redis: DBStatusDetail


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=LivenessResponse, summary="Liveness probe")
async def health_liveness(request: Request) -> LivenessResponse:
    """
    Basic liveness check — confirms the API process is running.
    Does NOT touch any database.  Extremely fast by design.
    """
    settings = request.app.state.settings
    logger.debug("Liveness probe hit.")
    return LivenessResponse(
        status="ok",
        service=settings.APP_NAME,
        environment=settings.ENVIRONMENT,
        version=settings.APP_VERSION,
        timestamp=time.time(),
    )


@router.get("/db", response_model=ReadinessResponse, summary="Readiness probe (DB)")
async def health_db(request: Request) -> ReadinessResponse:
    """
    Checks both MongoDB and Redis connectivity.
    Returns status="degraded" if either service fails, with details
    on which one and why — useful for on-call debugging.
    """
    # ── MongoDB ping ─────────────────────────────────────────────────────
    mongo_detail = DBStatusDetail(status="ok", message="Ping successful")
    try:
        client = request.app.state.mongo_client
        await client.admin.command("ping")
    except Exception as exc:
        logger.error("MongoDB health check failed", extra={"error": str(exc)})
        mongo_detail = DBStatusDetail(status="error", message=str(exc))

    # ── Redis ping ───────────────────────────────────────────────────────
    redis_detail = DBStatusDetail(status="ok", message="Ping successful")
    try:
        redis = request.app.state.redis
        await redis.ping()
    except Exception as exc:
        logger.error("Redis health check failed", extra={"error": str(exc)})
        redis_detail = DBStatusDetail(status="error", message=str(exc))

    # Overall status
    overall = (
        "ok"
        if mongo_detail.status == "ok" and redis_detail.status == "ok"
        else "degraded"
    )
    logger.info(
        "DB readiness probe complete",
        extra={"overall": overall, "mongo": mongo_detail.status, "redis": redis_detail.status},
    )
    return ReadinessResponse(
        status=overall,
        mongodb=mongo_detail,
        redis=redis_detail,
    )
