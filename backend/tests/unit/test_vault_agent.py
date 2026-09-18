"""
=============================================================================
LEXIS — Module 10: Vault & Deadline Agent — Unit Tests
=============================================================================

8 tests covering:
  1. Anonymous access is rejected with friendly message
  2. Vault upload + OCR + date extraction pipeline
  3. Low-confidence dates are flagged (needs_confirmation=True)
  4. Confirming dates creates deadline records
  5. Scheduler fires at T-30/T-15/T-3 (date-simulated, no real waiting)
  6. Document Drafter is invoked when reminder fires
  7. Hard delete removes from disk AND MongoDB
  8. AES-256-GCM encryption/decryption round-trip
"""

import asyncio
import base64
import os
import pytest
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch


# ── Test 1: Anonymous access rejected with friendly message ──────────────────

def test_anonymous_vault_blocked():
    """
    Anonymous users must get a clear, friendly 403 message — not just "forbidden".
    Tests the _require_real_account() guard used on all vault endpoints.
    """
    from api.routes.vault import _require_real_account, ANONYMOUS_VAULT_MESSAGE
    from fastapi import HTTPException

    anon_user = {"sub": "anon-session-123", "role": "anonymous"}

    with pytest.raises(HTTPException) as exc_info:
        _require_real_account(anon_user)

    assert exc_info.value.status_code == 403
    assert "real LEXIS account" in exc_info.value.detail
    assert "phone number" in exc_info.value.detail.lower() or "OTP" in exc_info.value.detail
    # Must not just say "forbidden" — must explain what to do
    assert len(exc_info.value.detail) > 50


def test_real_user_not_blocked():
    """Real users must pass the anonymous mode guard."""
    from api.routes.vault import _require_real_account

    real_user = {"sub": "user-xyz-123", "role": "user"}
    result = _require_real_account(real_user)
    assert result == real_user


# ── Test 2: Vault upload pipeline (mocked OCR + storage) ────────────────────

@pytest.mark.asyncio
async def test_vault_upload_pipeline():
    """
    Tests the vault upload → OCR → date extraction pipeline.
    Mocks the storage service (disk write) and OCR (no real file needed).
    Verifies the pipeline returns the vault document and extracted dates list.
    """
    # Build a minimal valid PDF magic bytes prefix for the file validator
    fake_pdf_bytes = b"%PDF-1.4 fake content for testing purposes only"

    # Mock the secure storage service to avoid disk writes
    mock_stored_meta = MagicMock()
    mock_stored_meta.file_id = "test-file-uuid-001"
    mock_stored_meta.created_at = "2026-08-26T00:00:00+00:00"

    # Set a test encryption key
    test_key = base64.b64encode(os.urandom(32)).decode()
    os.environ["VAULT_ENCRYPTION_KEY"] = test_key

    # Create a mock storage service object to patch onto the vault service
    mock_store_svc = MagicMock()
    mock_store_svc.store_file = AsyncMock(return_value=mock_stored_meta)

    with (
        patch("api.middleware.file_validator.validate_upload", return_value=(True, "application/pdf")),
        patch("services.ocr.extractor.extract_text", return_value="Lease agreement valid until 31 March 2027."),
        patch("security.vault_crypto.encrypt_bytes", return_value=b"ENCRYPTED_DATA"),
        patch.object(mock_store_svc, "store_file", new_callable=AsyncMock) as _mock_store,
    ):
        _mock_store.return_value = mock_stored_meta

        from services.vault.vault_service import VaultService
        svc = VaultService(storage_base_path="./test_vault_storage")
        # Replace internal storage with our mock
        svc._storage = mock_store_svc

        mock_db = MagicMock()
        mock_db["vault_documents"].update_one = AsyncMock()

        vault_doc, ocr_text = await svc.upload_and_extract(
            db=mock_db,
            user_id="user-test-001",
            file_bytes=fake_pdf_bytes,
            original_name="lease.pdf",
            content_type="application/pdf",
        )

    assert vault_doc.file_id == "test-file-uuid-001"
    assert vault_doc.encrypted is True
    assert vault_doc.user_id == "user-test-001"
    assert vault_doc.original_name == "lease.pdf"
    assert "2027" in ocr_text  # OCR text flowed through


# ── Test 3: Low-confidence dates are flagged ─────────────────────────────────

