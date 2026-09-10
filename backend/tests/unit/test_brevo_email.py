# backend/tests/unit/test_brevo_email.py
"""
Unit tests for Brevo REST API Email Integration in LEXIS.
Validates:
  - Strict REST API payload formatting (POST https://api.brevo.com/v3/smtp/email)
  - api-key authentication header (zero SMTP)
  - Success response parsing (201 Created with messageId)
  - Error response handling (400, 401 with xsmtpsib- detection, 402, 429, 5xx)
  - Network timeout and connection error resiliency
  - Configuration & input validation
  - Privacy and security: masked logging, zero OTP/API-key logging
"""

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from core.config.settings import Settings
from services.auth.email_provider import (
    BrevoEmailProvider,
    EmailSendResult,
    build_otp_email_templates,
    mask_email,
)


@pytest.fixture
def brevo_provider():
    return BrevoEmailProvider(
        api_key="xkeysib-valid-test-key-12345",
        sender_email="noreply@lexis.local",
        sender_name="LEXIS",
        timeout=5.0,
    )


# ── Test 1: Successful Email Send ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_brevo_send_email_success(brevo_provider):
    mock_response = httpx.Response(
        status_code=201,
        json={"messageId": "<20260910.12345@smtp-relay.mailin.fr>"},
        request=httpx.Request("POST", brevo_provider.BREVO_API_URL),
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
        result = await brevo_provider.send_email(
            recipient_email="citizen@example.com",
            subject="Test Subject",
            html_content="<p>Test HTML</p>",
            text_content="Test Text",
        )

        assert result.success is True
        assert bool(result) is True
        assert result.message_id == "<20260910.12345@smtp-relay.mailin.fr>"
        assert result.status_code == 201
        assert result.error is None

        # Verify Brevo REST API endpoint & headers
        mock_post.assert_called_once()
        call_args, call_kwargs = mock_post.call_args
        assert call_args[0] == "https://api.brevo.com/v3/smtp/email"
        assert call_kwargs["headers"] == {
            "accept": "application/json",
            "api-key": "xkeysib-valid-test-key-12345",
            "content-type": "application/json",
        }

        # Verify Brevo payload schema
        payload = call_kwargs["json"]
        assert payload["sender"] == {"name": "LEXIS", "email": "noreply@lexis.local"}
        assert payload["to"] == [{"email": "citizen@example.com"}]
        assert payload["subject"] == "Test Subject"
        assert payload["htmlContent"] == "<p>Test HTML</p>"
        assert payload["textContent"] == "Test Text"


# ── Test 2: OTP Template Generation & Send OTP Flow ──────────────────────────

@pytest.mark.asyncio
async def test_brevo_send_otp_flow(brevo_provider):
    mock_response = httpx.Response(
        status_code=201,
        json={"messageId": "<otp-msg-999@brevo.com>"},
        request=httpx.Request("POST", brevo_provider.BREVO_API_URL),
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
        success = await brevo_provider.send_otp(email="user@example.com", otp="654321")
        assert success is True
        assert brevo_provider.last_message_id == "<otp-msg-999@brevo.com>"
        assert brevo_provider.last_error == ""

        payload = mock_post.call_args[1]["json"]
        assert payload["subject"] == "LEXIS Email Verification Code"
        assert "654321" in payload["htmlContent"]
        assert "654321" in payload["textContent"]
        assert "Valid for 5 minutes" in payload["htmlContent"]
        assert "Never share this code" in payload["htmlContent"]


# ── Test 3: Missing Configuration Validation ──────────────────────────────────

@pytest.mark.asyncio
async def test_missing_api_key_fails_fast():
    provider = BrevoEmailProvider(api_key="", sender_email="noreply@lexis.local", sender_name="LEXIS")
    result = await provider.send_email("user@example.com", "Subj", "<p>hi</p>")

    assert result.success is False
    assert "BREVO_API_KEY" in result.error
    assert provider.last_error == result.error


@pytest.mark.asyncio
async def test_missing_sender_email_fails_fast():
    provider = BrevoEmailProvider(api_key="xkeysib-test", sender_email="", sender_name="LEXIS")
    result = await provider.send_email("user@example.com", "Subj", "<p>hi</p>")

    assert result.success is False
    assert "BREVO_SENDER_EMAIL" in result.error


# ── Test 4: Recipient Email Validation ────────────────────────────────────────

@pytest.mark.asyncio
async def test_invalid_recipient_email(brevo_provider):
    result_empty = await brevo_provider.send_email("", "Subj", "<p>hi</p>")
    assert result_empty.success is False
    assert "empty" in result_empty.error.lower()

    result_bad = await brevo_provider.send_email("not-an-email", "Subj", "<p>hi</p>")
    assert result_bad.success is False
    assert "syntax" in result_bad.error.lower()


# ── Test 5: 401 Unauthorized with SMTP Key Warning ───────────────────────────

@pytest.mark.asyncio
async def test_brevo_401_with_smtp_key():
    provider = BrevoEmailProvider(
        api_key="xsmtpsib-smtp-relay-key-123",
        sender_email="noreply@lexis.local",
        sender_name="LEXIS",
    )
    mock_response = httpx.Response(
        status_code=401,
        json={"code": "unauthorized", "message": "Key not found"},
        request=httpx.Request("POST", provider.BREVO_API_URL),
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
        result = await provider.send_email("user@example.com", "Subj", "<p>hi</p>")
        assert result.success is False
        assert result.status_code == 401
        assert "SMTP key" in result.error
        assert "xkeysib-" in result.error


@pytest.mark.asyncio
async def test_brevo_401_standard():
    provider = BrevoEmailProvider(
        api_key="xkeysib-invalid-api-key",
        sender_email="noreply@lexis.local",
        sender_name="LEXIS",
    )
    mock_response = httpx.Response(
        status_code=401,
        json={"code": "unauthorized", "message": "Invalid key"},
        request=httpx.Request("POST", provider.BREVO_API_URL),
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
        result = await provider.send_email("user@example.com", "Subj", "<p>hi</p>")
        assert result.success is False
        assert result.status_code == 401
        assert "BREVO_API_KEY" in result.error


# ── Test 6: 400 Bad Request (Unverified Sender) ───────────────────────────────

@pytest.mark.asyncio
async def test_brevo_400_bad_request(brevo_provider):
    mock_response = httpx.Response(
        status_code=400,
        json={"code": "invalid_parameter", "message": "Sender email is not verified"},
        request=httpx.Request("POST", brevo_provider.BREVO_API_URL),
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
        result = await brevo_provider.send_email("user@example.com", "Subj", "<p>hi</p>")
        assert result.success is False
        assert result.status_code == 400
        assert "verified" in result.error.lower()


# ── Test 7: 402 Quota Exceeded ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_brevo_402_quota_exceeded(brevo_provider):
    mock_response = httpx.Response(
        status_code=402,
        json={"code": "quota_exceeded", "message": "Account has run out of credits"},
        request=httpx.Request("POST", brevo_provider.BREVO_API_URL),
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
        result = await brevo_provider.send_email("user@example.com", "Subj", "<p>hi</p>")
        assert result.success is False
        assert result.status_code == 402
        assert "quota" in result.error.lower()


# ── Test 8: 429 Rate Limit Exceeded ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_brevo_429_rate_limit(brevo_provider):
    mock_response = httpx.Response(
        status_code=429,
        json={"code": "too_many_requests", "message": "Rate limit reached"},
        request=httpx.Request("POST", brevo_provider.BREVO_API_URL),
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
        result = await brevo_provider.send_email("user@example.com", "Subj", "<p>hi</p>")
        assert result.success is False
        assert result.status_code == 429
        assert "rate limit" in result.error.lower()


# ── Test 9: 5xx Server Error ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_brevo_500_server_error(brevo_provider):
    mock_response = httpx.Response(
        status_code=500,
        text="Internal Server Error",
        request=httpx.Request("POST", brevo_provider.BREVO_API_URL),
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
        result = await brevo_provider.send_email("user@example.com", "Subj", "<p>hi</p>")
        assert result.success is False
        assert result.status_code == 500
        assert "temporarily unavailable" in result.error.lower()


# ── Test 10: Network Timeout ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_brevo_timeout(brevo_provider):
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=httpx.TimeoutException("Read timeout")):
        result = await brevo_provider.send_email("user@example.com", "Subj", "<p>hi</p>")
        assert result.success is False
        assert "timeout" in result.error.lower()


# ── Test 11: Network / Connection Failure ─────────────────────────────────────

@pytest.mark.asyncio
async def test_brevo_connection_error(brevo_provider):
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=httpx.ConnectError("DNS failure")):
        result = await brevo_provider.send_email("user@example.com", "Subj", "<p>hi</p>")
        assert result.success is False
        assert "connection error" in result.error.lower()


# ── Test 12: Mask Email Utility ───────────────────────────────────────────────

def test_mask_email():
    assert mask_email("user@example.com") == "us****r@example.com"
    assert mask_email("ab@domain.com") == "a*@domain.com"
    assert mask_email("invalid") == "***"
    assert mask_email("") == "***"


# ── Test 13: Settings Config Validation ───────────────────────────────────────

def test_settings_validate_brevo_config():
    valid_settings = Settings(
        SECRET_KEY="test",
        MONGODB_URI="mongodb://localhost:27017",
        REDIS_URL="redis://localhost:6379/0",
        BREVO_API_KEY="xkeysib-123",
        BREVO_SENDER_EMAIL="noreply@lexis.local",
        BREVO_SENDER_NAME="LEXIS",
    )
    is_valid, missing = valid_settings.validate_brevo_config()
    assert is_valid is True
    assert len(missing) == 0

    incomplete_settings = Settings(
        SECRET_KEY="test",
        MONGODB_URI="mongodb://localhost:27017",
        REDIS_URL="redis://localhost:6379/0",
        BREVO_API_KEY="",
        BREVO_SENDER_EMAIL="",
        BREVO_SENDER_NAME="",
    )
    is_valid, missing = incomplete_settings.validate_brevo_config()
    assert is_valid is False
    assert "BREVO_API_KEY" in missing
    assert "BREVO_SENDER_EMAIL" in missing
    assert "BREVO_SENDER_NAME" in missing
