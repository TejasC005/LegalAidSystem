"""
=============================================================================
LEXIS — Admin Panel API Routes (Module 12)
=============================================================================

WHAT THIS FILE DOES
-------------------
Provides administrative endpoints for platform analytics, user management,
and confirmation agent moderation reviews.

SECURITY & AUTHENTICATION
-------------------------
Every single route in this module is protected by `require_role(["admin"])`
from Module 2.  There is NO separate auth mechanism — re-using the existing
role guard dependency guarantees a single source of truth for authorization.

DATA INTEGRITY
--------------
All analytics metrics are calculated strictly from real MongoDB records in:
  1. `reflection_logs` collection (Module 11 self-correction logs)
  2. `users` collection (Module 2 user documents)

No mock/dummy analytics numbers are generated — empty/zero states are returned
honestly if no log entries exist yet.
"""

import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form, Request, status
from pydantic import BaseModel

from api.dependencies.auth import require_role, get_current_user
from db.database import get_database
from models.knowledge_base import (
    KnowledgeDocumentOut,
    KnowledgeDocumentListOut,
    KnowledgeDocumentStatusResponse,
    KnowledgeChunk,
)
from services.rag.document_processor import (
    validate_kb_file,
    compute_file_hash,
    extract_text_from_kb_file,
    chunk_legal_text,
    prepare_chunk_embeddings,
    index_chunks_in_qdrant,
    remove_document_vectors_from_qdrant,
    DocumentProcessingError,
)
from services.rag.embedder import BGEM3Embedder
from db.qdrant_client import get_qdrant_client
from core.config import get_settings
from bson import ObjectId
from pwdlib import PasswordHash
from models.admin import (
    AdminUserOut,
    CreateAdminRequest,
    UpdateAdminStatusRequest,
    UpdateAdminPasswordRequest,
    CollectionSummary,
    CreateCollectionRequest,
    CollectionDocumentsResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin Panel"])

# Centralized guard for all routes in this router
admin_guard = Depends(require_role(["admin"]))
_password_hash = PasswordHash.recommended()


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic Schemas for Admin API
# ─────────────────────────────────────────────────────────────────────────────

class AgentMetric(BaseModel):
    agent_id: str
    total_queries: int
    passed_queries: int
    failed_queries: int
    fallback_queries: int
    retry_count_total: int
    contradiction_count: int


class AnalyticsOverviewResponse(BaseModel):
    total_sessions_logged: int
    total_agent_evaluations: int
    pass_rate_percentage: float
    fail_rate_percentage: float
    fallback_rate_percentage: float
    total_retries: int
    total_contradictions: int
    agents_evaluated: List[str]


class UserAdminOut(BaseModel):
    id: str
    phone: Optional[str] = None
    email: Optional[str] = None
    role: str
    is_active: bool
    created_at: str


class UserStatusUpdateResponse(BaseModel):
    message: str
    user_id: str
    is_active: bool


class ModerationItem(BaseModel):
    session_id: str
    timestamp: str
    agents_checked: List[str]
    pass_fail: str
    retry_count: int
    rejection_reason: str
    contradiction_caught: Optional[str] = None
    query_length: int
    response_length: int


# ─────────────────────────────────────────────────────────────────────────────
# 1. Analytics Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/analytics/overview",
    response_model=AnalyticsOverviewResponse,
    dependencies=[admin_guard],
    summary="Overview Usage & Reflection Analytics",
)
async def get_analytics_overview(db: Any = Depends(get_database)):
    """
    Returns platform-wide agent reflection metrics aggregated directly from
    the real `reflection_logs` collection.
    """
    collection = db["reflection_logs"]
    
    total_sessions_logged = await collection.count_documents({})
    
    if total_sessions_logged == 0:
        return AnalyticsOverviewResponse(
            total_sessions_logged=0,
            total_agent_evaluations=0,
            pass_rate_percentage=0.0,
            fail_rate_percentage=0.0,
            fallback_rate_percentage=0.0,
            total_retries=0,
            total_contradictions=0,
            agents_evaluated=[],
        )

    pipeline = [
        {
            "$group": {
                "_id": None,
                "total_evaluations": {"$sum": 1},
                "passes": {
                    "$sum": {"$cond": [{"$eq": ["$pass_fail", "pass"]}, 1, 0]}
                },
                "fails": {
                    "$sum": {"$cond": [{"$eq": ["$pass_fail", "fail"]}, 1, 0]}
                },
                "fallbacks": {
                    "$sum": {"$cond": [{"$eq": ["$pass_fail", "fallback"]}, 1, 0]}
                },
                "total_retries": {"$sum": "$retry_count"},
                "total_contradictions": {
                    "$sum": {
                        "$cond": [
                            {"$ne": [{"$ifNull": ["$contradiction_caught", None]}, None]},
                            1,
                            0
                        ]
                    }
                },
            }
        }
    ]

    agg_results = await collection.aggregate(pipeline).to_list(length=1)
    if not agg_results:
        return AnalyticsOverviewResponse(
            total_sessions_logged=0,
            total_agent_evaluations=0,
            pass_rate_percentage=0.0,
            fail_rate_percentage=0.0,
            fallback_rate_percentage=0.0,
            total_retries=0,
            total_contradictions=0,
            agents_evaluated=[],
        )

    data = agg_results[0]
    total_evals = data.get("total_evaluations", 0)
    passes = data.get("passes", 0)
    fails = data.get("fails", 0)
    fallbacks = data.get("fallbacks", 0)

    pass_rate = round((passes / total_evals) * 100, 2) if total_evals > 0 else 0.0
    fail_rate = round((fails / total_evals) * 100, 2) if total_evals > 0 else 0.0
    fallback_rate = round((fallbacks / total_evals) * 100, 2) if total_evals > 0 else 0.0

    distinct_agents = await collection.distinct("agents_checked")

    return AnalyticsOverviewResponse(
        total_sessions_logged=total_sessions_logged,
        total_agent_evaluations=total_evals,
        pass_rate_percentage=pass_rate,
        fail_rate_percentage=fail_rate,
        fallback_rate_percentage=fallback_rate,
        total_retries=data.get("total_retries", 0),
        total_contradictions=data.get("total_contradictions", 0),
        agents_evaluated=[str(a) for a in distinct_agents if a],
    )


