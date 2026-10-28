# backend/api/middleware/email_rate_limit.py
"""
LEXIS — Email OTP Rate Limiter (Module 13B)
--------------------------------------------
Rate limits the send-email-otp endpoint specifically, keyed by EMAIL ADDRESS.
Uses Redis INCR + EXPIRE to count requests atomically.

Redis key pattern:  rl:otp:email:{email}  → integer counter
TTL = OTP_RATE_LIMIT_WINDOW_SECONDS (default: 60 seconds)
Max = OTP_RATE_LIMIT_MAX (default: 3 requests per window)
"""

import logging

from fastapi import HTTPException, Request, status
from core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


async def email_otp_rate_limit(request: Request) -> None:
    """
    FastAPI dependency: enforces OTP rate limiting per email address.

    Reads the email address from the request JSON body.
    Uses Redis INCR + EXPIRE to count requests atomically.

    Raises HTTP 429 if the limit is exceeded.
    """
    try:
        body = await request.json()
        email = body.get("email", "").strip().lower()
    except Exception:
        email = ""

    if not email:
        return

    redis = request.app.state.redis
    redis_key = f"rl:otp:email:{email}"

    current_count = await redis.incr(redis_key)

    if current_count == 1:
        await redis.expire(redis_key, settings.OTP_RATE_LIMIT_WINDOW_SECONDS)

    logger.debug(
        "Email OTP rate limit check",
        extra={"count": current_count, "max": settings.OTP_RATE_LIMIT_MAX},
    )

    if current_count > settings.OTP_RATE_LIMIT_MAX:
        logger.warning("Email OTP rate limit exceeded")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Too many OTP requests for this email address. "
                f"Please wait {settings.OTP_RATE_LIMIT_WINDOW_SECONDS} seconds before trying again."
            ),
            headers={"Retry-After": str(settings.OTP_RATE_LIMIT_WINDOW_SECONDS)},
        )
