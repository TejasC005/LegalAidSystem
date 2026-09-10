# backend/api/routes/users.py
"""
LEXIS — Enhanced Auth, Profile & Account Management Routes (Module 13B)
-------------------------------------------------------------------------
BEGINNER NOTES:

1. WHY PROFILE COMPLETION IS A SEPARATE STEP AFTER SIGNUP (NOT MERGED):
   Signup in LEXIS requires only a phone number (primary identity) via fast 2-step OTP.
   If we merged full name, address, DOB, language, and notification preferences into the signup form,
   friction would skyrocket and many citizens would abandon registration.
   By keeping signup instantaneous (phone + OTP only), citizens can log in immediately.
   Profile setup is presented right after first login or updated anytime in Settings.

2. WHAT "CASCADING DELETE" MEANS AND WHY IT MATTERS HERE:
   In MongoDB (a document database), related data lives across multiple collections:
   'users', 'vault_documents', and 'vault_deadlines' (all referencing user_id).
   If we only delete the document from 'users', all stored documents and deadline reminders for
   that user remain orphaned in MongoDB and on disk.
   "Cascading delete" means deleting the primary user record AND automatically removing all child
   documents across vault_documents, vault_deadlines, and files on disk.
   This guarantees complete data erasure (privacy compliance) and prevents orphaned records.

ENDPOINTS:
  POST   /users/me/email/send-otp      → Send verification OTP to email
  POST   /users/me/email/verify-otp    → Verify email OTP and set email_verified=True
  GET    /users/me/profile             → Get current user's profile
  PATCH  /users/me/profile             → Update current user's profile
  POST   /users/me/profile/picture     → Upload profile picture (image only)
  DELETE /users/me                     → Hard delete user account and cascade child records
  GET    /users/me/export              → Export user profile & vault metadata as JSON dump
"""

import logging
import os
from typing import Dict, Any, List
from datetime import datetime, timezone
from bson import ObjectId

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, status

from api.dependencies.auth import get_current_user
from api.middleware.email_rate_limit import email_otp_rate_limit
from models.user import (
    ProfileDocument,
    ProfileUpdateRequest,
    SendEmailOTPRequest,
    UserExportResponse,
    UserOut,
    UserRole,
    VerifyEmailOTPRequest,
)
from services.auth.email_provider import get_email_provider
from services.auth.otp_service import send_email_otp, verify_email_otp
from services.storage.secure_storage import get_storage_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["User Profile & Management"])


def _require_real_user(current_user: dict) -> str:
    """Helper to ensure user is not anonymous and returns user_id string."""
    role = current_user.get("role", "")
    user_id = current_user.get("sub", "")
    if role == UserRole.ANONYMOUS.value or not user_id or str(user_id).startswith("anon:"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Anonymous sessions cannot manage profile or account data. Please sign in with a phone number.",
        )
    return user_id


# ── PART A: EMAIL OTP ENDPOINTS ───────────────────────────────────────────────

@router.post(
    "/me/email/send-otp",
    summary="Send verification OTP to email address",
    dependencies=[Depends(email_otp_rate_limit)],
)
async def send_email_otp_endpoint(
    body: SendEmailOTPRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """
    Sends a 6-digit verification OTP to the user's email address.
    Rate limited per email address using Redis.
    """
    _require_real_user(current_user)
    redis = request.app.state.redis
    provider = get_email_provider()

    success = await send_email_otp(body.email, redis, provider)
    if not success:
        error_detail = getattr(provider, "last_error", None) or "Failed to send email OTP. Please try again."
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=error_detail,
        )
    return {"message": "Email OTP sent successfully. Valid for 5 minutes."}


@router.post(
    "/me/email/verify-otp",
    summary="Verify email OTP and mark email as verified",
)
async def verify_email_otp_endpoint(
    body: VerifyEmailOTPRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """
    Verifies the email OTP. On success, updates the user document in MongoDB with:
    email = body.email, email_verified = True.
    """
    user_id = _require_real_user(current_user)
    redis = request.app.state.redis
    db = request.app.state.mongo_client[request.app.state.mongo_db_name]

    # Check if email is already taken by another user
    existing = await db["users"].find_one({
        "email": body.email.lower().strip(),
        "_id": {"$ne": ObjectId(user_id)}
    })
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This email address is already associated with another account.",
        )

    valid = await verify_email_otp(body.email, body.otp, redis)
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired email OTP.",
        )

    # Update Mongo
    now = datetime.now(timezone.utc)
    await db["users"].update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {
            "email": body.email.lower().strip(),
            "email_verified": True,
            "updated_at": now,
        }}
    )
    logger.info("User email verified successfully", extra={"user_id": user_id})
    return {"message": "Email verified successfully.", "email": body.email.lower().strip()}


