"""
=============================================================================
LEXIS — Secure File Storage Service (Module 7 / Module 10 shared)
=============================================================================

WHY THIS SERVICE EXISTS
------------------------
When a user uploads a document (contract, ID, notice), we must:
  1. Store it so only THAT user can retrieve it.
  2. Never expose it at a guessable public URL.
  3. Keep metadata (file_id, original name, type) in MongoDB so we can
     list, retrieve, and delete it safely.

HOW THE STORAGE PATTERN WORKS
--------------------------------
Files are stored on disk at:
    VAULT_STORAGE_PATH / {user_id} / {uuid4_file_id}

The `user_id` directory prevents any cross-user path collision.
The `uuid4_file_id` is randomly generated — it is NOT the original filename
and NOT derived from any guessable value.  The original filename is stored
only in MongoDB metadata, never exposed in the path.

WHY NOT SERVE FILES DIRECTLY FROM DISK?
-----------------------------------------
A direct static file server would let anyone who knows the path download it.
Instead, every retrieval goes through `retrieve_file(user_id, file_id)` which:
  - Checks MongoDB for a record WHERE {file_id AND user_id} match.
  - Only then reads bytes from disk.
  Even if someone guesses a uuid4 path, they still need the matching user_id
  from a valid JWT.

REUSE IN MODULE 10
--------------------
The Vault & Deadline Agent (Module 10) will call this same service to store
citizen legal documents (Aadhaar, property papers, etc.) with deadline
reminders.  The storage pattern is identical — only the MongoDB collection
name and calling context differ.
"""

import uuid
import logging
import os
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ── Data model for a stored file's metadata ───────────────────────────────────

class StoredFileMeta(BaseModel):
    """
    Represents the MongoDB metadata record for a stored file.
    The actual file bytes live on disk; this record points to them.
    """
    file_id: str          # UUID4 — the disk filename (not the original)
    user_id: str          # The JWT subject of the uploading user
    original_name: str    # Original filename (display only — never used for paths)
    content_type: str     # Validated MIME type (e.g. "application/pdf")
    size_bytes: int       # File size for UI display
    created_at: str       # ISO 8601 timestamp
    collection: str       # MongoDB collection this was stored in (for Module 10 reuse)


# ── Storage service ───────────────────────────────────────────────────────────

class SecureStorageService:
    """
    Handles all file storage and retrieval with per-user access control.

    USAGE:
        storage = SecureStorageService(base_path="./vault_storage")
        meta = await storage.store_file(
            db=db,
            user_id="user123",
            content_bytes=b"...",
            original_name="contract.pdf",
            content_type="application/pdf",
            collection="user_uploads",
        )
        file_bytes = await storage.retrieve_file(db, user_id="user123", file_id=meta.file_id)
    """

    def __init__(self, base_path: str):
        """
        base_path: Root directory where per-user subdirectories will be created.
                   In .env: VAULT_STORAGE_PATH=./vault_storage
                   In production, point this at a mounted volume or object store.
        """
        self.base_path = Path(base_path)

    def _user_dir(self, user_id: str) -> Path:
        """
        Returns the per-user directory path and creates it if it doesn't exist.
        user_id is used as the directory name — ensuring isolation between users.
        """
        # Sanitize user_id to prevent any directory traversal attacks.
        # JWT sub values are UUIDs or phone numbers — strip anything that isn't
        # alphanumeric, dash, underscore, or plus (for E.164 phone format).
        safe_uid = "".join(c for c in user_id if c.isalnum() or c in "-_+")
        if not safe_uid:
            raise ValueError("Invalid user_id — cannot determine storage directory.")
        user_dir = self.base_path / safe_uid
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir

    async def store_file(
        self,
        db,                      # Motor async MongoDB database handle
        user_id: str,
        content_bytes: bytes,
        original_name: str,
        content_type: str,
        collection: str = "user_uploads",
    ) -> StoredFileMeta:
        """
        Stores file bytes to disk and records metadata in MongoDB.

        Returns a StoredFileMeta with the file_id that can be used for later retrieval.
        The file_id is a UUID4 — not guessable, not the original filename.
        """
        file_id = str(uuid.uuid4())
        user_dir = self._user_dir(user_id)
        file_path = user_dir / file_id

        # Write bytes to disk
        file_path.write_bytes(content_bytes)
        logger.info(
            "File stored",
            extra={"user_id": user_id, "file_id": file_id, "size": len(content_bytes)},
        )

        meta = StoredFileMeta(
            file_id=file_id,
            user_id=user_id,
            original_name=original_name,
            content_type=content_type,
            size_bytes=len(content_bytes),
            created_at=datetime.now(timezone.utc).isoformat(),
            collection=collection,
        )

        # Store metadata in MongoDB — used for access-controlled retrieval
        if db is not None:
            await db[collection].insert_one(meta.model_dump())

        return meta

    async def retrieve_file(
        self,
        db,
        user_id: str,
        file_id: str,
        collection: str = "user_uploads",
    ) -> bytes:
        """
        Retrieves file bytes if and only if the file belongs to user_id.

        Raises FileNotFoundError if:
          - No metadata record exists for this (file_id, user_id) pair.
          - The disk file has been deleted (data integrity failure).

        This double-check (MongoDB + disk) ensures that even if someone guesses
        a UUID4 file_id, they cannot retrieve the file without also matching
        the correct user_id from a valid JWT.
        """
        if db is not None:
            meta = await db[collection].find_one(
                {"file_id": file_id, "user_id": user_id}
            )
            if not meta:
                raise FileNotFoundError(
                    f"File {file_id} not found or does not belong to this user."
                )

        user_dir = self._user_dir(user_id)
        file_path = user_dir / file_id
        if not file_path.exists():
            raise FileNotFoundError(f"File {file_id} missing from disk.")

        return file_path.read_bytes()

    async def delete_file(
        self,
        db,
        user_id: str,
        file_id: str,
        collection: str = "user_uploads",
    ) -> bool:
        """
        Deletes a file from disk and removes its MongoDB metadata record.
        Returns True if the file was found and deleted, False if not found.
        Access-controlled: user_id must match the file owner.
        """
        if db is not None:
            result = await db[collection].delete_one(
                {"file_id": file_id, "user_id": user_id}
            )
            if result.deleted_count == 0:
                return False

        user_dir = self._user_dir(user_id)
        file_path = user_dir / file_id
        if file_path.exists():
            file_path.unlink()
            logger.info("File deleted", extra={"user_id": user_id, "file_id": file_id})
        return True

    async def list_user_files(
        self,
        db,
        user_id: str,
        collection: str = "user_uploads",
    ) -> list[StoredFileMeta]:
        """
        Lists all files belonging to user_id.
        Returns an empty list if no files are found.
        """
        if db is None:
            return []
        cursor = db[collection].find({"user_id": user_id}).sort("created_at", -1)
        docs = await cursor.to_list(length=100)
        return [StoredFileMeta(**d) for d in docs]


# ── Singleton factory ─────────────────────────────────────────────────────────

_storage_service: Optional[SecureStorageService] = None


def get_storage_service() -> SecureStorageService:
    """
    Returns a cached SecureStorageService singleton.

    The base_path is read from settings at first call. This lazy initialization
    avoids importing settings at module load time, which would fail during testing
    when environment variables aren't set yet.
    """
    global _storage_service
    if _storage_service is None:
        from core.config import get_settings
        settings = get_settings()
        _storage_service = SecureStorageService(base_path=settings.VAULT_STORAGE_PATH)
    return _storage_service
