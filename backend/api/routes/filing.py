"""
=============================================================================
LEXIS — Filing Guide API Routes (Module 9)
=============================================================================

Endpoints for the Complaint Filing Guide Agent.

THREE USAGE PATTERNS:
----------------------
1. Direct lookup (citizen knows doc_type):
   GET /api/v1/filing/lookup?doc_type=rti_application

2. Handoff from Document Drafter (Module 6 → Module 9):
   GET /api/v1/filing/lookup?draft_id=<uuid>
   → Reads doc_type from user_drafts MongoDB record (no re-entry).
   → The citizen does NOT re-type their situation.
   → doc_type is authoritative structured data from the draft session.

3. List all available authorities:
   GET /api/v1/filing/authorities

HANDOFF DESIGN (Module 6 → Module 9):
---------------------------------------
The frontend Document Drafter page adds a "📋 Where to File →" button
to the completed document preview card. It links to:

  /filing-guide?doc_type=rti_application&draft_id=<draft_id>

The frontend Filing Guide page reads these URL params and calls:

  GET /api/v1/filing/lookup?draft_id=<draft_id>

This endpoint reads doc_type from the user_drafts collection (same user_id
access control), calls FilingGuideAgent.lookup_authority(doc_type), and
returns the authority record. Zero re-entry. Fully structured handoff.

SECURITY:
----------
- All endpoints require JWT authentication (get_current_user dependency).
- The draft_id handoff endpoint enforces user_id access control at the
  MongoDB query level — identical to Module 6's access control pattern.
  User B cannot look up User A's draft (returns 404, not 403, to avoid
  leaking the existence of the draft_id).
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.dependencies.auth import get_current_user
from db.database import get_database
from agents.filing_guide.agent import get_filing_agent, FilingAuthorityResult

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/filing", tags=["Filing Guide"])


# ── Response schemas ──────────────────────────────────────────────────────────

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


# ── Endpoints ─────────────────────────────────────────────────────────────────

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

    Returns the full filing authority record including portal URL, fees, required
    documents, and legal basis — sourced exclusively from the verified seed database.
    """
    user_id = current_user.get("sub", "anonymous")

    # ── Priority 1: draft_id handoff from Module 6 ───────────────────────────
    if draft_id:
        # Read doc_type from the user's draft record (same access control as Module 6)
        draft = await db.user_drafts.find_one(
            {"draft_id": draft_id, "user_id": user_id}
        )
        if not draft:
            # 404 (not 403) — do not reveal whether this draft_id belongs to another user
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
    """
    Returns a summary list of all filing authorities in the database.
    Useful for populating the filing guide dropdown UI and for admin verification.
    """
    cursor = db.filing_authorities.find({}, {"_id": 0})
    records = await cursor.to_list(length=100)

    if not records:
        # If MongoDB is empty (not seeded yet), fall back to seed cache
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