@router.get(
    "/analytics/agents",
    response_model=List[AgentMetric],
    dependencies=[admin_guard],
    summary="Per-Agent Analytics Breakdown",
)
async def get_agent_analytics(db: Any = Depends(get_database)):
    """
    Returns breakdown metrics for all 6 agents:
    rights, draft, analyze, scam, filing, vault.
    """
    ALL_AGENTS = ["rights", "draft", "analyze", "scam", "filing", "vault"]
    collection = db["reflection_logs"]

    pipeline = [
        {"$unwind": "$agents_checked"},
        {
            "$group": {
                "_id": "$agents_checked",
                "total_queries": {"$sum": 1},
                "passed_queries": {
                    "$sum": {"$cond": [{"$eq": ["$pass_fail", "pass"]}, 1, 0]}
                },
                "failed_queries": {
                    "$sum": {"$cond": [{"$eq": ["$pass_fail", "fail"]}, 1, 0]}
                },
                "fallback_queries": {
                    "$sum": {"$cond": [{"$eq": ["$pass_fail", "fallback"]}, 1, 0]}
                },
                "retry_count_total": {"$sum": "$retry_count"},
                "contradiction_count": {
                    "$sum": {
                        "$cond": [
                            {"$ne": [{"$ifNull": ["$contradiction_caught", None]}, None]},
                            1,
                            0
                        ]
                    }
                },
            }
        }
    ]

    results_map = {}
    async for doc in collection.aggregate(pipeline):
        agent_key = doc["_id"]
        results_map[agent_key] = AgentMetric(
            agent_id=agent_key,
            total_queries=doc.get("total_queries", 0),
            passed_queries=doc.get("passed_queries", 0),
            failed_queries=doc.get("failed_queries", 0),
            fallback_queries=doc.get("fallback_queries", 0),
            retry_count_total=doc.get("retry_count_total", 0),
            contradiction_count=doc.get("contradiction_count", 0),
        )

    # Ensure all 6 agents exist in output even if 0 activity
    agent_metrics = []
    for agent_id in ALL_AGENTS:
        if agent_id in results_map:
            agent_metrics.append(results_map[agent_id])
        else:
            agent_metrics.append(
                AgentMetric(
                    agent_id=agent_id,
                    total_queries=0,
                    passed_queries=0,
                    failed_queries=0,
                    fallback_queries=0,
                    retry_count_total=0,
                    contradiction_count=0,
                )
            )

    return agent_metrics


# ─────────────────────────────────────────────────────────────────────────────
# 2. User Management Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/users",
    response_model=List[UserAdminOut],
    dependencies=[admin_guard],
    summary="List All Users",
)
async def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Any = Depends(get_database),
):
    """
    Lists users registered in MongoDB with role and active status.
    """
    users_collection = db["users"]
    cursor = users_collection.find({}).skip(skip).limit(limit)

    users_list = []
    async for u in cursor:
        created_at_val = u.get("created_at")
        if isinstance(created_at_val, datetime):
            created_at_str = created_at_val.isoformat()
        else:
            created_at_str = str(created_at_val or "")

        users_list.append(
            UserAdminOut(
                id=str(u.get("_id")),
                phone=u.get("phone"),
                email=u.get("email"),
                role=str(u.get("role", "user")),
                is_active=bool(u.get("is_active", True)),
                created_at=created_at_str,
            )
        )

    return users_list


