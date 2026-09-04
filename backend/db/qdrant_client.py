"""
=============================================================================
LEXIS — Qdrant Vector Database Client (Module 5)
=============================================================================
Provides client instantiation and collection initialization for Qdrant.
Supports connected server mode (local Docker / staging) and automatic fallback
to in-memory mode (:memory:) for isolated unit testing and offline development.
"""

import logging
from typing import Optional

from qdrant_client import QdrantClient
from qdrant_client.http import models as rest_models

from core.config import get_settings

logger = logging.getLogger(__name__)


def get_qdrant_client(
    force_in_memory: bool = False,
    override_host: Optional[str] = None,
    override_port: Optional[int] = None,
) -> QdrantClient:
    """
    Returns an initialized QdrantClient instance.

    BEHAVIOUR:
      1. If `force_in_memory` is True, returns an in-memory client (`:memory:`).
      2. Otherwise, attempts to connect to the configured Qdrant server host/port.
      3. If connection fails or host is unreachable, falls back to in-memory mode
         so the application and test suite continue seamlessly without crashing.
    """
    if force_in_memory:
        logger.info("Initializing in-memory Qdrant client (:memory:)")
        return QdrantClient(location=":memory:")

    settings = get_settings()
    host = override_host or settings.QDRANT_HOST
    port = override_port or settings.QDRANT_PORT

    try:
        client = QdrantClient(
            host=host,
            port=port,
            api_key=settings.QDRANT_API_KEY if settings.QDRANT_API_KEY else None,
            timeout=5.0,
        )
        # Test connection with health check call
        client.get_collections()
        logger.info("Connected to Qdrant server at http://%s:%s", host, port)
        return client

    except Exception as exc:
        logger.warning(
            "Could not connect to Qdrant server at http://%s:%s (%s). Falling back to in-memory mode (:memory:)",
            host,
            port,
            exc,
        )
        return QdrantClient(location=":memory:")


def init_qdrant_collection(
    client: QdrantClient,
    collection_name: str,
    vector_size: int = 384,
    recreate: bool = False,
) -> bool:
    """
    Ensures that the target Qdrant collection exists with the required schema.

    - Vector size: 1024 (matches BGE-M3 dense embeddings)
    - Distance metric: Cosine similarity
    """
    try:
        collections = client.get_collections().collections
        exists = any(c.name == collection_name for c in collections)

        if exists and recreate:
            logger.info("Re-creating Qdrant collection '%s'", collection_name)
            client.delete_collection(collection_name=collection_name)
            exists = False

        if not exists:
            logger.info("Creating Qdrant collection '%s' (vector_size=%d)", collection_name, vector_size)
            client.create_collection(
                collection_name=collection_name,
                vectors_config=rest_models.VectorParams(
                    size=vector_size,
                    distance=rest_models.Distance.COSINE,
                ),
            )
            return True
        else:
            logger.info("Qdrant collection '%s' already exists", collection_name)
            return False

    except Exception as exc:
        logger.error("Failed to initialize Qdrant collection '%s': %s", collection_name, exc)
        raise
