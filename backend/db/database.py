# backend/db/database.py
"""
LEXIS — Async MongoDB Client (Module 1)
-----------------------------------------
Uses Motor, which is the official async MongoDB driver for Python.
Motor wraps PyMongo so all database calls can be awaited instead of
blocking the event loop.

The client is created ONCE during application startup (lifespan) and
stored in app.state.  Every request then reads it from state — no
repeated connect/disconnect per request, which would be very slow.
"""

import logging
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from fastapi import Request

logger = logging.getLogger(__name__)


async def connect_mongo(mongodb_uri: str, db_name: str) -> AsyncIOMotorClient:
    """
    Open the MongoDB connection pool.
    Called once during FastAPI lifespan startup.

    Args:
        mongodb_uri:  Full connection string, e.g. mongodb://localhost:27017
        db_name:      The database to use inside MongoDB, e.g. "lexis"

    Returns:
        A Motor client.  Store this in app.state.mongo_client.
    """
    logger.info("Connecting to MongoDB…", extra={"uri": mongodb_uri.split("@")[-1]})
    try:
        client = AsyncIOMotorClient(
            mongodb_uri,
            serverSelectionTimeoutMS=5000,  # Fail fast if Mongo is unreachable
        )
        # Ping to verify the connection is actually alive at startup
        await client.admin.command("ping")
        logger.info("MongoDB connection established.")
        return client
    except Exception as exc:
        local_uri = "mongodb://localhost:27017"
        if mongodb_uri != local_uri:
            logger.warning(
                "Failed to connect to primary MongoDB (%s): %s. Attempting fallback to local MongoDB (%s)...",
                mongodb_uri.split("@")[-1],
                exc,
                local_uri,
            )
            try:
                fallback_client = AsyncIOMotorClient(local_uri, serverSelectionTimeoutMS=3000)
                await fallback_client.admin.command("ping")
                logger.info("Successfully connected to fallback local MongoDB at %s", local_uri)
                return fallback_client
            except Exception as fallback_exc:
                logger.error("Fallback to local MongoDB also failed: %s", fallback_exc)
        raise exc


async def disconnect_mongo(client: AsyncIOMotorClient) -> None:
    """
    Gracefully close the MongoDB connection pool.
    Called once during FastAPI lifespan shutdown.
    """
    if client:
        client.close()
        logger.info("MongoDB connection closed.")


def get_database(request: Request) -> AsyncIOMotorDatabase:
    """
    FastAPI dependency — inject the Motor database into any route.

    Usage in a route:
        from fastapi import Depends
        from db.database import get_database

        @router.get("/example")
        async def example(db = Depends(get_database)):
            doc = await db["collection"].find_one({})
    """
    return request.app.state.mongo_client[request.app.state.mongo_db_name]
