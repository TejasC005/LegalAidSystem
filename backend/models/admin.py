# backend/models/admin.py
"""
LEXIS — Admin & Collections Schemas
-----------------------------------
Pydantic models for:
  1. Multi-admin team management (creation, listing, status/password updates)
  2. MongoDB collection explorer and management
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, EmailStr


class CreateAdminRequest(BaseModel):
    """Request schema for creating a new administrator."""
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=256, description="Plaintext admin password")
    full_name: Optional[str] = Field(None, max_length=120, description="Optional admin full name")


class UpdateAdminStatusRequest(BaseModel):
    """Request schema for updating an administrator's active status."""
    is_active: bool


class UpdateAdminPasswordRequest(BaseModel):
    """Request schema for updating an administrator's password."""
    password: str = Field(..., min_length=6, max_length=256, description="New plaintext admin password")


class AdminUserOut(BaseModel):
    """Public representation of an administrator account."""
    id: str
    email: str
    full_name: Optional[str] = None
    role: str = "admin"
    is_active: bool = True
    created_at: str
    updated_at: Optional[str] = None


class CollectionSummary(BaseModel):
    """Metadata summary of a MongoDB collection."""
    name: str
    document_count: int
    indexes_count: int = 0
    is_system: bool = False


class CreateCollectionRequest(BaseModel):
    """Request schema for creating a new custom MongoDB collection."""
    name: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_\-]+$")
    description: Optional[str] = Field(None, max_length=255)


class CollectionDocumentsResponse(BaseModel):
    """Paginated documents response for a collection."""
    collection_name: str
    total_documents: int
    skip: int
    limit: int
    documents: List[Dict[str, Any]]