@router.patch(
    "/users/{user_id}/suspend",
    response_model=UserStatusUpdateResponse,
    dependencies=[admin_guard],
    summary="Suspend a User Account",
)
async def suspend_user(user_id: str, db: Any = Depends(get_database)):
    """
    Sets user `is_active = False`. Suspended users cannot authenticate.
    """
    from bson import ObjectId
    users_collection = db["users"]

    try:
        obj_id = ObjectId(user_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid user_id format: '{user_id}'",
        )

    result = await users_collection.update_one(
        {"_id": obj_id},
        {"$set": {"is_active": False, "updated_at": datetime.now(timezone.utc)}},
    )

    if result.matched_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with ID '{user_id}' not found.",
        )

    logger.info("Admin suspended user %s", user_id)
    return UserStatusUpdateResponse(
        message="User account suspended successfully.",
        user_id=user_id,
        is_active=False,
    )


@router.patch(
    "/users/{user_id}/reactivate",
    response_model=UserStatusUpdateResponse,
    dependencies=[admin_guard],
    summary="Reactivate a Suspended User Account",
)
async def reactivate_user(user_id: str, db: Any = Depends(get_database)):
    """
    Sets user `is_active = True`.
    """
    from bson import ObjectId
    users_collection = db["users"]

    try:
        obj_id = ObjectId(user_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid user_id format: '{user_id}'",
        )

    result = await users_collection.update_one(
        {"_id": obj_id},
        {"$set": {"is_active": True, "updated_at": datetime.now(timezone.utc)}},
    )

    if result.matched_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with ID '{user_id}' not found.",
        )

    logger.info("Admin reactivated user %s", user_id)
    return UserStatusUpdateResponse(
        message="User account reactivated successfully.",
        user_id=user_id,
        is_active=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Moderation Queue Endpoint
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/moderation/queue",
    response_model=List[ModerationItem],
    dependencies=[admin_guard],
    summary="Moderation Queue — Surfacing Confirmation Failures",
)
async def get_moderation_queue(
    limit: int = Query(50, ge=1, le=100),
    db: Any = Depends(get_database),
):
    """
    Surfaces reflection logs where pass_fail == 'fallback'
    (Confirmation Agent retries failed repeatedly up to max_retries).
    Requires human admin review.
    """
    collection = db["reflection_logs"]
    cursor = collection.find({"pass_fail": "fallback"}).sort("timestamp", -1).limit(limit)

    queue = []
    async for doc in cursor:
        queue.append(
            ModerationItem(
                session_id=str(doc.get("session_id", "")),
                timestamp=str(doc.get("timestamp", "")),
                agents_checked=doc.get("agents_checked", []),
                pass_fail=str(doc.get("pass_fail", "fallback")),
                retry_count=int(doc.get("retry_count", 0)),
                rejection_reason=str(doc.get("rejection_reason", "")),
                contradiction_caught=doc.get("contradiction_caught"),
                query_length=int(doc.get("query_length", 0)),
                response_length=int(doc.get("response_length", 0)),
            )
        )

    return queue


