"""
=============================================================================
LEXIS — Filing Guide API Routes (Module 9 Enhanced)
=============================================================================

Endpoints for the Complaint Filing Guide Agent.

USAGE PATTERNS:
---------------
1. Conversational filing guide & follow-up Q&A:
   POST /api/v1/filing/guide
   Body: { query, conversation_history, draft_id, doc_type }
   -> Returns structured guide, markdown reply, intent, checklist, steps, etc.

2. Direct lookup (citizen knows doc_type):
   GET /api/v1/filing/lookup?doc_type=rti_application

3. Handoff from Document Drafter (Module 6 → Module 9):
   GET /api/v1/filing/lookup?draft_id=<uuid>
   -> Reads doc_type from user_drafts MongoDB record (no re-entry).

4. List all available authorities:
   GET /api/v1/filing/authorities

SECURITY:
----------
- All endpoints require JWT authentication (get_current_user dependency).
- The draft_id handoff enforces user_id access control at the
  MongoDB query level. User B cannot look up User A's draft (returns 404).
"""

import logging
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.dependencies.auth import get_current_user
from db.database import get_database
from agents.filing_guide.agent import get_filing_agent, FilingAuthorityResult

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/filing", tags=["Filing Guide"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class FilingFeeInfo(BaseModel):
    amount_central: Optional[str] = None
    payment_methods_central: Optional[List[str]] = None
    fee_exemption: Optional[str] = None
    state_fees: Optional[str] = None
    structure: Optional[str] = None
    fee_schedule: Optional[List[dict]] = None
    payment_online: Optional[str] = None
    payment_offline: Optional[str] = None
    notice_sending_fee: Optional[str] = None
    court_filing_fee: Optional[str] = None
    lawyer_fees: Optional[str] = None
    source: Optional[str] = None


class FilingAuthorityResponse(BaseModel):
    found: bool
    doc_type: str
    id: Optional[str] = None
    doc_type_name: Optional[str] = None
    authority_name: Optional[str] = None
    authority_short: Optional[str] = None
    description: Optional[str] = None
    portal_url: Optional[str] = None
    portal_name: Optional[str] = None
    portal_scope: Optional[str] = None
    fee: Optional[dict] = None
    required_documents: Optional[List[str]] = None
    filing_tiers: Optional[List[dict]] = None
    response_timeline: Optional[str] = None
    legal_basis: Optional[str] = None
    important_notes: Optional[List[str]] = None
    eligibility_prerequisites: Optional[List[str]] = None
    step_by_step_procedure: Optional[List[dict]] = None
    common_mistakes: Optional[List[str]] = None
    checklist: Optional[List[str]] = None
    source_ref: Optional[str] = None
    verified: Optional[bool] = None
    last_verified: Optional[str] = None
    message: Optional[str] = None   # Set when found=False


class AuthoritySummary(BaseModel):
    id: str
    doc_type: str
    doc_type_name: str
    authority_short: str
    portal_url: Optional[str]
    verified: bool


class FilingGuideQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000, description="Citizen filing query or follow-up question")
    conversation_history: Optional[List[Dict[str, Any]]] = Field(default=None, description="Previous conversation turns")
    draft_id: Optional[str] = Field(default=None, description="Optional draft UUID carried from Document Drafter")
    doc_type: Optional[str] = Field(default=None, description="Optional explicit document type")


class StructuredGuideData(BaseModel):
    id: Optional[str] = None
    doc_type: str
    doc_type_name: str
    authority_name: str
    authority_short: Optional[str] = None
    description: Optional[str] = None
    portal_url: Optional[str] = None
    portal_name: Optional[str] = None
    portal_scope: Optional[str] = None
    fee: Optional[dict] = None
    required_documents: Optional[List[str]] = None
    filing_tiers: Optional[List[dict]] = None
    response_timeline: Optional[str] = None
    legal_basis: Optional[str] = None
    important_notes: Optional[List[str]] = None
    eligibility_prerequisites: Optional[List[str]] = None
    step_by_step_procedure: Optional[List[dict]] = None
    common_mistakes: Optional[List[str]] = None
    checklist: Optional[List[str]] = None
    source_ref: Optional[str] = None
    verified: Optional[bool] = None
    last_verified: Optional[str] = None
    calculated_tier: Optional[dict] = None
    state_jurisdiction: Optional[str] = None


