# backend/services/auth/otp_service.py
"""
LEXIS — OTP Business Logic (Module 2 / Module 13B)
--------------------------------------------------
BEGINNER NOTE — WHY EMAIL OTP REUSES PHONE OTP LOGIC:
  We reuse the exact same OTP generation (_generate_otp), storage in Redis, TTL expiry,
  attempt counting, and constant-time digest comparison (secrets.compare_digest) for both
  phone and email OTPs.
  Why? Cryptographic OTP generation and timing-attack-safe verification are core security primitives.
  Building a second, separate implementation for email would duplicate critical security code,
  increasing maintenance burden and the risk of introducing subtle bugs.
  Instead, we extract and reuse the core logic, simply using a separate Redis key namespace
  ('otp:email:{email}') and swapping the delivery provider (SMS vs Email provider).

Redis key patterns:
  Phone OTP:  otp:{phone}        →  {"otp": "<6-digit>", "attempts": N}
  Email OTP:  otp:email:{email}  →  {"otp": "<6-digit>", "attempts": N}

TTL:  Configured via OTP_TTL_SECONDS (default 5 minutes).
SECURITY RULES:
  - OTP values and email addresses are NEVER logged in production.
  - OTP attempts are capped (OTP_MAX_ATTEMPTS from settings).
  - Expired OTPs are rejected cleanly.
"""

import json
import logging
import secrets

import redis.asyncio as aioredis

from services.auth.otp_provider import OTPProvider
from services.auth.email_provider import EmailProvider
from core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _make_otp_key(phone: str) -> str:
    """Redis key for storing an OTP for a given phone number."""
    return f"otp:{phone}"


def _make_email_otp_key(email: str) -> str:
    """Redis key for storing an OTP for a given email address."""
    return f"otp:email:{email.lower().strip()}"


def _generate_otp() -> str:
    """
    Generate a cryptographically random 6-digit OTP.
    Uses secrets module (NOT random) — secrets is designed for security tokens.
    """
    return str(secrets.randbelow(900000) + 100000)  # Always 6 digits: 100000–999999


async def send_otp(
    phone: str,
    redis: aioredis.Redis,
    provider: OTPProvider,
) -> bool:
    """
    Generate a new OTP, store it in Redis, and dispatch it via the provider.

    Args:
        phone:    The recipient's phone number.
        redis:    The Redis client (from app.state).
        provider: An OTPProvider instance (dev stub or real SMS provider).

    Returns:
        True on success.
    """
    otp = _generate_otp()
    key = _make_otp_key(phone)

    # Store OTP + attempt counter in Redis with TTL
    payload = json.dumps({"otp": otp, "attempts": 0})
    await redis.setex(key, settings.OTP_TTL_SECONDS, payload)

    # Hand off to the provider (never log otp here)
    success = await provider.send_otp(phone, otp)

    masked_phone = phone[:3] + "****" + phone[-3:] if len(phone) > 6 else "***"
    logger.info(
        "OTP dispatch completed",
        extra={"phone_masked": masked_phone, "success": success},
    )
    return success


async def verify_otp(
    phone: str,
    otp_input: str,
    redis: aioredis.Redis,
) -> bool:
    """
    Verify the OTP a user submitted against what's stored in Redis.

    Increments the attempt counter on each wrong guess.
    Deletes the Redis key on success (one-time use).
    Rejects if max attempts exceeded.

    Returns:
        True if OTP is correct and not expired/exhausted.
        False otherwise (wrong code, expired, too many attempts).
    """
    key = _make_otp_key(phone)
    raw = await redis.get(key)

    if raw is None:
        logger.warning("OTP verification failed — key not found (expired or never sent)",
                       extra={"phone_masked": phone[:3] + "****" + phone[-3:]})
        return False

    data = json.loads(raw)
    attempts = data.get("attempts", 0)

    if attempts >= settings.OTP_MAX_ATTEMPTS:
        logger.warning("OTP verification failed — max attempts exceeded",
                       extra={"phone_masked": phone[:3] + "****" + phone[-3:],
                              "attempts": attempts})
        await redis.delete(key)   # Invalidate after too many tries
        return False

    stored_otp = data.get("otp", "")

    # ⚠️  Constant-time comparison prevents timing attacks
    # (an attacker can't guess digits by measuring response time)
    if not secrets.compare_digest(stored_otp, otp_input):
        # Increment attempt count and save back
        data["attempts"] = attempts + 1
        ttl = await redis.ttl(key)
        if ttl > 0:
            await redis.setex(key, ttl, json.dumps(data))
        logger.warning("OTP verification failed — wrong code",
                       extra={"phone_masked": phone[:3] + "****" + phone[-3:]})
        return False

    # ✅ Correct OTP — delete immediately (one-time use)
    await redis.delete(key)
    logger.info("OTP verified successfully",
                extra={"phone_masked": phone[:3] + "****" + phone[-3:]})
    return True


async def send_email_otp(
    email: str,
    redis: aioredis.Redis,
    provider: EmailProvider,
) -> bool:
    """
    Generate a new OTP for an email address, store in Redis, and dispatch via EmailProvider.
    Reuses the exact same OTP generation (_generate_otp) logic as phone OTP.
    """
    otp = _generate_otp()
    key = _make_email_otp_key(email)

    payload = json.dumps({"otp": otp, "attempts": 0})
    await redis.setex(key, settings.OTP_TTL_SECONDS, payload)

    success = await provider.send_otp(email, otp)
    logger.info("Email OTP dispatch completed", extra={"success": success})
    return success


async def verify_email_otp(
    email: str,
    otp_input: str,
    redis: aioredis.Redis,
) -> bool:
    """
    Verify email OTP submitted against what's stored in Redis.
    Reuses the exact same constant-time comparison and attempt counter logic as phone OTP.
    """
    key = _make_email_otp_key(email)
    raw = await redis.get(key)

    if raw is None:
        logger.warning("Email OTP verification failed — key not found")
        return False

    data = json.loads(raw)
    attempts = data.get("attempts", 0)

    if attempts >= settings.OTP_MAX_ATTEMPTS:
        logger.warning("Email OTP verification failed — max attempts exceeded")
        await redis.delete(key)
        return False

    stored_otp = data.get("otp", "")

    if not secrets.compare_digest(stored_otp, otp_input):
        data["attempts"] = attempts + 1
        ttl = await redis.ttl(key)
        if ttl > 0:
            await redis.setex(key, ttl, json.dumps(data))
        logger.warning("Email OTP verification failed — wrong code")
        return False

    await redis.delete(key)
    logger.info("Email OTP verified successfully")
    return True