# ─────────────────────────────────────────────────────────────────────────────
# 4. Legal Knowledge Base Endpoints (Rights Agent RAG Knowledge Base)
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/knowledge-base/upload",
    response_model=KnowledgeDocumentOut,
    dependencies=[admin_guard],
    summary="Upload and Index Official Legal Document",
)
async def upload_knowledge_base_document(
    file: UploadFile = File(..., description="Official legal document (.pdf, .docx, .json)"),
    title: Optional[str] = Form(None),
    act_name: Optional[str] = Form(None),
    topic: Optional[str] = Form(None),
    jurisdiction: Optional[str] = Form("India"),
    authority: Optional[str] = Form(None),
    source_url: Optional[str] = Form(None),
    version: Optional[str] = Form("1.0"),
    effective_date: Optional[str] = Form(None),
    auto_activate: bool = Form(True),
    current_user: dict = Depends(get_current_user),
    db: Any = Depends(get_database),
):
    """
    Uploads an official legal document (.pdf, .docx, or .json), extracts text,
    splits into structured legal chunks, generates BGE-M3 embeddings, and
    indexes them into Qdrant for retrieval by the Rights Agent.
    """
    settings = get_settings()

    try:
        file_bytes = await file.read()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not read uploaded file: {exc}",
        )

    # 1. Validation & Magic Byte verification
    try:
        file_type = validate_kb_file(file_bytes, file.filename or "document", file.content_type or "")
    except DocumentProcessingError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    # 2. Duplicate Detection via SHA-256
    file_hash = compute_file_hash(file_bytes)
    existing_doc = await db["knowledge_base_documents"].find_one({"file_hash": file_hash})
    if existing_doc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"This exact document has already been uploaded with ID '{existing_doc.get('document_id')}' "
                f"and title '{existing_doc.get('title')}'. Reprocess the existing document or upload a revised version."
            ),
        )

    document_id = f"doc_{uuid.uuid4().hex[:12]}"

    # 3. Extract text
    try:
        raw_text = extract_text_from_kb_file(file_bytes, file_type)
    except DocumentProcessingError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    # 4. Normalize metadata
    clean_filename = "".join(c for c in (file.filename or "document") if c.isalnum() or c in "._- ")
    stem_name = Path(clean_filename).stem.replace("_", " ").title()
    doc_title = (title or "").strip() or stem_name
    doc_act = (act_name or "").strip() or doc_title
    doc_topic = (topic or "").strip() or "Citizen Rights"
    doc_jurisdiction = (jurisdiction or "").strip() or "India"
    doc_authority = (authority or "").strip() or "Official Legal Authority"
    doc_version = (version or "").strip() or "1.0"
    doc_effective_date = (effective_date or "").strip() or None
    doc_source_url = (source_url or "").strip() or None

    # 5. Chunk text
    try:
        chunks = chunk_legal_text(
            raw_text=raw_text,
            file_type=file_type,
            act_name=doc_act,
            topic=doc_topic,
            title=doc_title,
            document_id=document_id,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Failed to chunk legal document: {exc}",
        )

    if not chunks:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No valid text chunks could be extracted from this document.",
        )

    # 6. Save raw file safely to disk
    storage_base = Path("data/knowledge_base/uploads") / document_id
    storage_base.mkdir(parents=True, exist_ok=True)
    stored_file_path = storage_base / clean_filename
    try:
        stored_file_path.write_bytes(file_bytes)
    except Exception as exc:
        logger.error("Failed to store KB file on disk: %s", exc)

    # 7. Generate embeddings and index in Qdrant if auto_activate
    embedder = BGEM3Embedder()
    chunks, embeddings = prepare_chunk_embeddings(chunks, embedder)

    qdrant_client = get_qdrant_client()
    collection_name = settings.QDRANT_COLLECTION_NAME

    doc_status = "active" if auto_activate else "inactive"
    is_active_flag = bool(auto_activate)

    if is_active_flag:
        try:
            index_chunks_in_qdrant(
                client=qdrant_client,
                collection_name=collection_name,
                document_id=document_id,
                chunks=chunks,
                embeddings=embeddings,
                metadata={
                    "topic": doc_topic,
                    "act_name": doc_act,
                    "title": doc_title,
                    "file_name": clean_filename,
                    "authority": doc_authority,
                    "source_url": doc_source_url or "",
                    "jurisdiction": doc_jurisdiction,
                    "version": doc_version,
                    "effective_date": doc_effective_date or "",
                },
                is_active=True,
            )
        except Exception as exc:
            logger.error("Failed to index chunks into Qdrant: %s", exc)
            doc_status = "failed"
            is_active_flag = False

    # 8. Record in MongoDB
    now_iso = datetime.now(timezone.utc).isoformat()
    preview = raw_text[:1200] if file_type != "json" else (chunks[0]["content"][:1200] if chunks else "")

    doc_record = {
        "document_id": document_id,
        "title": doc_title,
        "act_name": doc_act,
        "topic": doc_topic,
        "jurisdiction": doc_jurisdiction,
        "authority": doc_authority,
        "source_url": doc_source_url,
        "version": doc_version,
        "effective_date": doc_effective_date,
        "file_name": clean_filename,
        "file_type": file_type,
        "file_size_bytes": len(file_bytes),
        "file_hash": file_hash,
        "file_path": str(stored_file_path),
        "chunk_count": len(chunks),
        "chunks": chunks,
        "preview_text": preview,
        "status": doc_status,
        "is_active": is_active_flag,
        "error_message": None if doc_status != "failed" else "Vector indexing failed",
        "uploaded_by": current_user.get("sub", "admin"),
        "created_at": now_iso,
        "updated_at": now_iso,
    }

    insert_result = await db["knowledge_base_documents"].insert_one(doc_record)
    doc_record["_id"] = insert_result.inserted_id

    return KnowledgeDocumentOut(
        id=str(doc_record["_id"]),
        document_id=doc_record["document_id"],
        title=doc_record["title"],
        act_name=doc_record["act_name"],
        topic=doc_record["topic"],
        jurisdiction=doc_record["jurisdiction"],
        authority=doc_record["authority"],
        source_url=doc_record["source_url"],
        version=doc_record["version"],
        effective_date=doc_record["effective_date"],
        file_name=doc_record["file_name"],
        file_type=doc_record["file_type"],
        file_size_bytes=doc_record["file_size_bytes"],
        file_hash=doc_record["file_hash"],
        chunk_count=doc_record["chunk_count"],
        status=doc_record["status"],
        is_active=doc_record["is_active"],
        error_message=doc_record["error_message"],
        preview_text=doc_record["preview_text"],
        chunks=[KnowledgeChunk(**c) for c in doc_record["chunks"]],
        uploaded_by=doc_record["uploaded_by"],
        created_at=doc_record["created_at"],
        updated_at=doc_record["updated_at"],
    )


