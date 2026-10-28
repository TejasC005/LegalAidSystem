# backend/models/user.py
"""
LEXIS — User Model & Auth Schemas (Module 2)
----------------------------------------------
All Pydantic models related to users and authentication live here.

MongoDB document shape:  UserDocument  (what gets stored)
API request bodies:      SendOTPRequest, VerifyOTPRequest, RefreshRequest
API response bodies:     TokenResponse, UserOut, AnonymousTokenResponse

Why separate "UserDocument" from "UserOut"?
  UserDocument has all DB fields including internal ones (hashed_otp, etc.)
  UserOut is what we *return to the client* — a safe, public-facing subset.
  This pattern prevents accidentally leaking internal data in API responses.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List, Any, Dict
from pydantic import BaseModel, Field, EmailStr, field_validator, model_validator
from bson import ObjectId


# ── Role & Profile enums ──────────────────────────────────────────────────────

class UserRole(str, Enum):
    """
    The three roles in LEXIS.

    user     → Indian citizen using the legal aid features. Functional now.
    admin    → Platform administrator. Sees analytics, manages users. Functional now.
    lawyer   → Future scope. Role + permission boundary exist; no features yet
               until Module 13.
    anonymous → Temporary session identity. Not persisted to DB.
               Cannot use Vault or access history.
    """
    USER = "user"
    ADMIN = "admin"
    LAWYER = "lawyer"
    ANONYMOUS = "anonymous"


class PreferredLanguage(str, Enum):
    """Short fixed list of preferred languages for legal guidance."""
    EN = "en"
    HI = "hi"
    MR = "mr"


class NotificationPreference(str, Enum):
    """Channels through which deadline reminders are sent."""
    SMS = "sms"
    EMAIL = "email"
    BOTH = "both"


# ── Profile sub-document shape ─────────────────────────────────────────────────

class ProfileDocument(BaseModel):
    """Sub-document containing extended citizen profile details."""
    full_name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    preferred_language: Optional[PreferredLanguage] = None
    date_of_birth: Optional[str] = None  # Expected ISO format: YYYY-MM-DD
    id_verified: bool = False
    id_type: Optional[str] = None       # "Aadhaar Card", "PAN Card", etc.
    id_number_masked: Optional[str] = None
    profile_picture_url: Optional[str] = None
    notification_preference: NotificationPreference = NotificationPreference.SMS


# ── MongoDB document shape ─────────────────────────────────────────────────────

class UserDocument(BaseModel):
    """
    Represents a user document as stored in MongoDB.
    Fields marked Optional are set server-side, not by the user.

    Note: We do NOT store passwords. Auth is OTP-based — the phone number
    IS the primary identity, and the OTP proves ownership of that number.
    Email is an optional/secondary verification channel.
    """
    id: Optional[str] = Field(None, alias="_id")
    phone: Optional[str] = None             # E.164 format or None if registering via email
    email: Optional[str] = None             # Email address (primary or secondary channel)
    email_verified: bool = False
    role: UserRole = UserRole.USER
    password_hash: Optional[str] = None
    is_anonymous: bool = False
    is_active: bool = True
    profile: Optional[ProfileDocument] = Field(default_factory=ProfileDocument)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"populate_by_name": True}


# ── Request bodies ─────────────────────────────────────────────────────────────

class SendOTPRequest(BaseModel):
    """Body for POST /auth/send-otp"""
    phone: Optional[str] = Field(
        None,
        pattern=r"^\+?[1-9]\d{9,14}$",
        description="Phone number in E.164 format, e.g. +919876543210",
        examples=["+919876543210"],
    )
    email: Optional[EmailStr] = Field(
        None,
        description="Email address for OTP verification",
        examples=["citizen@example.com"],
    )

    @model_validator(mode="after")
    def check_identifier_provided(self):
        if not self.phone and not self.email:
            raise ValueError("Either email or phone must be provided to send OTP.")
        return self


class VerifyOTPRequest(BaseModel):
    """Body for POST /auth/verify-otp"""
    phone: Optional[str] = Field(None, description="Phone used in send-otp")
    email: Optional[EmailStr] = Field(None, description="Email used in send-otp")
    otp: str = Field(..., min_length=6, max_length=6, description="6-digit OTP")

    @model_validator(mode="after")
    def check_identifier_provided(self):
        if not self.phone and not self.email:
            raise ValueError("Either email or phone must be provided to verify OTP.")
        return self


class VerifyFirebaseTokenRequest(BaseModel):
    """Body for POST /auth/verify-firebase-token"""
    id_token: str = Field(..., description="Firebase ID token from client SDK")
    phone: Optional[str] = Field(None, description="Optional phone number fallback if not in token claims")



class SendEmailOTPRequest(BaseModel):
    """Body for POST /users/me/email/send-otp"""
    email: EmailStr = Field(..., description="Email address to verify")


class VerifyEmailOTPRequest(BaseModel):
    """Body for POST /users/me/email/verify-otp"""
    email: EmailStr = Field(..., description="Email address used in send-otp")
    otp: str = Field(..., min_length=6, max_length=6, description="6-digit OTP")


class ProfileUpdateRequest(BaseModel):
    """Body for PATCH /users/me/profile"""
    full_name: Optional[str] = Field(None, max_length=100)
    address: Optional[str] = Field(None, max_length=500)
    city: Optional[str] = Field(None, max_length=100)
    preferred_language: Optional[PreferredLanguage] = None
    date_of_birth: Optional[str] = Field(None, description="Format: YYYY-MM-DD")
    profile_picture_url: Optional[str] = None
    notification_preference: Optional[NotificationPreference] = None

    @field_validator("date_of_birth")
    @classmethod
    def validate_dob(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("date_of_birth must be a valid date string in YYYY-MM-DD format")
        return v


class RefreshRequest(BaseModel):
    """Body for POST /auth/refresh"""
    refresh_token: str


# ── Response bodies ────────────────────────────────────────────────────────────

class TokenResponse(BaseModel):
    """
    Returned after successful OTP verification (login/signup).
    Contains both the short-lived access token and the longer-lived refresh token.
    """
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    role: UserRole


class AnonymousTokenResponse(BaseModel):
    """Returned when a user starts an anonymous session."""
    access_token: str
    token_type: str = "bearer"
    role: UserRole = UserRole.ANONYMOUS
    session_id: str


class UserOut(BaseModel):
    """
    Safe, public representation of a user.
    Never contains OTPs, hashes, or internal flags.
    """
    id: str
    phone: Optional[str] = None
    email: Optional[str] = None
    email_verified: bool = False
    role: UserRole
    is_active: bool
    profile: Optional[ProfileDocument] = None
    profile_complete: bool = False
    created_at: datetime


class UserExportResponse(BaseModel):
    """Returned by GET /users/me/export — data dump for the citizen."""
    user_id: str
    phone: Optional[str] = None
    email: Optional[str] = None
    email_verified: bool = False
    created_at: str
    profile: Optional[ProfileDocument] = None
    vault_documents: List[Dict[str, Any]] = Field(default_factory=list)
    vault_deadlines: List[Dict[str, Any]] = Field(default_factory=list)

# Admin login request model for POST /auth/admin-login
class AdminLoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=256)