class FilingGuideQueryResponse(BaseModel):
    reply_text: str
    guide: Optional[StructuredGuideData] = None
    intent: str
    doc_type: Optional[str] = None
    verified: bool
    sources: List[str]
    disclaimer: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "/guide",
    response_model=FilingGuideQueryResponse,
    summary="Interactive conversational filing guide and follow-up Q&A",
    description=(
        "Processes citizen filing queries conversationally. Identifies dispute category, "
        "asks clarifying questions when info is missing, calculates pecuniary tiers for "
        "consumer claims, generates step-by-step filing guides, and answers follow-up questions."
    ),
)
async def get_conversational_filing_guide(
    body: FilingGuideQueryRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    """Conversational filing guide endpoint."""
    user_id = current_user.get("sub", "anonymous")
    logger.info(
        "Filing guide conversational query received: user_id='%s', query_len=%d, draft_id='%s'",
        user_id, len(body.query), body.draft_id
    )

    # Security check if draft_id passed: ensure current user owns the draft
    if body.draft_id and db is not None:
        draft_filter = {"draft_id": body.draft_id}
        if user_id != "anonymous":
            draft_filter["user_id"] = user_id
        draft = await db.user_drafts.find_one(draft_filter)
        if not draft:
            raise HTTPException(status_code=404, detail="Draft not found or unauthorized access.")
        if not body.doc_type and draft.get("doc_type"):
            body.doc_type = draft.get("doc_type")

    agent = get_filing_agent(mongo_db=db)
    result = await agent.process_conversation(
        query=body.query,
        conversation_history=body.conversation_history,
        draft_id=body.draft_id,
        doc_type=body.doc_type,
        mongo_db=db,
        user_id=user_id,
    )

    return FilingGuideQueryResponse(**result)


@router.get(
    "/lookup",
    response_model=FilingAuthorityResponse,
    summary="Look up filing authority for a document type or draft",
)
async def lookup_filing_authority(
    doc_type: Optional[str] = Query(
        None,
        description="Document type: rti_application | consumer_complaint | legal_notice"
    ),
    draft_id: Optional[str] = Query(
        None,
        description=(
            "Draft ID from Document Drafter (Module 6). "
            "When provided, doc_type is automatically read from the draft record — "
            "the citizen does not need to re-enter it. "
            "Access control: only the draft owner can use their draft_id."
        )
    ),
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Core filing guide lookup endpoint.

    Accepts either:
    - `doc_type` (direct lookup): citizen selects from the UI dropdown.
    - `draft_id` (Module 6 handoff): doc_type is read from the user's draft session.

    If both are provided, `draft_id` takes precedence (authoritative structured data
    is preferred over re-entered natural language).
    """
    user_id = current_user.get("sub", "anonymous")

    # ── Priority 1: draft_id handoff from Module 6 ───────────────────────────
    if draft_id:
        draft = await db.user_drafts.find_one(
            {"draft_id": draft_id, "user_id": user_id}
        )
        if not draft:
            raise HTTPException(
                status_code=404,
                detail="Draft not found or unauthorized access."
            )
        doc_type = draft.get("doc_type")
        if not doc_type:
            raise HTTPException(
                status_code=400,
                detail="The referenced draft has no document type — cannot determine filing authority."
            )
        logger.info(
            "Filing guide handoff from draft: user_id='%s', draft_id='%s', doc_type='%s'",
            user_id, draft_id, doc_type
        )

    # ── Priority 2: direct doc_type parameter ────────────────────────────────
    elif doc_type:
        doc_type = doc_type.strip().lower()
    else:
        raise HTTPException(
            status_code=400,
            detail=(
                "Provide either 'doc_type' (rti_application | consumer_complaint | legal_notice) "
                "or 'draft_id' (to auto-read doc_type from a completed draft session)."
            )
        )

    # ── Perform lookup ───────────────────────────────────────────────────────
    agent = get_filing_agent(mongo_db=db)
    result: FilingAuthorityResult = await agent.lookup_authority(doc_type, mongo_db=db)

    return FilingAuthorityResponse(**result.to_dict())


@router.get(
    "/authorities",
    response_model=List[AuthoritySummary],
    summary="List all available filing authorities",
)
async def list_filing_authorities(
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    """Returns a summary list of all filing authorities in the database."""
    cursor = db.filing_authorities.find({}, {"_id": 0})
    records = await cursor.to_list(length=100)

    if not records:
        from services.filing.ingestion import load_filing_seed
        try:
            records = load_filing_seed()
        except Exception:
            records = []

    return [
        AuthoritySummary(
            id=r.get("id", ""),
            doc_type=r.get("doc_type", ""),
            doc_type_name=r.get("doc_type_name", ""),
            authority_short=r.get("authority_short", ""),
            portal_url=r.get("portal_url"),
            verified=r.get("verified", False),
        )
        for r in records
    ]