@router.get(
    "/knowledge-base/documents",
    response_model=List[KnowledgeDocumentListOut],
    dependencies=[admin_guard],
    summary="List All Legal Knowledge Base Documents",
)
async def list_knowledge_base_documents(
    db: Any = Depends(get_database),
):
    """
    Returns list of all uploaded legal documents without the full chunk bodies.
    """
    cursor = db["knowledge_base_documents"].find({}, {"chunks": 0, "preview_text": 0}).sort("created_at", -1)
    documents = []
    async for doc in cursor:
        documents.append(
            KnowledgeDocumentListOut(
                id=str(doc.get("_id")),
                document_id=doc.get("document_id", ""),
                title=doc.get("title", ""),
                act_name=doc.get("act_name", ""),
                topic=doc.get("topic", ""),
                jurisdiction=doc.get("jurisdiction", "India"),
                authority=doc.get("authority", ""),
                source_url=doc.get("source_url"),
                version=doc.get("version", "1.0"),
                effective_date=doc.get("effective_date"),
                file_name=doc.get("file_name", ""),
                file_type=doc.get("file_type", ""),
                file_size_bytes=doc.get("file_size_bytes", 0),
                file_hash=doc.get("file_hash", ""),
                chunk_count=doc.get("chunk_count", 0),
                status=doc.get("status", "inactive"),
                is_active=bool(doc.get("is_active", False)),
                error_message=doc.get("error_message"),
                created_at=str(doc.get("created_at", "")),
                updated_at=str(doc.get("updated_at", "")),
            )
        )
    return documents


@router.get(
    "/knowledge-base/documents/{document_id}",
    response_model=KnowledgeDocumentOut,
    dependencies=[admin_guard],
    summary="Get Full Legal Document Details and Chunks",
)
async def get_knowledge_base_document(
    document_id: str,
    db: Any = Depends(get_database),
):
    """
    Returns the complete document details including extracted text preview and all chunks.
    """
    doc = await db["knowledge_base_documents"].find_one({"document_id": document_id})
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found.",
        )

    chunks_data = [KnowledgeChunk(**c) for c in doc.get("chunks", [])]

    return KnowledgeDocumentOut(
        id=str(doc.get("_id")),
        document_id=doc.get("document_id", ""),
        title=doc.get("title", ""),
        act_name=doc.get("act_name", ""),
        topic=doc.get("topic", ""),
        jurisdiction=doc.get("jurisdiction", "India"),
        authority=doc.get("authority", ""),
        source_url=doc.get("source_url"),
        version=doc.get("version", "1.0"),
        effective_date=doc.get("effective_date"),
        file_name=doc.get("file_name", ""),
        file_type=doc.get("file_type", ""),
        file_size_bytes=doc.get("file_size_bytes", 0),
        file_hash=doc.get("file_hash", ""),
        chunk_count=doc.get("chunk_count", 0),
        status=doc.get("status", "inactive"),
        is_active=bool(doc.get("is_active", False)),
        error_message=doc.get("error_message"),
        preview_text=doc.get("preview_text"),
        chunks=chunks_data,
        uploaded_by=str(doc.get("uploaded_by", "")),
        created_at=str(doc.get("created_at", "")),
        updated_at=str(doc.get("updated_at", "")),
    )


@router.post(
    "/knowledge-base/documents/{document_id}/activate",
    response_model=KnowledgeDocumentStatusResponse,
    dependencies=[admin_guard],
    summary="Activate Legal Document (Indexes into Qdrant)",
)
async def activate_knowledge_base_document(
    document_id: str,
    db: Any = Depends(get_database),
):
    """
    Activates the legal document and ensures its vectors are indexed into Qdrant.
    """
    doc = await db["knowledge_base_documents"].find_one({"document_id": document_id})
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found.",
        )

    settings = get_settings()
    qdrant_client = get_qdrant_client()
    chunks = doc.get("chunks", [])

    if chunks:
        embedder = BGEM3Embedder()
        chunks, embeddings = prepare_chunk_embeddings(chunks, embedder)
        index_chunks_in_qdrant(
            client=qdrant_client,
            collection_name=settings.QDRANT_COLLECTION_NAME,
            document_id=document_id,
            chunks=chunks,
            embeddings=embeddings,
            metadata=doc,
            is_active=True,
        )

    now_iso = datetime.now(timezone.utc).isoformat()
    await db["knowledge_base_documents"].update_one(
        {"document_id": document_id},
        {"$set": {"status": "active", "is_active": True, "error_message": None, "updated_at": now_iso}},
    )

    return KnowledgeDocumentStatusResponse(
        message="Document activated and indexed into Qdrant.",
        document_id=document_id,
        is_active=True,
        status="active",
    )


@router.post(
    "/knowledge-base/documents/{document_id}/deactivate",
    response_model=KnowledgeDocumentStatusResponse,
    dependencies=[admin_guard],
    summary="Deactivate Legal Document (Removes Vectors from Qdrant)",
)
async def deactivate_knowledge_base_document(
    document_id: str,
    db: Any = Depends(get_database),
):
    """
    Deactivates the legal document and safely removes its vectors from Qdrant,
    ensuring it is no longer returned in citizen searches.
    """
    doc = await db["knowledge_base_documents"].find_one({"document_id": document_id})
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found.",
        )

    settings = get_settings()
    qdrant_client = get_qdrant_client()
    remove_document_vectors_from_qdrant(qdrant_client, settings.QDRANT_COLLECTION_NAME, document_id)

    now_iso = datetime.now(timezone.utc).isoformat()
    await db["knowledge_base_documents"].update_one(
        {"document_id": document_id},
        {"$set": {"status": "inactive", "is_active": False, "updated_at": now_iso}},
    )

    return KnowledgeDocumentStatusResponse(
        message="Document deactivated and vectors safely removed from Qdrant.",
        document_id=document_id,
        is_active=False,
        status="inactive",
    )


