"""
=============================================================================
LEXIS — Document Analysis API Routes (Module 7)
=============================================================================

Endpoints:
  POST /api/v1/analysis/upload   — Upload a document for analysis
  GET  /api/v1/analysis/         — List user's past analysis records
  GET  /api/v1/analysis/{id}     — Get a specific analysis result

SECURITY MODEL
---------------
All endpoints require JWT authentication (get_current_user dependency).
All MongoDB queries include `{\"user_id\": current_user[\"sub\"]}` — a user can
only see and retrieve their own analysis records.

Files are stored via SecureStorageService — not directly accessible by URL.

FILE VALIDATION
---------------
Files are validated BEFORE any processing:
  1. Size check (max UPLOAD_MAX_SIZE_MB)
  2. MIME type allowlist (PDF, JPEG, PNG only)
  3. Magic byte verification (actual content matches claimed type)
A file that fails any check returns HTTP 400 with a clear message.
"""

import uuid
import logging
import asyncio
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.responses import JSONResponse

from api.dependencies.auth import get_current_user
from db.database import get_database
from api.middleware.file_validator import validate_upload, ALLOWED_MIME_TYPES
from agents.document_analyzer.agent import get_analyzer_agent

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/analysis", tags=["Document Analyzer"])


# =============================================================================
# POST /api/v1/analysis/upload
# =============================================================================

@router.post("/upload", summary="Upload and analyze a legal document")
async def upload_document(
    file: UploadFile = File(..., description="PDF, JPEG, or PNG document to analyze"),
    current_user: dict = Depends(get_current_user),
    db = Depends(get_database),
):
    """
    Uploads a legal document, validates it, runs OCR + clause analysis,
    and returns risk-scored clause results.

    WHAT THIS DOES STEP BY STEP:
      1. Read the uploaded file bytes from the HTTP request.
      2. Validate size, MIME type, and magic bytes.
      3. Run OCR text extraction (sync function wrapped in asyncio.to_thread).
      4. Split text into clauses and score each GREEN/YELLOW/RED.
      5. Generate plain-language rewrites for YELLOW/RED clauses.
      6. Store the file in per-user isolated storage.
      7. Save the analysis record to MongoDB.
      8. Return the full analysis as JSON.

    ACCESS CONTROL:
      Only the uploading user can retrieve their analysis records.
      Files are stored at VAULT_STORAGE_PATH/{user_id}/{uuid} — not a guessable URL.

    ACCEPTED FILE TYPES: PDF, JPEG, PNG
    MAX SIZE: 10 MB (configurable via UPLOAD_MAX_SIZE_MB in .env)
    """
    from core.config import get_settings
    settings = get_settings()

    # ── Read file bytes ───────────────────────────────────────────────────
    try:
        file_bytes = await file.read()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not read uploaded file: {exc}",
        )

    # ── Validate file (size, MIME, magic bytes) ───────────────────────────
    claimed_ct = file.content_type or "application/octet-stream"
    valid, result_or_error = validate_upload(
        file_bytes=file_bytes,
        claimed_content_type=claimed_ct,
        max_size_mb=settings.UPLOAD_MAX_SIZE_MB,
    )
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result_or_error,  # result_or_error is the error message here
        )
    verified_content_type = result_or_error  # valid=True means this is the verified MIME

    # ── Run analysis pipeline ─────────────────────────────────────────────
    user_id = current_user["sub"]
    agent = get_analyzer_agent()

    analysis_result = await agent.analyze_document(
        file_bytes=file_bytes,
        content_type=verified_content_type,
        original_name=file.filename or "uploaded_document",
        user_id=user_id,
        db=db,
        openai_api_key=settings.OPENAI_API_KEY,
        model=settings.OPENAI_MODEL_DEV,
    )

    if analysis_result.status == "error":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=analysis_result.error_message,
        )

    # ── Persist analysis record to MongoDB ────────────────────────────────
    analysis_id = str(uuid.uuid4())
    record = {
        "analysis_id":   analysis_id,
        "user_id":       user_id,
        "file_id":       analysis_result.file_id,
        "original_name": analysis_result.original_name,
        "status":        analysis_result.status,
        "total_clauses": analysis_result.total_clauses,
        "green_count":   analysis_result.green_count,
        "yellow_count":  analysis_result.yellow_count,
        "red_count":     analysis_result.red_count,
        "created_at":    datetime.now(timezone.utc).isoformat(),
        "clauses":       [
            {
                "text":        c.text,
                "risk_level":  c.risk_level.value,
                "rule_hit":    c.rule_hit,
                "explanation": c.explanation,
                "confidence":  c.confidence,
                "rewrite":     c.rewrite or "",
            }
            for c in analysis_result.clauses
        ],
    }

    if db is not None:
        await db["document_analyses"].insert_one(record)

    logger.info(
        "Analysis saved",
        extra={
            "analysis_id":   analysis_id,
            "user_id":       user_id,
            "total_clauses": analysis_result.total_clauses,
            "red":           analysis_result.red_count,
            "yellow":        analysis_result.yellow_count,
        },
    )

    return {
        "analysis_id":   analysis_id,
        **analysis_result.to_dict(),
    }


# =============================================================================
# GET /api/v1/analysis/
# =============================================================================

@router.get("/", summary="List user's past document analyses")
async def list_analyses(
    current_user: dict = Depends(get_current_user),
    db = Depends(get_database),
):
    """
    Returns a list of all past document analyses for the current user.
    Results are sorted newest first.

    ACCESS CONTROL: Only the authenticated user's own records are returned.
    MongoDB query always includes {user_id: current_user["sub"]}.
    """
    user_id = current_user["sub"]

    if db is None:
        return {"analyses": []}

    cursor = db["document_analyses"].find(
        {"user_id": user_id},
        # Exclude the full clause list from the list view (large)
        {"clauses": 0},
    ).sort("created_at", -1).limit(50)

    analyses = await cursor.to_list(length=50)

    # Remove MongoDB _id field (not JSON-serializable)
    for a in analyses:
        a.pop("_id", None)

    return {"analyses": analyses}


# =============================================================================
# GET /api/v1/analysis/{analysis_id}
# =============================================================================

@router.get("/{analysis_id}", summary="Get a specific analysis result")
async def get_analysis(
    analysis_id: str,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_database),
):
    """
    Retrieves the full result of a specific document analysis.

    ACCESS CONTROL: The query includes both analysis_id AND user_id.
    Even if someone guesses an analysis_id, they cannot access another user's result.
    """
    user_id = current_user["sub"]

    if db is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found.")

    record = await db["document_analyses"].find_one(
        {"analysis_id": analysis_id, "user_id": user_id}
    )

    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analysis not found or does not belong to this user.",
        )

    record.pop("_id", None)
    return record