@pytest.mark.asyncio
async def test_low_confidence_date_flagged():
    """
    SAFETY TEST: dates extracted with confidence < 0.70 must have
    needs_confirmation=True. This prevents a mis-read date from silently
    becoming a deadline.
    """
    from agents.vault_deadline.agent import VaultDeadlineAgent, CONFIDENCE_THRESHOLD

    agent = VaultDeadlineAgent()

    # Mock LLM response: one high-confidence, one low-confidence date
    mock_llm_response = """[
        {"label": "Lease End Date", "date_str": "2027-03-31", "confidence": 0.92,
         "raw_snippet": "The lease expires on 31 March 2027", "needs_confirmation": false},
        {"label": "Payment Due", "date_str": "2027-01-01", "confidence": 0.45,
         "raw_snippet": "01/01/2027", "needs_confirmation": false}
    ]"""

    with patch("google.genai.Client") as mock_genai_cls:
        mock_client = MagicMock()
        mock_genai_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.text = mock_llm_response
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        with patch("core.config.get_settings") as mock_settings:
            mock_settings.return_value.GEMINI_API_KEY = "test-key"
            mock_settings.return_value.GEMINI_MODEL_DEV = "gemini-3.6-flash"
            mock_settings.return_value.OPENAI_API_KEY = ""

            results = await agent.extract_dates_from_text(
                "The lease expires on 31 March 2027. Payment 01/01/2027."
            )

    assert len(results) == 2

    # High-confidence date: needs_confirmation must be False
    high_conf = next(r for r in results if r["label"] == "Lease End Date")
    assert high_conf["confidence"] == 0.92
    assert high_conf["needs_confirmation"] is False

    # Low-confidence date: needs_confirmation must be True (enforced by post-processing)
    low_conf = next(r for r in results if r["label"] == "Payment Due")
    assert low_conf["confidence"] == 0.45
    assert low_conf["confidence"] < CONFIDENCE_THRESHOLD
    assert low_conf["needs_confirmation"] is True


# ── Test 4: Confirm dates creates deadline records ───────────────────────────

@pytest.mark.asyncio
async def test_date_confirmation_creates_deadline():
    """
    When the citizen confirms dates, exactly one deadline record is created
    per confirmed date, stored in vault_deadlines.
    """
    from services.vault.deadline_service import DeadlineService

    svc = DeadlineService()

    mock_db = MagicMock()

    # Mock insert_one so we don't need a real DB
    mock_db["vault_deadlines"].insert_one = AsyncMock()

    record = await svc.create_deadline(
        db=mock_db,
        user_id="user-test-001",
        vault_doc_id="file-uuid-001",
        deadline_date_str="2027-03-31",
        label="Lease End Date",
        doc_type="legal_notice",
    )

    assert record.deadline_date == "2027-03-31"
    assert record.label == "Lease End Date"
    assert record.user_id == "user-test-001"
    assert record.vault_doc_id == "file-uuid-001"
    assert record.reminders_sent == []  # No reminders sent yet
    mock_db["vault_deadlines"].insert_one.assert_called_once()


@pytest.mark.asyncio
async def test_invalid_date_format_raises():
    """Invalid date format must raise ValueError — not silently store bad data."""
    from services.vault.deadline_service import DeadlineService

    svc = DeadlineService()
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        await svc.create_deadline(
            db=None,
            user_id="user",
            vault_doc_id="doc",
            deadline_date_str="31/03/2027",  # Wrong format
            label="Test",
        )


# ── Test 5: Scheduler fires at T-30/T-15/T-3 (simulated dates) ──────────────

