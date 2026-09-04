# backend/api/dependencies/auth.py
"""
LEXIS — Auth Dependencies (Module 2)
--------------------------------------
FastAPI "dependencies" are functions that run automatically before a route
handler.  They can read the request, validate things, and either return a
value to the route or raise an HTTPException to abort the request.

HOW THE ROLE GUARD WORKS
─────────────────────────
`require_role` is a "dependency factory" — a function that returns another
function.  This lets you pass arguments to a dependency:

  @router.get("/admin-only")
  async def admin_page(user = Depends(require_role(["admin"]))):
      ...

What happens on every request to that route:
  1. FastAPI calls require_role(["admin"]) → this returns `_guard`.
  2. FastAPI calls `_guard(request)`.
  3. `_guard` calls `get_current_user` to decode the JWT and get the user.
  4. It checks: is the user's role in ["admin"]?
     - Yes → passes the user object to the route handler.
     - No  → raises HTTP 403 Forbidden immediately.

The route handler never runs if the role check fails.
This is clean, reusable, and readable — one line to protect any route.
"""

import logging
from typing import List

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError

from services.auth.jwt_service import decode_token, ACCESS_TOKEN_TYPE
from models.user import UserRole

logger = logging.getLogger(__name__)

# FastAPI's built-in helper: reads "Authorization: Bearer <token>" header
_bearer_scheme = HTTPBearer(auto_error=False)


# ── Current user dependency ────────────────────────────────────────────────────

async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> dict:
    """
    FastAPI dependency: validates the Bearer JWT and returns the decoded payload.

    Add `user = Depends(get_current_user)` to any route to require login.

    Returns a dict with keys: sub (user_id), role, type, exp.
    Raises HTTP 401 if the token is missing, invalid, or expired.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated — provide a Bearer token in the Authorization header.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_token(credentials.credentials, expected_type=ACCESS_TOKEN_TYPE)
    except JWTError as exc:
        logger.warning("JWT validation failed", extra={"error": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is invalid or expired. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


# ── Role guard factory ─────────────────────────────────────────────────────────

def require_role(allowed_roles: List[str]):
    """
    Dependency factory: creates a guard that allows only the specified roles.

    Usage:
        @router.delete("/user/{id}")
        async def delete_user(user = Depends(require_role(["admin"]))):
            ...

    Args:
        allowed_roles: List of role strings, e.g. ["admin"] or ["admin", "lawyer"].

    Returns:
        A FastAPI dependency function that returns the current user payload
        if their role is allowed, or raises HTTP 403 if not.
    """
    async def _guard(current_user: dict = Depends(get_current_user)) -> dict:
        user_role = current_user.get("role", "")
        if user_role not in allowed_roles:
            logger.warning(
                "Access denied — insufficient role",
                extra={"user_role": user_role, "required": allowed_roles},
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required role: {allowed_roles}. Your role: {user_role}.",
            )
        return current_user

    return _guard
