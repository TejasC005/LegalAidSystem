# backend/tests/unit/test_module_13b.py
"""
LEXIS — Module 13B: Enhanced Auth & Profile Unit Tests
------------------------------------------------------
Tests covering:
  1. Email OTP send & verify flow
  2. Email OTP rate limiting triggers correctly (HTTP 429)
  3. Profile update persists valid inputs and rejects invalid inputs (e.g. invalid date_of_birth, invalid preferred_language)
  4. Profile picture upload accepts valid image files and rejects non-image files (e.g. text/pdf)
  5. notification_preference is respected by the Module 10 scheduler / notification service
  6. Account deletion removes the user record AND all their vault documents and deadlines (no orphaned records remain)
  7. Unauthorized / anonymous users cannot GET or PATCH someone else's profile (RBAC & ownership verification)
  8. Account data export returns structured JSON payload
"""

import json
import os
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId

from fastapi import HTTPException
from fastapi.testclient import TestClient

from main import create_app
from models.user import UserRole, PreferredLanguage, NotificationPreference, UserDocument, ProfileDocument
from services.auth.jwt_service import create_access_token


# ── Fixtures & Setup ──────────────────────────────────────────────────────────

@pytest.fixture
def mock_mongo_db():
    """Mock Mongo Database instance."""
    db = MagicMock()
    # Mock collections
    users_col = MagicMock()
    vault_docs_col = MagicMock()
    vault_deadlines_col = MagicMock()
    profile_pics_col = MagicMock()

    profile_pics_col.delete_many = AsyncMock()
    vault_docs_col.delete_many = AsyncMock()
    vault_deadlines_col.delete_many = AsyncMock()
    users_col.delete_one = AsyncMock()

    db.__getitem__.side_effect = lambda name: {
        "users": users_col,
        "vault_documents": vault_docs_col,
        "vault_deadlines": vault_deadlines_col,
        "user_profile_pictures": profile_pics_col,
    }.get(name, MagicMock())

    return db, users_col, vault_docs_col, vault_deadlines_col


