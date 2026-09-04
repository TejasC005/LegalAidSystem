# backend/services/auth/jwt_service.py
"""
LEXIS — JWT Token Service (Module 2)
---------------------------------------
Creates and validates JSON Web Tokens (JWTs).

WHY TWO TOKENS INSTEAD OF ONE LONG-LIVED TOKEN?
─────────────────────────────────────────────────
Imagine you have a door key.

Option A (one long-lived token):
  You give someone a key that works for 30 days. If that key is stolen,
  the thief has full access for up to 30 days — there is nothing you can
  do except invalidate ALL tokens (logging everyone out).

Option B (access + refresh tokens) — what we use:
  • Access token:   Valid for 15 minutes only.  Used on every API call.
                   If stolen, the thief has at most 15 minutes of access.
  • Refresh token:  Valid for 7 days. Used ONLY to get a new access token.
                   Lives in secure storage, not sent on every request.
                   Can be individually revoked (we can store a blocklist
                   in Redis — added in Module 14 security hardening).

The user stays "logged in" for 7 days (via the refresh token), but their
actual access token expires every 15 minutes — limiting the blast radius
of any token theft to just 15 minutes.

HOW TOKENS ARE STRUCTURED
──────────────────────────
A JWT has three base64-encoded parts: header.payload.signature
  header:    algorithm used (HS256)
  payload:   our data — user_id, role, expiry, token_type
  signature: HMAC of header+payload using SECRET_KEY

The server verifies the signature on every request. If the token has been
tampered with, the signature won't match and the request is rejected.
SECRET_KEY never leaves the server — it's read from .env.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt

from core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

ALGORITHM = "HS256"
ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"


# ── Token creation ─────────────────────────────────────────────────────────────

def create_access_token(user_id: str, role: str) -> str:
    """
    Create a short-lived access token (default: 15 minutes).
    Include user_id and role so any endpoint can identify the caller
    without hitting the database on every request.
    """
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.JWT_ACCESS_EXPIRE_MINUTES
    )
    payload = {
        "sub": user_id,              # "subject" — standard JWT claim for user ID
        "role": role,
        "type": ACCESS_TOKEN_TYPE,
        "exp": expire,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(user_id: str, role: str) -> str:
    """
    Create a longer-lived refresh token (default: 7 days).
    Used only to issue a new access token — not for API calls.
    """
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.JWT_REFRESH_EXPIRE_DAYS
    )
    payload = {
        "sub": user_id,
        "role": role,
        "type": REFRESH_TOKEN_TYPE,
        "exp": expire,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def create_anonymous_token(session_id: str) -> str:
    """
    Create an access token for an anonymous session.
    Anonymous sessions do not persist to the database — they expire
    with the access token.
    """
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.JWT_ACCESS_EXPIRE_MINUTES
    )
    payload = {
        "sub": f"anon:{session_id}",
        "role": "anonymous",
        "type": ACCESS_TOKEN_TYPE,
        "session_id": session_id,
        "exp": expire,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


# ── Token validation ───────────────────────────────────────────────────────────

def decode_token(token: str, expected_type: Optional[str] = None) -> dict:
    """
    Decode and validate a JWT.

    Args:
        token:          The raw JWT string from the Authorization header.
        expected_type:  If set ("access" or "refresh"), rejects tokens of
                        the wrong type (prevents using a refresh token as
                        an access token and vice versa).

    Returns:
        The decoded payload dict.

    Raises:
        JWTError: if the token is invalid, expired, or of the wrong type.
    """
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])

    if expected_type and payload.get("type") != expected_type:
        raise JWTError(f"Expected token type '{expected_type}', got '{payload.get('type')}'")

    return payload
