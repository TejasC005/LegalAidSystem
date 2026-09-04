"""
=============================================================================
LEXIS — Vault API Routes (Module 10)
=============================================================================

All routes are protected by JWT authentication.

ANONYMOUS MODE BLOCK:
Every endpoint immediately returns HTTP 403 if the authenticated user's role
is "anonymous". This is by design — vault documents require a persistent real
account for security, data ownership, and notification delivery.

The error message explains WHY and HOW to get a real account, rather than
just refusing access — per the user-friendly design principle from Module 2.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from pydantic import BaseModel

from api.dependencies.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vault", tags=["Vault & Deadlines — Module 10"])

# ── Anonymous mode error message (friendly, not just "forbidden") ─────────────
ANONYMOUS_VAULT_MESSAGE = (
    "The Vault & Deadlines feature requires a real LEXIS account. "
    "Anonymous sessions cannot store documents, because encryption keys "
    "and deadline notifications are tied to your verified identity. "
    "Please sign in with your phone number (OTP login) to use this feature."
)


def _require_real_account(current_user: dict) -> dict:
    """
    Checks that the current user is NOT anonymous.
    Raises HTTP 403 with a friendly explanation if they are.
    Call this at the start of every vault endpoint.
    """
    if current_user.get("role") == "anonymous":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ANONYMOUS_VAULT_MESSAGE,
        )
    return current_user


# ── Request/Response Models ───────────────────────────────────────────────────

class ConfirmDateRequest(BaseModel):
    """
    Request body for POST /vault/{doc_id}/confirm-dates.

    confirmed_dates: list of dates to confirm, each with:
      - label: the label (e.g., "Lease End Date")
      - date_str: the confirmed/corrected date in "YYYY-MM-DD" format
      - doc_type: document type for Drafter handoff (optional, default "legal_notice")
    """
    confirmed_dates: list[dict]


def _get_db():
    """Get MongoDB database from app lifespan state."""
    try:
        from main import app as lexis_app
        return lexis_app.state.mongo_client[lexis_app.state.mongo_db_name]
    except Exception:
        return None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/upload", summary="Upload a document to the Vault")
async def upload_vault_document(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """
    ## Upload a Document to the Vault

    Accepts PDF, JPEG, or PNG files (max 10 MB).

    **Pipeline:**
    1. Validates file type (magic bytes + MIME allowlist — Module 7 reuse)
    2. Extracts text via OCR (Module 7 reuse)
    3. Encrypts file with AES-256-GCM before writing to disk
    4. Runs LLM-based date extraction on the OCR text
    5. Returns document record + extracted dates for citizen review

    **Anonymous mode:** Returns HTTP 403 with explanation.

    **Date extraction:** Dates with `needs_confirmation=true` (confidence < 70%)
    must be reviewed by the citizen before a deadline is created.
    """
    user = _require_real_account(current_user)
    user_id = user["sub"]
    db = _get_db()

    file_bytes = await file.read()
    if len(file_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    content_type = file.content_type or "application/octet-stream"
    original_name = file.filename or "document"

    from services.vault.vault_service import get_vault_service
    vault_svc = get_vault_service()

    try:
        vault_doc, ocr_text = await vault_svc.upload_and_extract(
            db=db,
            user_id=user_id,
            file_bytes=file_bytes,
            original_name=original_name,
            content_type=content_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Vault upload failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Document upload failed. Please try again.")

    # Run date extraction via the vault agent
    from agents.vault_deadline.agent import get_vault_agent
    vault_agent = get_vault_agent()
    extracted_dates = await vault_agent.extract_dates_from_text(ocr_text)

    # Store extracted dates in the document record
    if db is not None:
        await db["vault_documents"].update_one(
            {"file_id": vault_doc.file_id, "user_id": user_id},
            {"$set": {"extracted_dates": extracted_dates}},
        )

    low_confidence_count = sum(1 for d in extracted_dates if d.get("needs_confirmation"))

    return {
        "file_id": vault_doc.file_id,
        "original_name": vault_doc.original_name,
        "content_type": vault_doc.content_type,
        "size_bytes": vault_doc.size_bytes,
        "created_at": vault_doc.created_at,
        "encrypted": True,
        "extracted_dates": extracted_dates,
        "extraction_summary": {
            "total_dates_found": len(extracted_dates),
            "needs_confirmation_count": low_confidence_count,
            "all_auto_confirmed": low_confidence_count == 0 and len(extracted_dates) > 0,
        },
        "message": (
            f"Document uploaded and encrypted. Found {len(extracted_dates)} date(s). "
            + (f"{low_confidence_count} date(s) require your verification before a deadline is created."
               if low_confidence_count else "")
        ),
    }


@router.post("/{doc_id}/confirm-dates", summary="Confirm extracted dates and create deadlines")
async def confirm_vault_dates(
    doc_id: str,
    body: ConfirmDateRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    ## Confirm Extracted Dates and Create Deadline Records

    After reviewing extracted dates, the citizen explicitly confirms which
    dates to track. Only confirmed dates create deadline records.

    **Body:** `{"confirmed_dates": [{"label": "...", "date_str": "YYYY-MM-DD", "doc_type": "..."}]}`
    """
    user = _require_real_account(current_user)
    user_id = user["sub"]
    db = _get_db()

    if not body.confirmed_dates:
        raise HTTPException(status_code=400, detail="No dates provided for confirmation.")

    from services.vault.deadline_service import get_deadline_service
    deadline_svc = get_deadline_service()

    created_deadlines = []
    errors = []

    for date_entry in body.confirmed_dates:
        label = date_entry.get("label", "Deadline")
        date_str = date_entry.get("date_str", "")
        doc_type = date_entry.get("doc_type", "legal_notice")

        if not date_str:
            errors.append(f"Missing date_str for label: {label}")
            continue

        try:
            record = await deadline_svc.create_deadline(
                db=db,
                user_id=user_id,
                vault_doc_id=doc_id,
                deadline_date_str=date_str,
                label=label,
                doc_type=doc_type,
            )
            created_deadlines.append(record.model_dump())
        except ValueError as exc:
            errors.append(str(exc))

    if created_deadlines and db is not None:
        await db["vault_documents"].update_one(
            {"file_id": doc_id, "user_id": user_id},
            {"$set": {"confirmed_deadline_id": created_deadlines[0]["deadline_id"]}},
        )

    return {
        "created": len(created_deadlines),
        "errors": errors,
        "deadlines": created_deadlines,
    }


