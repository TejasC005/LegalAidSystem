"""
=============================================================================
LEXIS — Vault Document Service (Module 10)
=============================================================================

WHAT THIS SERVICE DOES
------------------------
This service orchestrates the complete vault upload pipeline:

  1. Validate the uploaded file (reusing Module 7's file_validator)
  2. Extract text from the file (reusing Module 7's OCR extractor)
  3. Ask the LLM to extract deadline dates from the OCR text
  4. Encrypt the file bytes using AES-256-GCM (security/vault_crypto.py)
  5. Store the ENCRYPTED bytes using Module 7's SecureStorageService
  6. Record metadata in MongoDB (collection: vault_documents)

MODULE 7 REUSE POLICY
----------------------
This module does NOT duplicate Module 7's code. It imports and calls:
  - services/ocr/extractor.py   → extract_text()
  - services/storage/secure_storage.py → SecureStorageService.store_file()
  - api/middleware/file_validator.py   → validate_upload()

The only difference from Module 7's storage: bytes are encrypted BEFORE
being passed to store_file(). The storage service itself is unaware of
encryption — it just stores whatever bytes it receives. This separation
of concerns keeps each service focused on one job.

DATE EXTRACTION SAFETY NOTE
-----------------------------
Date extraction from legal documents is safety-critical:
  - A wrongly-extracted visa expiry could mean a missed renewal.
  - A wrongly-extracted lease end date could mean a lost deposit.

LLM date extraction is therefore:
  1. Performed by the vault agent (not here)
  2. Returned WITH a confidence score per date
  3. Never stored as a confirmed deadline until the citizen explicitly confirms

This service stores the RAW extracted dates in vault_documents with
confirmed=False. The API route surfaces them to the citizen for confirmation.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)

VAULT_COLLECTION = "vault_documents"


# ── Data models ───────────────────────────────────────────────────────────────

class ExtractedDate(BaseModel):
    """
    One date extracted by the LLM from an OCR'd document.

    Fields:
        label        — Human-readable label (e.g., "Lease End Date", "Visa Expiry")
        date_str     — The date as a string in ISO 8601 format: "YYYY-MM-DD"
        confidence   — Float 0.0–1.0. Below 0.7 = needs_confirmation=True
        raw_snippet  — Verbatim text from the document that contained this date.
                       Shown to the citizen so they can verify the extraction.
        needs_confirmation — True if confidence < 0.7. The citizen must manually
                             verify this date before a deadline is created.
    """
    label: str
    date_str: str
    confidence: float
    raw_snippet: str
    needs_confirmation: bool = False


class VaultDocument(BaseModel):
    """
    MongoDB metadata record for a vault-stored document.

    NOTE: The actual file bytes are on disk (encrypted). This record just
    describes the file and its extracted dates.
    """
    file_id: str              # UUID4 — disk filename (encrypted, not original)
    user_id: str              # JWT sub of the uploading user
    original_name: str        # Original filename (display only)
    content_type: str         # Validated MIME type
    size_bytes: int           # Original (unencrypted) file size
    created_at: str           # ISO 8601 timestamp
    encrypted: bool = True    # Always True for vault documents
    extracted_dates: list[ExtractedDate] = []   # From LLM — NOT yet confirmed
    confirmed_deadline_id: Optional[str] = None  # Set after citizen confirms dates
    collection: str = VAULT_COLLECTION


# ── Vault upload service ──────────────────────────────────────────────────────

class VaultService:
    """
    Handles the complete vault document lifecycle:
      upload → validate → OCR → encrypt → store → metadata record
    """

    def __init__(self, base_path: str = "./vault_storage", storage_base_path: str = ""):
        # Accept either parameter name for compatibility with tests
        resolved_path = storage_base_path or base_path
        from services.storage.secure_storage import SecureStorageService
        self._storage = SecureStorageService(base_path=resolved_path)

    async def upload_and_extract(
        self,
        db,
        user_id: str,
        file_bytes: bytes,
        original_name: str,
        content_type: str,
    ) -> tuple[VaultDocument, list[ExtractedDate]]:
        """
        Full upload pipeline:
          1. Validate (magic bytes + MIME allowlist + size)
          2. OCR (extract text for date extraction)
          3. Encrypt file bytes (AES-256-GCM)
          4. Store encrypted bytes to disk
          5. Write metadata to MongoDB
          6. Return (VaultDocument, extracted_dates) — dates are NOT confirmed yet

        The extracted_dates list is returned separately so the API route can
        surface them to the citizen for confirmation before creating a deadline.

        RAISES:
            ValueError — if file validation fails
            VaultCryptoError — if encryption key is missing or malformed
        """
        from core.config import get_settings
        settings = get_settings()

        # ── Step 1: Validate ─────────────────────────────────────────────────
        from api.middleware.file_validator import validate_upload
        valid, result_or_error = validate_upload(
            file_bytes=file_bytes,
            claimed_content_type=content_type,
            max_size_mb=settings.UPLOAD_MAX_SIZE_MB,
        )
        if not valid:
            raise ValueError(f"File validation failed: {result_or_error}")
        verified_content_type = result_or_error

        # ── Step 2: OCR (run in thread — synchronous library) ────────────────
        import asyncio
        from services.ocr.extractor import extract_text
        try:
            ocr_text = await asyncio.to_thread(
                extract_text, file_bytes, verified_content_type
            )
            logger.info(
                "Vault OCR complete",
                extra={"user_id": user_id, "chars": len(ocr_text)},
            )
        except Exception as exc:
            # OCR failure is non-fatal for vault — store with empty ocr_text
            logger.warning("Vault OCR failed (non-fatal): %s", exc)
            ocr_text = ""

        # ── Step 3: Encrypt ──────────────────────────────────────────────────
        from security.vault_crypto import encrypt_bytes
        encrypted_bytes = encrypt_bytes(file_bytes)  # Key from VAULT_ENCRYPTION_KEY env

        # ── Step 4: Store encrypted bytes ─────────────────────────────────────
        # We store the ENCRYPTED bytes via Module 7's storage service.
        # The storage service does not know about encryption — it just writes bytes.
        # The original_name and content_type describe the ORIGINAL file,
        # not the encrypted blob (so we can still serve the right Content-Type on download).
        stored_meta = await self._storage.store_file(
            db=db,
            user_id=user_id,
            content_bytes=encrypted_bytes,
            original_name=original_name,
            content_type=verified_content_type,
            collection=VAULT_COLLECTION,
        )

        # ── Step 5: Build vault document metadata ─────────────────────────────
        # extracted_dates are added by the agent separately
        vault_doc = VaultDocument(
            file_id=stored_meta.file_id,
            user_id=user_id,
            original_name=original_name,
            content_type=verified_content_type,
            size_bytes=len(file_bytes),  # Original size, not encrypted size
            created_at=stored_meta.created_at,
            encrypted=True,
            extracted_dates=[],
        )

        # Update the MongoDB record (stored_meta was already inserted by storage service;
        # we upsert the vault_doc with additional vault-specific fields)
        if db is not None:
            await db[VAULT_COLLECTION].update_one(
                {"file_id": vault_doc.file_id, "user_id": user_id},
                {"$set": {
                    "encrypted": True,
                    "extracted_dates": [],
                    "confirmed_deadline_id": None,
                    "size_bytes": len(file_bytes),  # Override with original (unencrypted) size
                }},
            )

        # Return the document AND the raw OCR text so the agent can extract dates
        return vault_doc, ocr_text

    async def retrieve_decrypted(
        self,
        db,
        user_id: str,
        file_id: str,
    ) -> bytes:
        """
        Retrieves an encrypted vault file and decrypts it.

        Access control: file_id + user_id must match (enforced by storage service).

        RETURNS:
            Original plaintext file bytes (decrypted).

        RAISES:
            FileNotFoundError — if file not found or wrong user
            VaultCryptoError — if decryption fails (wrong key or tampered data)
        """
        encrypted_bytes = await self._storage.retrieve_file(
            db=db,
            user_id=user_id,
            file_id=file_id,
            collection=VAULT_COLLECTION,
        )

        from security.vault_crypto import decrypt_bytes
        return decrypt_bytes(encrypted_bytes)

    async def delete_document(
        self,
        db,
        user_id: str,
        file_id: str,
    ) -> bool:
        """
        HARD DELETE: removes file from disk AND MongoDB metadata record.

        This is intentionally a hard delete (not a soft flag / tombstone).
        Vault documents contain the most sensitive personal data in LEXIS
        (Aadhaar, passport, legal documents). A soft delete would mean the
        data persists on disk even after the citizen "deleted" it — unacceptable.

        Also deletes any associated deadline record from vault_deadlines.

        Returns True if the file was found and deleted, False if not found.
        """
        # Delete the file + its storage metadata record (covers disk + vault_documents)
        deleted = await self._storage.delete_file(
            db=db,
            user_id=user_id,
            file_id=file_id,
            collection=VAULT_COLLECTION,
        )

        if deleted and db is not None:
            # Also remove any associated deadline record
            await db["vault_deadlines"].delete_many(
                {"vault_doc_id": file_id, "user_id": user_id}
            )
            logger.info(
                "Vault document hard-deleted (disk + MongoDB + deadlines)",
                extra={"user_id": user_id, "file_id": file_id},
            )

        return deleted

    async def list_documents(
        self,
        db,
        user_id: str,
    ) -> list[VaultDocument]:
        """
        Lists all vault documents belonging to user_id.
        Returns sorted by created_at descending (newest first).
        """
        if db is None:
            return []
        cursor = db[VAULT_COLLECTION].find({"user_id": user_id}).sort("created_at", -1)
        docs = await cursor.to_list(length=100)
        result = []
        for doc in docs:
            doc.pop("_id", None)
            # Reconstruct ExtractedDate objects
            raw_dates = doc.pop("extracted_dates", [])
            dates = [ExtractedDate(**d) if isinstance(d, dict) else d for d in raw_dates]
            result.append(VaultDocument(**doc, extracted_dates=dates))
        return result

    async def store_extracted_dates(
        self,
        db,
        user_id: str,
        file_id: str,
        extracted_dates: list[ExtractedDate],
    ) -> None:
        """
        Updates the vault document record with LLM-extracted dates.
        Called after the agent completes date extraction from OCR text.
        """
        if db is None:
            return
        await db[VAULT_COLLECTION].update_one(
            {"file_id": file_id, "user_id": user_id},
            {"$set": {"extracted_dates": [d.model_dump() for d in extracted_dates]}},
        )


# ── Singleton factory ─────────────────────────────────────────────────────────

_vault_service: Optional[VaultService] = None


def get_vault_service() -> VaultService:
    """Returns a cached VaultService singleton."""
    global _vault_service
    if _vault_service is None:
        from core.config import get_settings
        settings = get_settings()
        _vault_service = VaultService(base_path=settings.VAULT_STORAGE_PATH)
    return _vault_service