@router.delete(
    "/knowledge-base/documents/{document_id}",
    dependencies=[admin_guard],
    summary="Delete Legal Document and Associated Vectors",
)
async def delete_knowledge_base_document(
    document_id: str,
    db: Any = Depends(get_database),
):
    """
    Permanently deletes the legal document, cleans its vectors from Qdrant,
    and removes the file from disk.
    """
    doc = await db["knowledge_base_documents"].find_one({"document_id": document_id})
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found.",
        )

    settings = get_settings()
    qdrant_client = get_qdrant_client()
    remove_document_vectors_from_qdrant(qdrant_client, settings.QDRANT_COLLECTION_NAME, document_id)

    file_path = doc.get("file_path")
    if file_path:
        try:
            p = Path(file_path)
            if p.exists():
                p.unlink()
            if p.parent.exists() and not any(p.parent.iterdir()):
                p.parent.rmdir()
        except Exception as exc:
            logger.warning("Could not delete stored file on disk: %s", exc)

    await db["knowledge_base_documents"].delete_one({"document_id": document_id})

    return {
        "message": "Legal document and associated vectors deleted successfully.",
        "document_id": document_id,
    }


@router.post(
    "/knowledge-base/documents/{document_id}/reprocess",
    response_model=KnowledgeDocumentOut,
    dependencies=[admin_guard],
    summary="Reprocess Legal Document from Disk",
)
async def reprocess_knowledge_base_document(
    document_id: str,
    db: Any = Depends(get_database),
):
    """
    Re-extracts text, re-chunks, and re-indexes a document using the stored file.
    Useful for resolving failed ingestions.
    """
    doc = await db["knowledge_base_documents"].find_one({"document_id": document_id})
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found.",
        )

    file_path_str = doc.get("file_path")
    if not file_path_str or not Path(file_path_str).exists():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Stored document file is missing on disk. Please upload the file again.",
        )

    file_path = Path(file_path_str)
    file_bytes = file_path.read_bytes()
    file_type = doc.get("file_type", "pdf")

    try:
        raw_text = extract_text_from_kb_file(file_bytes, file_type)
        chunks = chunk_legal_text(
            raw_text=raw_text,
            file_type=file_type,
            act_name=doc.get("act_name", ""),
            topic=doc.get("topic", "Citizen Rights"),
            title=doc.get("title", ""),
            document_id=document_id,
        )

        embedder = BGEM3Embedder()
        chunks, embeddings = prepare_chunk_embeddings(chunks, embedder)

        settings = get_settings()
        qdrant_client = get_qdrant_client()
        remove_document_vectors_from_qdrant(qdrant_client, settings.QDRANT_COLLECTION_NAME, document_id)

        index_chunks_in_qdrant(
            client=qdrant_client,
            collection_name=settings.QDRANT_COLLECTION_NAME,
            document_id=document_id,
            chunks=chunks,
            embeddings=embeddings,
            metadata=doc,
            is_active=True,
        )

        now_iso = datetime.now(timezone.utc).isoformat()
        preview = raw_text[:1200] if file_type != "json" else (chunks[0]["content"][:1200] if chunks else "")

        await db["knowledge_base_documents"].update_one(
            {"document_id": document_id},
            {
                "$set": {
                    "chunks": chunks,
                    "chunk_count": len(chunks),
                    "preview_text": preview,
                    "status": "active",
                    "is_active": True,
                    "error_message": None,
                    "updated_at": now_iso,
                }
            },
        )

        updated_doc = await db["knowledge_base_documents"].find_one({"document_id": document_id})
        return KnowledgeDocumentOut(
            id=str(updated_doc["_id"]),
            document_id=updated_doc["document_id"],
            title=updated_doc["title"],
            act_name=updated_doc["act_name"],
            topic=updated_doc["topic"],
            jurisdiction=updated_doc["jurisdiction"],
            authority=updated_doc["authority"],
            source_url=updated_doc["source_url"],
            version=updated_doc["version"],
            effective_date=updated_doc["effective_date"],
            file_name=updated_doc["file_name"],
            file_type=updated_doc["file_type"],
            file_size_bytes=updated_doc["file_size_bytes"],
            file_hash=updated_doc["file_hash"],
            chunk_count=updated_doc["chunk_count"],
            status=updated_doc["status"],
            is_active=updated_doc["is_active"],
            error_message=updated_doc["error_message"],
            preview_text=updated_doc["preview_text"],
            chunks=[KnowledgeChunk(**c) for c in updated_doc["chunks"]],
            uploaded_by=updated_doc["uploaded_by"],
            created_at=updated_doc["created_at"],
            updated_at=updated_doc["updated_at"],
        )

    except Exception as exc:
        logger.error("Reprocessing failed for document '%s': %s", document_id, exc)
        now_iso = datetime.now(timezone.utc).isoformat()
        await db["knowledge_base_documents"].update_one(
            {"document_id": document_id},
            {"$set": {"status": "failed", "is_active": False, "error_message": str(exc), "updated_at": now_iso}},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Reprocessing failed: {exc}",
        )