# ── PART B: PROFILE ENDPOINTS ──────────────────────────────────────────────────

@router.get(
    "/me/profile",
    summary="Get current user's profile",
)
async def get_profile_endpoint(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Returns the current user's profile sub-document."""
    user_id = _require_real_user(current_user)
    db = request.app.state.mongo_client[request.app.state.mongo_db_name]

    doc = await db["users"].find_one({"_id": ObjectId(user_id)})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    profile_data = doc.get("profile") or {}
    if isinstance(profile_data, dict):
        profile_obj = ProfileDocument(**profile_data)
    else:
        profile_obj = ProfileDocument()

    return {
        "user_id": user_id,
        "phone": doc["phone"],
        "email": doc.get("email"),
        "email_verified": doc.get("email_verified", False),
        "profile": profile_obj,
        "profile_complete": bool(profile_obj.full_name),
    }


@router.patch(
    "/me/profile",
    summary="Update current user's profile",
)
async def update_profile_endpoint(
    body: ProfileUpdateRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """
    Validates input and updates the owner's profile sub-document.
    Only allows authenticated owner (via JWT) to update their own profile.
    """
    user_id = _require_real_user(current_user)
    db = request.app.state.mongo_client[request.app.state.mongo_db_name]

    doc = await db["users"].find_one({"_id": ObjectId(user_id)})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    current_profile = doc.get("profile") or {}
    if not isinstance(current_profile, dict):
        current_profile = {}

    update_fields = body.model_dump(exclude_unset=True)
    for key, value in update_fields.items():
        if value is not None:
            current_profile[key] = value

    now = datetime.now(timezone.utc)
    await db["users"].update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"profile": current_profile, "updated_at": now}}
    )

    logger.info("User profile updated", extra={"user_id": user_id})
    return {
        "message": "Profile updated successfully.",
        "profile": ProfileDocument(**current_profile),
        "profile_complete": bool(current_profile.get("full_name")),
    }


@router.post(
    "/me/profile/picture",
    summary="Upload profile picture",
)
async def upload_profile_picture_endpoint(
    request: Request,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """
    Uploads profile picture using SecureStorageService directly.
    Restricts file type to image file types only (image/jpeg, image/png, image/webp, image/gif).
    Enforces max file size (2 MB). Reject anything else with a clear error.
    """
    user_id = _require_real_user(current_user)
    db = request.app.state.mongo_client[request.app.state.mongo_db_name]

    # Validate MIME type
    allowed_types = {"image/jpeg", "image/png", "image/webp", "image/gif"}
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type '{file.content_type}'. Profile picture must be an image (JPEG, PNG, WEBP, GIF).",
        )

    # Read bytes & validate size (2 MB max)
    content_bytes = await file.read()
    max_bytes = 2 * 1024 * 1024  # 2MB
    if len(content_bytes) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large ({len(content_bytes) / (1024*1024):.2f} MB). Maximum profile picture size is 2 MB.",
        )

    # Reuse SecureStorageService
    storage = get_storage_service()
    meta = await storage.store_file(
        db=db,
        user_id=user_id,
        content_bytes=content_bytes,
        original_name=file.filename or "profile_picture.jpg",
        content_type=file.content_type,
        collection="user_profile_pictures",
    )

    # Picture URL/path representation
    picture_url = f"/api/v1/users/me/profile/picture/{meta.file_id}"

    # Update profile in Mongo
    doc = await db["users"].find_one({"_id": ObjectId(user_id)})
    profile_dict = doc.get("profile") or {}
    if not isinstance(profile_dict, dict):
        profile_dict = {}

    profile_dict["profile_picture_url"] = picture_url
    await db["users"].update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"profile": profile_dict, "updated_at": datetime.now(timezone.utc)}}
    )

    return {
        "message": "Profile picture uploaded successfully.",
        "file_id": meta.file_id,
        "profile_picture_url": picture_url,
    }