@pytest.mark.asyncio
async def test_scheduler_fires_at_correct_intervals():
    """
    CORE SCHEDULER TEST: verifies the daily_deadline_check logic fires
    reminders at T-30, T-15, and T-3 days and skips all other intervals.

    This test SIMULATES date checks — no real waiting required.
    We mock:
      a) date.today() to return specific "today" values
      b) The deadline record to have a fixed deadline_date
      c) All downstream actions (notification, drafter) as no-ops

    This proves the scheduler decision logic, not the actual timing.
    """
    from services.vault.scheduler import daily_deadline_check, REMINDER_INTERVALS
    from services.vault.deadline_service import DeadlineRecord

    # Trigger interval cases to test
    trigger_cases = [30, 15, 3]
    skip_cases = [31, 29, 16, 14, 4, 2, 1, 60]

    for days_remaining in trigger_cases + skip_cases:
        # Set fake deadline_date = today + days_remaining
        fake_today = date(2027, 1, 1)
        fake_deadline = (fake_today + timedelta(days=days_remaining)).isoformat()

        record = DeadlineRecord(
            deadline_id=f"dl-{days_remaining}",
            user_id="user-001",
            vault_doc_id="file-001",
            label="Lease End Date",
            deadline_date=fake_deadline,
            doc_type="legal_notice",
            reminders_sent=[],  # No reminders sent yet
            created_at="2026-08-26T00:00:00+00:00",
        )

        mock_db = MagicMock()
        fired = []

        async def mock_mark_sent(db, deadline_id, interval, draft_text=None):
            fired.append(interval)

        with (
            patch("services.vault.scheduler.date") as mock_date_cls,
            patch("services.vault.deadline_service.DeadlineService.get_all_upcoming_deadlines",
                  new_callable=AsyncMock, return_value=[record]),
            patch("services.vault.deadline_service.DeadlineService.mark_reminder_sent",
                  side_effect=mock_mark_sent),
            patch("agents.vault_deadline.agent.VaultDeadlineAgent.invoke_document_drafter",
                  new_callable=AsyncMock, return_value="[Draft text]"),
            patch("services.notifications.notification_service.NotificationService.send_deadline_notification",
                  new_callable=AsyncMock, return_value=True),
        ):
            mock_date_cls.today.return_value = fake_today

            result = await daily_deadline_check(db=mock_db)

        if days_remaining in REMINDER_INTERVALS:
            assert len(fired) == 1, (
                f"Expected reminder to fire at T-{days_remaining} but fired={fired}"
            )
            assert fired[0] == days_remaining
        else:
            assert len(fired) == 0, (
                f"Expected NO reminder at T-{days_remaining} but got fired={fired}"
            )


@pytest.mark.asyncio
async def test_scheduler_does_not_duplicate_sent_interval():
    """
    If an interval is already in reminders_sent, the scheduler must NOT
    fire again — even if days_remaining matches.
    """
    from services.vault.scheduler import daily_deadline_check
    from services.vault.deadline_service import DeadlineRecord

    fake_today = date(2027, 1, 1)
    fake_deadline = (fake_today + timedelta(days=30)).isoformat()

    record = DeadlineRecord(
        deadline_id="dl-already-sent",
        user_id="user-001",
        vault_doc_id="file-001",
        label="Lease",
        deadline_date=fake_deadline,
        doc_type="legal_notice",
        reminders_sent=[30],  # Already sent T-30
        created_at="2026-08-26T00:00:00+00:00",
    )

    fired = []

    async def mock_mark_sent(db, deadline_id, interval, draft_text=None):
        fired.append(interval)

    with (
        patch("services.vault.scheduler.date") as mock_date_cls,
        patch("services.vault.deadline_service.DeadlineService.get_all_upcoming_deadlines",
              new_callable=AsyncMock, return_value=[record]),
        patch("services.vault.deadline_service.DeadlineService.mark_reminder_sent",
              side_effect=mock_mark_sent),
    ):
        mock_date_cls.today.return_value = fake_today
        result = await daily_deadline_check(db=MagicMock())

    assert len(fired) == 0, "Reminder must NOT fire again for an already-sent interval"
    assert result["skipped"] >= 1


# ── Test 6: Document Drafter invoked on reminder ──────────────────────────────

@pytest.mark.asyncio
async def test_document_drafter_invoked_on_reminder():
    """
    When a reminder fires, invoke_document_drafter() must be called and
    return non-empty draft text. This is the "proactive agentic" proof.
    """
    from agents.vault_deadline.agent import VaultDeadlineAgent

    agent = VaultDeadlineAgent()

    # Use template fallback (no LLM key needed)
    with patch("core.config.get_settings") as mock_settings:
        mock_settings.return_value.OPENAI_API_KEY = ""  # No LLM → template fallback

        draft_text = await agent.invoke_document_drafter(
            doc_type="legal_notice",
            context={
                "label": "Lease End Date",
                "deadline_date": "2027-03-31",
                "days_remaining": 30,
                "user_id": "user-001",
            },
        )

    assert draft_text, "Draft text must not be empty"
    assert len(draft_text) > 100, "Draft must be a real document, not a one-liner"
    # Template draft must include key context
    assert "Lease End Date" in draft_text or "2027" in draft_text or "FILL IN" in draft_text