# ─────────────────────────────────────────────────────────────────────────────
# 5. Multi-Admin Team Management Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/admins",
    response_model=List[AdminUserOut],
    dependencies=[admin_guard],
    summary="List All Platform Administrators",
)
async def list_admins(db: Any = Depends(get_database)):
    """Returns all accounts configured with role='admin' in MongoDB."""
    cursor = db["users"].find({"role": "admin"}).sort("created_at", -1)
    admin_docs = await cursor.to_list(length=100)

    result = []
    for doc in admin_docs:
        full_name = None
        if isinstance(doc.get("profile"), dict):
            full_name = doc["profile"].get("full_name")
        elif doc.get("full_name"):
            full_name = doc["full_name"]

        result.append(
            AdminUserOut(
                id=str(doc["_id"]),
                email=str(doc.get("email") or ""),
                full_name=full_name,
                role="admin",
                is_active=bool(doc.get("is_active", True)),
                created_at=str(doc.get("created_at") or ""),
                updated_at=str(doc.get("updated_at") or "") if doc.get("updated_at") else None,
            )
        )
    return result


@router.post(
    "/admins",
    response_model=AdminUserOut,
    dependencies=[admin_guard],
    status_code=status.HTTP_201_CREATED,
    summary="Create a New Platform Administrator",
)
async def create_admin(body: CreateAdminRequest, db: Any = Depends(get_database)):
    """Creates a new administrator account with individual hashed credentials."""
    email_clean = str(body.email).strip().lower()

    # Check if user already exists
    existing = await db["users"].find_one({"email": email_clean})
    if existing:
        if existing.get("role") == "admin":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"An administrator account with email '{email_clean}' already exists.",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A user with email '{email_clean}' already exists as role '{existing.get('role')}'. Update role instead.",
        )

    # Hash password with Argon2id
    password_hash = _password_hash.hash(body.password)
    now = datetime.now(timezone.utc)

    admin_doc = {
        "_id": ObjectId(),
        "email": email_clean,
        "role": "admin",
        "password_hash": password_hash,
        "is_active": True,
        "is_anonymous": False,
        "email_verified": True,
        "profile": {"full_name": body.full_name} if body.full_name else {},
        "created_at": now,
        "updated_at": now,
    }

    await db["users"].insert_one(admin_doc)
    logger.info("Admin created new administrator: %s", email_clean)

    return AdminUserOut(
        id=str(admin_doc["_id"]),
        email=email_clean,
        full_name=body.full_name,
        role="admin",
        is_active=True,
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
    )


@router.patch(
    "/admins/{admin_id}/status",
    response_model=AdminUserOut,
    dependencies=[admin_guard],
    summary="Update Administrator Active Status",
)
async def update_admin_status(
    admin_id: str,
    body: UpdateAdminStatusRequest,
    current_user: dict = Depends(get_current_user),
    db: Any = Depends(get_database),
):
    """Enables or disables an admin account. Admins cannot deactivate themselves."""
    if not ObjectId.is_valid(admin_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid admin ID format: '{admin_id}'.",
        )

    # Prevent self-deactivation
    caller_id = str(current_user.get("user_id") or current_user.get("id") or "")
    if caller_id == admin_id and not body.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot deactivate your own administrator account.",
        )

    target_oid = ObjectId(admin_id)
    existing = await db["users"].find_one({"_id": target_oid, "role": "admin"})
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Administrator with ID '{admin_id}' not found.",
        )

    now = datetime.now(timezone.utc)
    await db["users"].update_one(
        {"_id": target_oid},
        {"$set": {"is_active": body.is_active, "updated_at": now}},
    )

    updated = await db["users"].find_one({"_id": target_oid})
    full_name = None
    if isinstance(updated.get("profile"), dict):
        full_name = updated["profile"].get("full_name")
    elif updated.get("full_name"):
        full_name = updated["full_name"]

    return AdminUserOut(
        id=str(updated["_id"]),
        email=str(updated.get("email") or ""),
        full_name=full_name,
        role="admin",
        is_active=bool(updated.get("is_active", True)),
        created_at=str(updated.get("created_at") or ""),
        updated_at=now.isoformat(),
    )


@router.patch(
    "/admins/{admin_id}/password",
    response_model=Dict[str, str],
    dependencies=[admin_guard],
    summary="Reset Administrator Password",
)
async def reset_admin_password(
    admin_id: str,
    body: UpdateAdminPasswordRequest,
    db: Any = Depends(get_database),
):
    """Updates an administrator's password with a new Argon2id hash."""
    if not ObjectId.is_valid(admin_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid admin ID format: '{admin_id}'.",
        )

    target_oid = ObjectId(admin_id)
    existing = await db["users"].find_one({"_id": target_oid, "role": "admin"})
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Administrator with ID '{admin_id}' not found.",
        )

    new_hash = _password_hash.hash(body.password)
    now = datetime.now(timezone.utc)

    await db["users"].update_one(
        {"_id": target_oid},
        {"$set": {"password_hash": new_hash, "updated_at": now}},
    )

    logger.info("Admin password reset for user ID: %s", admin_id)
    return {"message": "Administrator password updated successfully.", "admin_id": admin_id}