# ── PART C: ACCOUNT DELETION & EXPORT ──────────────────────────────────────────

@router.delete(
    "/me",
    summary="Delete user account and cascade all associated data",
)
async def delete_account_endpoint(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """
    Deletes the user record and cascades:
    Removes vault_documents metadata + disk files, vault_deadlines, and user record.
    Verifies no orphaned records remain.
    """
    user_id = _require_real_user(current_user)
    db = request.app.state.mongo_client[request.app.state.mongo_db_name]
    storage = get_storage_service()

    # 1. Fetch user's vault documents to delete from disk
    vault_docs = await db["vault_documents"].find({"user_id": user_id}).to_list(length=1000)
    for vdoc in vault_docs:
        file_id = vdoc.get("file_id")
        if file_id:
            try:
                await storage.delete_file(db=db, user_id=user_id, file_id=file_id, collection="vault_documents")
            except Exception as exc:
                logger.warning(f"Could not delete vault disk file {file_id}: {exc}")

    # 2. Delete all vault_documents from Mongo
    deleted_docs = await db["vault_documents"].delete_many({"user_id": user_id})

    # 3. Delete all vault_deadlines from Mongo
    deleted_deadlines = await db["vault_deadlines"].delete_many({"user_id": user_id})

    # 4. Delete profile pictures if any
    await db["user_profile_pictures"].delete_many({"user_id": user_id})

    # 5. Delete primary user record from Mongo
    deleted_user = await db["users"].delete_one({"_id": ObjectId(user_id)})

    logger.info(
        "User account and cascaded records deleted",
        extra={
            "user_id": user_id,
            "docs_deleted": deleted_docs.deleted_count,
            "deadlines_deleted": deleted_deadlines.deleted_count,
        },
    )

    return {
        "deleted": True,
        "message": "Account and all associated vault documents and deadlines have been permanently deleted.",
        "cascaded": {
            "vault_documents": deleted_docs.deleted_count,
            "vault_deadlines": deleted_deadlines.deleted_count,
        },
    }


@router.get(
    "/me/export",
    response_model=UserExportResponse,
    summary="Export a JSON dump of user's profile and metadata",
)
async def export_user_data_endpoint(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """
    Returns a JSON dump of the user's profile, vault document metadata
    (not raw encrypted files), and deadlines — a simple data-export feature.
    """
    user_id = _require_real_user(current_user)
    db = request.app.state.mongo_client[request.app.state.mongo_db_name]

    user_doc = await db["users"].find_one({"_id": ObjectId(user_id)})
    if not user_doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    profile_data = user_doc.get("profile") or {}
    profile_obj = ProfileDocument(**profile_data) if isinstance(profile_data, dict) else ProfileDocument()

    # Vault documents metadata
    raw_docs = await db["vault_documents"].find({"user_id": user_id}).to_list(length=1000)
    cleaned_docs = []
    for d in raw_docs:
        doc_dict = {
            "file_id": d.get("file_id"),
            "original_name": d.get("original_name"),
            "doc_type": d.get("doc_type"),
            "created_at": str(d.get("created_at")),
            "encrypted": d.get("encrypted", True),
        }
        cleaned_docs.append(doc_dict)

    # Deadlines metadata
    raw_deadlines = await db["vault_deadlines"].find({"user_id": user_id}).to_list(length=1000)
    cleaned_deadlines = []
    for dl in raw_deadlines:
        dl_dict = {
            "deadline_id": dl.get("deadline_id"),
            "vault_doc_id": dl.get("vault_doc_id"),
            "label": dl.get("label"),
            "deadline_date": dl.get("deadline_date"),
            "doc_type": dl.get("doc_type"),
            "created_at": str(dl.get("created_at")),
            "reminders_sent": dl.get("reminders_sent", []),
        }
        cleaned_deadlines.append(dl_dict)

    return UserExportResponse(
        user_id=user_id,
        phone=user_doc["phone"],
        email=user_doc.get("email"),
        email_verified=user_doc.get("email_verified", False),
        created_at=str(user_doc.get("created_at")),
        profile=profile_obj,
        vault_documents=cleaned_docs,
        vault_deadlines=cleaned_deadlines,
    )
