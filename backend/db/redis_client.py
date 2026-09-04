# backend/db/redis_client.py
"""
LEXIS — Async Redis Client (Module 1)
---------------------------------------
Uses redis-py's asyncio interface (redis.asyncio).
A connection pool is created ONCE at startup, stored in app.state,
and closed cleanly on shutdown.

Redis is used in LEXIS for:
  - Rate-limiting counters (Module 2)
  - Session cache / token blacklist (Module 2)
  - Agent scratchpad caching (Module 4+)
"""

import logging
import redis.asyncio as aioredis
from fastapi import Request

logger = logging.getLogger(__name__)


async def connect_redis(redis_url: str) -> aioredis.Redis:
    """
    Create the async Redis connection pool.
    Called once during FastAPI lifespan startup.

    Args:
        redis_url: Connection string, e.g. redis://localhost:6379/0

    Returns:
        An async Redis client.  Store this in app.state.redis.
    """
    logger.info("Connecting to Redis…", extra={"url": redis_url})
    client = aioredis.from_url(
        redis_url,
        encoding="utf-8",
        decode_responses=True,
        socket_connect_timeout=5,  # Fail fast if Redis is unreachable
    )
    # Ping to confirm connection is alive
    await client.ping()
    logger.info("Redis connection established.")
    return client


async def disconnect_redis(client: aioredis.Redis) -> None:
    """
    Gracefully close the Redis connection pool.
    Called once during FastAPI lifespan shutdown.
    """
    if client:
        await client.aclose()
        logger.info("Redis connection closed.")


def get_redis(request: Request) -> aioredis.Redis:
    """
    FastAPI dependency — inject the Redis client into any route.

    Usage in a route:
        from fastapi import Depends
        from db.redis_client import get_redis

        @router.get("/example")
        async def example(redis = Depends(get_redis)):
            await redis.set("key", "value", ex=60)
    """
    return request.app.state.redis
