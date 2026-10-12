"""
=============================================================================
LEXIS — Knowledge Base Models & Schemas (Admin Module)
=============================================================================
Pydantic schemas for admin-managed official legal documents and chunks.
"""

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class KnowledgeDocumentStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    PROCESSING = "processing"
    FAILED = "failed"


class KnowledgeChunk(BaseModel):
    chunk_id: str
    section: str = ""
    title: str = ""
    content: str
    citation: str
    topic: Optional[str] = None


class KnowledgeDocumentListOut(BaseModel):
    id: str
    document_id: str
    title: str
    act_name: str
    topic: str
    jurisdiction: str
    authority: str
    source_url: Optional[str] = None
    version: str
    effective_date: Optional[str] = None
    file_name: str
    file_type: str
    file_size_bytes: int
    file_hash: str
    chunk_count: int
    status: str
    is_active: bool
    error_message: Optional[str] = None
    created_at: str
    updated_at: str


class KnowledgeDocumentOut(BaseModel):
    id: str
    document_id: str
    title: str
    act_name: str
    topic: str
    jurisdiction: str
    authority: str
    source_url: Optional[str] = None
    version: str
    effective_date: Optional[str] = None
    file_name: str
    file_type: str
    file_size_bytes: int
    file_hash: str
    chunk_count: int
    status: str
    is_active: bool
    error_message: Optional[str] = None
    preview_text: Optional[str] = None
    chunks: Optional[List[KnowledgeChunk]] = Field(default_factory=list)
    uploaded_by: str = ""
    created_at: str
    updated_at: str


class KnowledgeDocumentStatusResponse(BaseModel):
    message: str
    document_id: str
    is_active: bool
    status: str