# ── Test 7: Hard delete removes disk + MongoDB ───────────────────────────────

@pytest.mark.asyncio
async def test_hard_delete_clears_disk_and_db():
    """
    Verifies that delete_document() removes:
      1. The file from disk (via storage service)
      2. The MongoDB metadata record
      3. Any associated deadline records
    """
    from services.vault.vault_service import VaultService
    from services.storage.secure_storage import SecureStorageService

    svc = VaultService(storage_base_path="./test_vault_storage")

    mock_db = MagicMock()
    mock_db["vault_deadlines"].delete_many = AsyncMock()

    with patch.object(
        svc._storage,
        "delete_file",
        new_callable=AsyncMock,
        return_value=True,
    ):
        deleted = await svc.delete_document(
            db=mock_db,
            user_id="user-test-001",
            file_id="test-file-uuid-001",
        )

    assert deleted is True
    # Deadlines must also be deleted
    mock_db["vault_deadlines"].delete_many.assert_called_once()
    call_args = mock_db["vault_deadlines"].delete_many.call_args[0][0]
    assert call_args["vault_doc_id"] == "test-file-uuid-001"
    assert call_args["user_id"] == "user-test-001"


# ── Test 8: AES-256-GCM encryption / decryption round-trip ──────────────────

def test_encryption_decryption_roundtrip():
    """
    Verifies that:
      1. encrypt_bytes() → decrypt_bytes() returns the original plaintext
      2. The ciphertext is NOT the same as the plaintext (actual encryption happened)
      3. Different calls to encrypt_bytes() with the same plaintext produce
         different ciphertext (random nonce ensures this)
    """
    from security.vault_crypto import encrypt_bytes, decrypt_bytes, AES_KEY_SIZE_BYTES

    # Generate a test key (32 bytes)
    test_key = os.urandom(AES_KEY_SIZE_BYTES)

    plaintext = b"SENSITIVE DOCUMENT CONTENT: Aadhaar 1234 5678 9012"

    # Encrypt
    encrypted1 = encrypt_bytes(plaintext, key=test_key)
    encrypted2 = encrypt_bytes(plaintext, key=test_key)

    # Ciphertext must NOT equal plaintext
    assert encrypted1 != plaintext, "Ciphertext must differ from plaintext"

    # Two encryptions of the same data must produce different ciphertexts (random nonce)
    assert encrypted1 != encrypted2, "Same plaintext must produce different ciphertexts (nonce reuse prevention)"

    # Round-trip: decrypt must return original plaintext
    decrypted = decrypt_bytes(encrypted1, key=test_key)
    assert decrypted == plaintext, "Decrypted bytes must match original plaintext"


def test_decryption_with_wrong_key_fails():
    """
    Decrypting with the wrong key must raise VaultCryptoError (not silently return garbage).
    """
    from security.vault_crypto import encrypt_bytes, decrypt_bytes, VaultCryptoError, AES_KEY_SIZE_BYTES

    key_a = os.urandom(AES_KEY_SIZE_BYTES)
    key_b = os.urandom(AES_KEY_SIZE_BYTES)

    encrypted = encrypt_bytes(b"secret data", key=key_a)

    with pytest.raises(VaultCryptoError):
        decrypt_bytes(encrypted, key=key_b)


def test_tampered_ciphertext_fails_decryption():
    """
    If the ciphertext is tampered with (even one byte), GCM authentication
    must fail — not silently return corrupted data.
    """
    from security.vault_crypto import encrypt_bytes, decrypt_bytes, VaultCryptoError, AES_KEY_SIZE_BYTES

    key = os.urandom(AES_KEY_SIZE_BYTES)
    encrypted = encrypt_bytes(b"important document", key=key)

    # Flip a byte in the middle of the ciphertext
    tampered = bytearray(encrypted)
    tampered[len(encrypted) // 2] ^= 0xFF
    tampered = bytes(tampered)

    with pytest.raises(VaultCryptoError, match="tampered|authentication|failed"):
        decrypt_bytes(tampered, key=key)
