# backend/api/middleware/rate_limit.py
"""
LEXIS — OTP Rate Limiter (Module 2)
-------------------------------------
Rate limits the send-OTP endpoint specifically, keyed by PHONE NUMBER
(not IP address).  Keying by phone is more accurate because:
  - A single phone can only request N OTPs per window, regardless of
    which IP/VPN/network they use.
  - IP-based limiting is too blunt (shared IPs at offices, universities,
    etc. would block legitimate users).

Redis is the right tool here:
  - It persists counters across multiple backend processes (if we scale up).
  - TTL (time-to-live) on keys means the window resets automatically.
  - It's already available in our stack.

Redis key pattern:  rl:otp:{phone}  → integer counter
TTL = OTP_RATE_LIMIT_WINDOW_SECONDS (default: 60 seconds)
Max  = OTP_RATE_LIMIT_MAX            (default: 3 requests per window)

Example: phone +91987... can call send-otp 3 times per 60 seconds.
On the 4th call, they get HTTP 429 Too Many Requests.
"""

import logging

from fastapi import HTTPException, Request, status
from core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


async def otp_rate_limit(request: Request) -> None:
    """
    FastAPI dependency: enforces OTP rate limiting per phone number.

    Reads the phone number from the request JSON body.
    Uses Redis INCR + EXPIRE to count requests atomically.

    Raises HTTP 429 if the limit is exceeded.
    Usage:
        @router.post("/send-otp", dependencies=[Depends(otp_rate_limit)])
        async def send_otp_endpoint(...):
    """
    # Parse body to extract email or phone — we need it before the route handler runs
    try:
        body = await request.json()
        target = (body.get("email") or "").strip().lower() or (body.get("phone") or "").strip()
    except Exception:
        target = ""

    if not target:
        # If target is missing, the request validator will catch it — not our job here
        return

    redis = request.app.state.redis
    redis_key = f"rl:otp:{target}"

    # Atomically increment the counter
    current_count = await redis.incr(redis_key)

    if current_count == 1:
        # First request in this window — set the TTL
        await redis.expire(redis_key, settings.OTP_RATE_LIMIT_WINDOW_SECONDS)

    masked_target = target[:3] + "****" + target[-3:] if len(target) > 6 else "***"
    logger.debug(
        "OTP rate limit check",
        extra={
            "target_masked": masked_target,
            "count": current_count,
            "max": settings.OTP_RATE_LIMIT_MAX,
        },
    )

    if current_count > settings.OTP_RATE_LIMIT_MAX:
        logger.warning(
            "OTP rate limit exceeded",
            extra={"target_masked": masked_target, "count": current_count},
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Too many OTP requests. "
                f"Please wait {settings.OTP_RATE_LIMIT_WINDOW_SECONDS} seconds before trying again."
            ),
            headers={"Retry-After": str(settings.OTP_RATE_LIMIT_WINDOW_SECONDS)},
        )