@router.get("/documents", summary="List vault documents")
async def list_vault_documents(
    current_user: dict = Depends(get_current_user),
):
    """
    ## List Vault Documents

    Returns all documents in the authenticated user's vault (newest first).
    **Anonymous mode:** Returns HTTP 403.
    """
    user = _require_real_account(current_user)
    user_id = user["sub"]
    db = _get_db()

    from services.vault.vault_service import get_vault_service
    vault_svc = get_vault_service()
    docs = await vault_svc.list_documents(db=db, user_id=user_id)

    return {"documents": [d.model_dump() for d in docs], "count": len(docs)}


@router.get("/documents/{doc_id}/download", summary="Download a vault document (decrypted)")
async def download_vault_document(
    doc_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    ## Download a Vault Document

    Decrypts and returns the file. Access is strictly limited to the document owner.
    **Anonymous mode:** Returns HTTP 403.
    """
    from fastapi.responses import Response

    user = _require_real_account(current_user)
    user_id = user["sub"]
    db = _get_db()

    from services.vault.vault_service import get_vault_service
    vault_svc = get_vault_service()

    try:
        decrypted_bytes = await vault_svc.retrieve_decrypted(
            db=db, user_id=user_id, file_id=doc_id
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Document not found or access denied.")
    except Exception as exc:
        logger.error("Vault download failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Download failed. Please try again.")

    content_type = "application/octet-stream"
    if db is not None:
        meta = await db["vault_documents"].find_one({"file_id": doc_id, "user_id": user_id})
        if meta:
            content_type = meta.get("content_type", content_type)

    return Response(
        content=decrypted_bytes,
        media_type=content_type,
        headers={"Content-Disposition": f"attachment; filename={doc_id}"},
    )


@router.delete("/documents/{doc_id}", summary="Hard-delete a vault document")
async def delete_vault_document(
    doc_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    ## Delete a Vault Document (Hard Delete)

    Permanently removes the document from disk AND all MongoDB metadata,
    including any associated deadline records. **Unrecoverable.**

    **Anonymous mode:** Returns HTTP 403.
    """
    user = _require_real_account(current_user)
    user_id = user["sub"]
    db = _get_db()

    from services.vault.vault_service import get_vault_service
    vault_svc = get_vault_service()
    deleted = await vault_svc.delete_document(db=db, user_id=user_id, file_id=doc_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found or access denied.")

    return {"deleted": True, "file_id": doc_id, "message": "Document permanently deleted."}


@router.get("/deadlines", summary="List upcoming deadlines")
async def list_deadlines(
    current_user: dict = Depends(get_current_user),
):
    """
    ## List Upcoming Deadlines

    Returns all deadline records for the authenticated user, with days remaining
    and urgency level computed for each. **Anonymous mode:** Returns HTTP 403.
    """
    user = _require_real_account(current_user)
    user_id = user["sub"]
    db = _get_db()

    from services.vault.deadline_service import get_deadline_service
    from datetime import date, datetime
    deadline_svc = get_deadline_service()
    records = await deadline_svc.list_deadlines(db=db, user_id=user_id)

    today = date.today()
    result = []
    for record in records:
        try:
            dl_date = datetime.strptime(record.deadline_date, "%Y-%m-%d").date()
            days_remaining = (dl_date - today).days
        except Exception:
            days_remaining = None

        result.append({
            **record.model_dump(),
            "days_remaining": days_remaining,
            "urgency": (
                "critical" if days_remaining is not None and days_remaining <= 3
                else "high" if days_remaining is not None and days_remaining <= 15
                else "medium" if days_remaining is not None and days_remaining <= 30
                else "low"
            ),
        })

    return {"deadlines": result, "count": len(result)}


@router.get("/deadlines/{deadline_id}/draft", summary="Get proactive draft for a deadline")
async def get_deadline_draft(
    deadline_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    ## Get Proactively Generated Draft

    Returns the draft document generated by the Document Drafter agent for
    this deadline reminder. Returns 404 if no reminder has fired yet.

    **Anonymous mode:** Returns HTTP 403.
    """
    user = _require_real_account(current_user)
    user_id = user["sub"]
    db = _get_db()

    from services.vault.deadline_service import get_deadline_service
    deadline_svc = get_deadline_service()
    record = await deadline_svc.get_deadline(db=db, deadline_id=deadline_id, user_id=user_id)

    if not record:
        raise HTTPException(status_code=404, detail="Deadline not found.")

    if not record.last_draft_text:
        return {
            "deadline_id": deadline_id,
            "draft_available": False,
            "message": "No draft yet. A draft will be created when the first reminder fires (T-30, T-15, or T-3 days).",
        }

    return {
        "deadline_id": deadline_id,
        "draft_available": True,
        "label": record.label,
        "deadline_date": record.deadline_date,
        "reminders_sent": record.reminders_sent,
        "draft_text": record.last_draft_text,
    }