@pytest.fixture
def mock_redis():
    """Mock Redis client instance."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=True)
    redis.incr = AsyncMock(return_value=1)
    redis.expire = AsyncMock(return_value=True)
    redis.ttl = AsyncMock(return_value=300)
    return redis


@pytest.fixture
def test_app(mock_mongo_db, mock_redis):
    db, users_col, vault_docs_col, vault_deadlines_col = mock_mongo_db
    app = create_app()
    app.state.mongo_client = MagicMock()
    app.state.mongo_client.__getitem__.return_value = db
    app.state.mongo_db_name = "lexis"
    app.state.redis = mock_redis
    return app


@pytest.fixture
def client(test_app):
    return TestClient(test_app)


# ── Test 1: Email OTP Send & Verify Flow ──────────────────────────────────────

@pytest.mark.asyncio
async def test_email_otp_send_and_verify_flow(mock_redis):
    from services.auth.email_provider import DevLogEmailProvider
    from services.auth.otp_service import send_email_otp, verify_email_otp

    provider = DevLogEmailProvider(dev_mode=True)
    email = "citizen@example.com"

    # Send OTP
    success = await send_email_otp(email, mock_redis, provider)
    assert success is True
    mock_redis.setex.assert_called_once()
    key_used = mock_redis.setex.call_args[0][0]
    assert key_used == "otp:email:citizen@example.com"

    stored_payload = mock_redis.setex.call_args[0][2]
    otp_code = json.loads(stored_payload)["otp"]

    # Verify OTP success
    mock_redis.get.return_value = stored_payload
    verified = await verify_email_otp(email, otp_code, mock_redis)
    assert verified is True
    mock_redis.delete.assert_called_with("otp:email:citizen@example.com")

    # Verify OTP wrong code
    mock_redis.get.return_value = stored_payload
    wrong_verified = await verify_email_otp(email, "000000", mock_redis)
    assert wrong_verified is False


# ── Test 2: Email OTP Rate Limiting Triggers ─────────────────────────────────

def test_email_otp_rate_limiting_triggers(client, mock_redis):
    user_id = str(ObjectId())
    token = create_access_token(user_id=user_id, role="user")

    # Simulate 4th call in window (max is 3)
    mock_redis.incr.return_value = 4

    response = client.post(
        "/api/v1/users/me/email/send-otp",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": "citizen@example.com"},
    )
    assert response.status_code == 429
    assert "Too many OTP requests" in response.json()["detail"]


# ── Test 3: Profile Update Persists & Rejects Invalid Input ───────────────────

def test_profile_update_valid_and_invalid(client, mock_mongo_db):
    db, users_col, _, _ = mock_mongo_db
    user_id = str(ObjectId())
    token = create_access_token(user_id=user_id, role="user")

    # Mock user document
    users_col.find_one = AsyncMock(return_value={
        "_id": ObjectId(user_id),
        "phone": "+919876543210",
        "role": "user",
        "profile": {},
    })
    users_col.update_one = AsyncMock()

    # Valid update
    valid_payload = {
        "full_name": "Ramesh Kumar",
        "address": "123 MG Road, Pune",
        "preferred_language": "hi",
        "date_of_birth": "1990-05-15",
        "notification_preference": "both",
    }
    res = client.patch(
        "/api/v1/users/me/profile",
        headers={"Authorization": f"Bearer {token}"},
        json=valid_payload,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["message"] == "Profile updated successfully."
    assert data["profile"]["full_name"] == "Ramesh Kumar"
    assert data["profile"]["preferred_language"] == "hi"

    # Invalid preferred_language
    res_bad_lang = client.patch(
        "/api/v1/users/me/profile",
        headers={"Authorization": f"Bearer {token}"},
        json={"preferred_language": "fr"},  # Invalid enum value
    )
    assert res_bad_lang.status_code == 422  # Validation error

    # Invalid date_of_birth format
    res_bad_dob = client.patch(
        "/api/v1/users/me/profile",
        headers={"Authorization": f"Bearer {token}"},
        json={"date_of_birth": "15-05-1990"},  # Must be YYYY-MM-DD
    )
    assert res_bad_dob.status_code == 422


# ── Test 4: Profile Picture Upload Rejects Non-Image Files ─────────────────────

def test_profile_picture_upload_validation(client, mock_mongo_db):
    db, users_col, _, _ = mock_mongo_db
    user_id = str(ObjectId())
    token = create_access_token(user_id=user_id, role="user")

    users_col.find_one = AsyncMock(return_value={
        "_id": ObjectId(user_id),
        "phone": "+919876543210",
        "role": "user",
        "profile": {},
    })

    # Non-image file (e.g. application/pdf)
    fake_pdf = ("document.pdf", b"%PDF-1.4 content", "application/pdf")
    res_pdf = client.post(
        "/api/v1/users/me/profile/picture",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": fake_pdf},
    )
    assert res_pdf.status_code == 400
    assert "Profile picture must be an image" in res_pdf.json()["detail"]

    # Valid image file (e.g. image/png)
    fake_png = ("avatar.png", b"\x89PNG\r\n\x1a\nfakeimagebytes", "image/png")
    with patch("services.storage.secure_storage.SecureStorageService.store_file") as mock_store:
        mock_meta = MagicMock()
        mock_meta.file_id = "img-uuid-123"
        mock_store.return_value = mock_meta
        users_col.update_one = AsyncMock()

        res_img = client.post(
            "/api/v1/users/me/profile/picture",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": fake_png},
        )
        assert res_img.status_code == 200
        assert "profile_picture_url" in res_img.json()


# ── Test 5: Notification Preference Respected by Scheduler / Service ─────────

@pytest.mark.asyncio
async def test_notification_preference_respected():
    from services.notifications.notification_service import NotificationService

    service = NotificationService(smtp_host="", smtp_port=587, smtp_user="", smtp_pass="", smtp_from="noreply@lexis.local", dev_mode=True)

    # Test preference: 'sms'
    mock_db_sms = MagicMock()
    user_sms_query = MagicMock()
    user_sms_query.find_one = AsyncMock(return_value={
        "_id": "user-123",
        "phone": "+919876543210",
        "email": "user@example.com",
        "profile": {"notification_preference": "sms"},
    })
    mock_db_sms.__getitem__.return_value = user_sms_query

    with patch.object(service, "_send_smtp", new_callable=AsyncMock) as mock_smtp:
        sent = await service.send_deadline_notification(
            user_id="user-123",
            deadline_label="Rent Deadline",
            deadline_date="2026-09-01",
            days_remaining=3,
            draft_text="Draft notice",
            db=mock_db_sms,
        )
        assert sent is True
        mock_smtp.assert_not_called()  # SMTP not called for SMS-only preference

    # Test preference: 'email' (in non-dev mode to test _send_smtp call)
    service_email = NotificationService(smtp_host="smtp.gmail.com", smtp_port=587, smtp_user="u", smtp_pass="p", smtp_from="f", dev_mode=False)
    mock_db_email = MagicMock()
    user_email_query = MagicMock()
    user_email_query.find_one = AsyncMock(return_value={
        "_id": "user-456",
        "phone": "+919876543210",
        "email": "user@example.com",
        "profile": {"notification_preference": "email"},
    })
    mock_db_email.__getitem__.return_value = user_email_query

    with patch.object(service_email, "_send_smtp", new_callable=AsyncMock, return_value=True) as mock_smtp:
        sent_e = await service_email.send_deadline_notification(
            user_id="user-456",
            deadline_label="Property Tax",
            deadline_date="2026-09-15",
            days_remaining=15,
            draft_text="Draft letter",
            db=mock_db_email,
        )
        assert sent_e is True
        mock_smtp.assert_called_once()


# ── Test 6: Account Deletion Cascades & Leaves No Orphaned Records ───────────

def test_account_deletion_cascades(client, mock_mongo_db):
    db, users_col, vault_docs_col, vault_deadlines_col = mock_mongo_db
    user_id = str(ObjectId())
    token = create_access_token(user_id=user_id, role="user")

    # Mock cursor for user vault documents
    cursor_mock = MagicMock()
    cursor_mock.to_list = AsyncMock(return_value=[{"file_id": "file-1"}, {"file_id": "file-2"}])
    vault_docs_col.find.return_value = cursor_mock

    # Mock delete_many / delete_one returns
    deleted_count_mock = MagicMock()
    deleted_count_mock.deleted_count = 2
    vault_docs_col.delete_many = AsyncMock(return_value=deleted_count_mock)
    vault_deadlines_col.delete_many = AsyncMock(return_value=deleted_count_mock)
    users_col.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))

    with patch("services.storage.secure_storage.SecureStorageService.delete_file", new_callable=AsyncMock) as mock_del_file:
        res = client.delete(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        assert res.json()["deleted"] is True
        assert mock_del_file.call_count == 2
        vault_docs_col.delete_many.assert_called_once_with({"user_id": user_id})
        vault_deadlines_col.delete_many.assert_called_once_with({"user_id": user_id})
        users_col.delete_one.assert_called_once()


# ── Test 7: RBAC & Anonymous Guard on Profile Endpoints ──────────────────────

def test_anonymous_and_unauthorized_profile_blocked(client):
    # Anonymous token
    anon_token = create_access_token(user_id="anon-session-999", role="anonymous")

    res_get = client.get(
        "/api/v1/users/me/profile",
        headers={"Authorization": f"Bearer {anon_token}"},
    )
    assert res_get.status_code == 403
    assert "Anonymous sessions cannot manage profile" in res_get.json()["detail"]

    res_patch = client.patch(
        "/api/v1/users/me/profile",
        headers={"Authorization": f"Bearer {anon_token}"},
        json={"full_name": "Hack Attack"},
    )
    assert res_patch.status_code == 403

    # Unauthenticated (no token)
    res_no_auth = client.get("/api/v1/users/me/profile")
    assert res_no_auth.status_code == 401


# ── Test 8: Data Export Endpoint Returns Structured JSON ──────────────────────

def test_data_export_endpoint(client, mock_mongo_db):
    db, users_col, vault_docs_col, vault_deadlines_col = mock_mongo_db
    user_id = str(ObjectId())
    token = create_access_token(user_id=user_id, role="user")

    users_col.find_one = AsyncMock(return_value={
        "_id": ObjectId(user_id),
        "phone": "+919876543210",
        "email": "citizen@example.com",
        "email_verified": True,
        "created_at": datetime.now(timezone.utc),
        "profile": {"full_name": "Ramesh Kumar", "preferred_language": "hi"},
    })

    doc_cursor = MagicMock()
    doc_cursor.to_list = AsyncMock(return_value=[{
        "file_id": "file-123",
        "original_name": "passport.pdf",
        "doc_type": "passport",
        "created_at": "2026-08-25T10:00:00Z",
        "encrypted": True
    }])
    vault_docs_col.find.return_value = doc_cursor

    dl_cursor = MagicMock()
    dl_cursor.to_list = AsyncMock(return_value=[{
        "deadline_id": "dl-456",
        "vault_doc_id": "file-123",
        "label": "Passport Renewal",
        "deadline_date": "2027-01-15",
        "doc_type": "passport",
        "created_at": "2026-08-25T10:05:00Z",
        "reminders_sent": [30]
    }])
    vault_deadlines_col.find.return_value = dl_cursor

    res = client.get(
        "/api/v1/users/me/export",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["user_id"] == user_id
    assert data["email"] == "citizen@example.com"
    assert data["profile"]["full_name"] == "Ramesh Kumar"
    assert len(data["vault_documents"]) == 1
    assert data["vault_documents"][0]["original_name"] == "passport.pdf"
    assert len(data["vault_deadlines"]) == 1
    assert data["vault_deadlines"][0]["label"] == "Passport Renewal"
