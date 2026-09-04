# backend/api/routes/auth.py
"""
LEXIS — Authentication Routes (Module 2)
------------------------------------------
All auth endpoints live under /api/v1/auth/

  POST /auth/send-otp      →  Request an OTP for a phone number
  POST /auth/verify-otp    →  Verify OTP, get access + refresh tokens
  POST /auth/refresh        →  Exchange refresh token for new access token
  POST /auth/anonymous      →  Get a temporary anonymous session token
  GET  /auth/me             →  Get current user info (requires login)
  GET  /auth/admin-only     →  Example admin-only route (role guard demo)
"""

import logging
import uuid
from datetime import datetime

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Request, status
from jose import JWTError

from api.dependencies.auth import get_current_user, require_role
from api.middleware.rate_limit import otp_rate_limit
from models.user import (
    AnonymousTokenResponse,
    RefreshRequest,
    SendOTPRequest,
    TokenResponse,
    UserOut,
    UserRole,
    VerifyOTPRequest,
)
from services.auth.jwt_service import (
    REFRESH_TOKEN_TYPE,
    create_access_token,
    create_anonymous_token,
    create_refresh_token,
    decode_token,
)
from services.auth.otp_provider import DevLogOTPProvider
from services.auth.otp_service import send_otp, verify_otp

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])

# Use the dev stub provider — swap this for a real provider before production
_otp_provider = DevLogOTPProvider()


# ── POST /auth/send-otp ───────────────────────────────────────────────────────

@router.post(
    "/send-otp",
    status_code=status.HTTP_200_OK,
    summary="Request an OTP (rate-limited per phone)",
    dependencies=[Depends(otp_rate_limit)],  # Rate limit applied BEFORE handler
)
async def send_otp_endpoint(body: SendOTPRequest, request: Request):
    """
    Sends a 6-digit OTP to the given phone number.
    Rate limited: max 3 requests per 60 seconds per phone number.

    In dev mode, the OTP is printed to server logs instead of sent via SMS.
    """
    redis = request.app.state.redis
    success = await send_otp(body.phone, redis, _otp_provider)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to send OTP. Please try again.",
        )

    return {"message": "OTP sent successfully. Valid for 5 minutes."}


# ── POST /auth/verify-otp ─────────────────────────────────────────────────────

@router.post(
    "/verify-otp",
    response_model=TokenResponse,
    summary="Verify OTP and receive JWT tokens",
)
async def verify_otp_endpoint(body: VerifyOTPRequest, request: Request):
    """
    Verifies the OTP.  On success:
      - Creates a user in MongoDB if this is their first login (signup).
      - Updates the user record on subsequent logins.
      - Issues an access token (15 min) + refresh token (7 days).
    On failure: returns 401.
    """
    redis = request.app.state.redis
    from datetime import timezone
    db = request.app.state.mongo_client[request.app.state.mongo_db_name]

    otp_valid = await verify_otp(body.phone, body.otp, redis)

    if not otp_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired OTP.",
        )

    # Upsert user — create on first login, fetch on subsequent logins
    users_col = db["users"]
    now = datetime.now(timezone.utc)

    existing = await users_col.find_one({"phone": body.phone})
    if existing:
        user_id = str(existing["_id"])
        role = existing.get("role", UserRole.USER.value)
        await users_col.update_one({"_id": existing["_id"]}, {"$set": {"updated_at": now}})
        logger.info("Existing user logged in", extra={"user_id": user_id})
    else:
        new_id = ObjectId()
        user_id = str(new_id)
        role = UserRole.USER.value
        await users_col.insert_one({
            "_id": new_id,
            "phone": body.phone,
            "role": role,
            "is_anonymous": False,
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        })
        logger.info("New user created", extra={"user_id": user_id})

    access_token = create_access_token(user_id, role)
    refresh_token = create_refresh_token(user_id, role)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        role=UserRole(role),
    )


# ── POST /auth/refresh ────────────────────────────────────────────────────────

@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh access token using a valid refresh token",
)
async def refresh_token_endpoint(body: RefreshRequest):
    """
    Exchange a valid refresh token for a new access + refresh token pair.
    The old refresh token is invalidated in Module 14 (token rotation / blocklist).
    """
    try:
        payload = decode_token(body.refresh_token, expected_type=REFRESH_TOKEN_TYPE)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token is invalid or expired. Please log in again.",
        )

    user_id = payload.get("sub", "")
    role = payload.get("role", UserRole.USER.value)

    new_access = create_access_token(user_id, role)
    new_refresh = create_refresh_token(user_id, role)

    return TokenResponse(
        access_token=new_access,
        refresh_token=new_refresh,
        role=UserRole(role),
    )


# ── POST /auth/anonymous ──────────────────────────────────────────────────────

@router.post(
    "/anonymous",
    response_model=AnonymousTokenResponse,
    summary="Start an anonymous session (no signup required)",
)
async def anonymous_session():
    """
    Issues a temporary JWT for an anonymous user.
    The session expires with the access token.
    No database record is created — nothing is persisted.

    Anonymous users CAN use all agent features but CANNOT:
      - Access the Vault (document storage)
      - View conversation history
      - Receive deadline reminders
    """
    session_id = str(uuid.uuid4())
    token = create_anonymous_token(session_id)
    logger.info("Anonymous session created", extra={"session_id": session_id})

    return AnonymousTokenResponse(
        access_token=token,
        session_id=session_id,
    )


# ── GET /auth/me ──────────────────────────────────────────────────────────────

@router.get("/me", summary="Get current user profile")
async def get_me(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """
    Returns the current user's profile.
    Requires a valid Bearer access token.
    Works for both real users and anonymous sessions.
    """
    user_id = current_user.get("sub", "")
    role = current_user.get("role", "")

    # Anonymous users don't have a DB record
    if role == UserRole.ANONYMOUS.value or str(user_id).startswith("anon:"):
        return {
            "id": user_id,
            "role": role,
            "is_anonymous": True,
        }

    # Real users — look up in MongoDB
    db = request.app.state.mongo_client[request.app.state.mongo_db_name]
    try:
        doc = await db["users"].find_one({"_id": ObjectId(user_id)})
    except Exception:
        doc = None

    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    profile_data = doc.get("profile") or {}
    has_full_name = bool(profile_data.get("full_name") if isinstance(profile_data, dict) else getattr(profile_data, "full_name", None))

    return UserOut(
        id=str(doc["_id"]),
        phone=doc["phone"],
        email=doc.get("email"),
        email_verified=doc.get("email_verified", False),
        role=UserRole(doc["role"]),
        is_active=doc.get("is_active", True),
        profile=profile_data if profile_data else None,
        profile_complete=has_full_name,
        created_at=doc["created_at"],
    )


# ── GET /auth/admin-only — role guard example ─────────────────────────────────

@router.get(
    "/admin-only",
    summary="Admin-only endpoint (demonstrates require_role guard)",
    tags=["Authentication", "Admin"],
)
async def admin_only_endpoint(
    current_user: dict = Depends(require_role(["admin"])),
):
    """
    This endpoint can ONLY be called by users with role='admin'.
    Any other role receives HTTP 403 Forbidden automatically.
    This is the pattern all admin routes will use in Module 12.
    """
    return {
        "message": "Welcome, admin!",
        "user_id": current_user.get("sub"),
        "role": current_user.get("role"),
    }