# ─────────────────────────────────────────────────────────────────────────────
# 6. MongoDB Database Collections Explorer Endpoints
# ─────────────────────────────────────────────────────────────────────────────

PROTECTED_CORE_COLLECTIONS = {
    "users",
    "reflection_logs",
    "scam_patterns",
    "scam_candidates",
    "scam_submissions",
    "vault_documents",
    "user_drafts",
    "knowledge_base_documents",
}


SENSITIVE_REDACT_KEYS = {"password_hash", "password"}


def _serialize_mongo_doc(doc: Any) -> Any:
    """Helper to convert MongoDB documents into standard JSON-serializable types and mask secrets."""
    if isinstance(doc, dict):
        serialized = {}
        for k, v in doc.items():
            if k in SENSITIVE_REDACT_KEYS:
                serialized[k] = "[REDACTED]"
            else:
                serialized[k] = _serialize_mongo_doc(v)
        return serialized
    if isinstance(doc, list):
        return [_serialize_mongo_doc(item) for item in doc]
    if isinstance(doc, ObjectId):
        return str(doc)
    if isinstance(doc, datetime):
        return doc.isoformat()
    if isinstance(doc, bytes):
        return f"<binary data {len(doc)} bytes>"
    return doc


@router.get(
    "/collections",
    response_model=List[CollectionSummary],
    dependencies=[admin_guard],
    summary="List All MongoDB Collections in Database",
)
async def list_collections(db: Any = Depends(get_database)):
    """Returns all collection names in the active database with document and index counts."""
    collection_names = await db.list_collection_names()
    collection_names.sort()

    summaries = []
    for name in collection_names:
        is_system = name.startswith("system.") or name in PROTECTED_CORE_COLLECTIONS
        try:
            doc_count = await db[name].count_documents({})
        except Exception:
            doc_count = 0

        try:
            indexes = await db[name].index_information()
            indexes_count = len(indexes)
        except Exception:
            indexes_count = 0

        summaries.append(
            CollectionSummary(
                name=name,
                document_count=doc_count,
                indexes_count=indexes_count,
                is_system=is_system,
            )
        )
    return summaries


@router.post(
    "/collections",
    response_model=CollectionSummary,
    dependencies=[admin_guard],
    status_code=status.HTTP_201_CREATED,
    summary="Create a New MongoDB Collection",
)
async def create_collection(
    body: CreateCollectionRequest,
    db: Any = Depends(get_database),
):
    """Creates a new collection in the active database."""
    name_clean = body.name.strip()
    existing_cols = await db.list_collection_names()

    if name_clean in existing_cols:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Collection '{name_clean}' already exists in the database.",
        )

    try:
        await db.create_collection(name_clean)
        logger.info("Admin created new MongoDB collection: %s", name_clean)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create collection '{name_clean}': {exc}",
        )

    return CollectionSummary(
        name=name_clean,
        document_count=0,
        indexes_count=1,  # Default _id_ index created by MongoDB
        is_system=False,
    )


@router.get(
    "/collections/{collection_name}/documents",
    response_model=CollectionDocumentsResponse,
    dependencies=[admin_guard],
    summary="Inspect Documents in a Collection",
)
async def get_collection_documents(
    collection_name: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    db: Any = Depends(get_database),
):
    """Returns paginated JSON documents from any collection in the database."""
    existing_cols = await db.list_collection_names()
    if collection_name not in existing_cols:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Collection '{collection_name}' does not exist.",
        )

    total = await db[collection_name].count_documents({})
    cursor = db[collection_name].find().skip(skip).limit(limit)
    raw_docs = await cursor.to_list(length=limit)

    serialized = [_serialize_mongo_doc(d) for d in raw_docs]

    return CollectionDocumentsResponse(
        collection_name=collection_name,
        total_documents=total,
        skip=skip,
        limit=limit,
        documents=serialized,
    )


@router.delete(
    "/collections/{collection_name}",
    response_model=Dict[str, str],
    dependencies=[admin_guard],
    summary="Drop a Custom Collection",
)
async def drop_custom_collection(
    collection_name: str,
    db: Any = Depends(get_database),
):
    """Drops a custom collection. Protected core system collections cannot be dropped."""
    if collection_name in PROTECTED_CORE_COLLECTIONS or collection_name.startswith("system."):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot drop protected core collection '{collection_name}'.",
        )

    existing_cols = await db.list_collection_names()
    if collection_name not in existing_cols:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Collection '{collection_name}' does not exist.",
        )

    try:
        await db.drop_collection(collection_name)
        logger.info("Admin dropped custom collection: %s", collection_name)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to drop collection '{collection_name}': {exc}",
        )

    return {"message": f"Collection '{collection_name}' was successfully dropped."}

