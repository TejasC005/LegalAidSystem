"""
=============================================================================
LEXIS — Document Drafter API Routes (Module 6)
=============================================================================

Endpoints for:
  - Multi-turn draft session management (start session, submit answer)
  - Document preview & saved draft management
  - Server-side PDF & DOCX export downloads

PER-USER ACCESS CONTROL (REQUIREMENT 7):
  - Every database query for fetching, updating, listing, or downloading documents
    strictly includes `{"user_id": current_user["sub"]}` at the query level.
  - Users can NEVER access or download another user's drafts even if they know the draft_id.
"""

import uuid
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Response
from pydantic import BaseModel, Field

from api.dependencies.auth import get_current_user
from db.database import get_database
from agents.document_drafter.agent import get_drafter_agent
from agents.document_drafter.templates import TEMPLATES
from agents.document_drafter.export import generate_pdf_bytes, generate_docx_bytes

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/drafts", tags=["Document Drafter"])


# ── Schemas ─────────────────────────────────────────────────────────────────

class StartSessionRequest(BaseModel):
    doc_type: str = Field(..., description="rti_application | legal_notice | consumer_complaint")

class AnswerRequest(BaseModel):
    answer: str = Field(..., min_length=1, description="Citizen's answer to the current question")

class DraftSessionResponse(BaseModel):
    session_id: str
    doc_type: str
    doc_type_name: str
    status: str  # "in_progress" | "completed"
    current_question: Optional[str] = None
    questions_answered: int
    total_questions: int
    assembled_document: Optional[str] = None
    draft_id: Optional[str] = None
    prefilled_fields: List[str] = Field(default_factory=list)

class DraftDocumentSummary(BaseModel):
    draft_id: str
    doc_type: str
    doc_type_name: str
    title: str
    created_at: str
    status: str


# ── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/templates", summary="List available document templates")
async def list_templates(current_user: dict = Depends(get_current_user)):
    return [
        {
            "id": k,
            "name": v["name"],
            "description": v["description"],
            "total_questions": len(v["questions"])
        }
        for k, v in TEMPLATES.items()
    ]


@router.post("/session", response_model=DraftSessionResponse, summary="Start a new multi-turn drafting session")
async def start_draft_session(
    body: StartSessionRequest,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_database)
):
    from bson import ObjectId

    user_id = current_user.get("sub", "anonymous")
    if body.doc_type not in TEMPLATES:
        raise HTTPException(status_code=400, detail=f"Invalid doc_type. Choose from: {list(TEMPLATES.keys())}")

    session_id = str(uuid.uuid4())
    template_info = TEMPLATES[body.doc_type]
    collected_answers: Dict[str, Any] = {}

    # Check if user has saved identity details in their profile to auto pre-fill
    if db is not None and user_id and not str(user_id).startswith("anon:"):
        try:
            if ObjectId.is_valid(user_id):
                users_col = getattr(db, "users", None)
                if users_col is None:
                    users_col = db["users"]
                user_doc = await users_col.find_one({"_id": ObjectId(user_id)})
                if user_doc and user_doc.get("profile"):
                    prof = user_doc["profile"]
                    full_name = prof.get("full_name")
                    address = prof.get("address")
                    city = prof.get("city")

                    if body.doc_type == "rti_application":
                        if full_name:
                            collected_answers["applicant_name"] = full_name
                        if address:
                            collected_answers["applicant_address"] = address
                        if city:
                            collected_answers["city"] = city
                    elif body.doc_type == "legal_notice":
                        if full_name:
                            collected_answers["sender_name"] = full_name
                        if address:
                            collected_answers["sender_address"] = address
                        if city:
                            collected_answers["city"] = city
                    elif body.doc_type == "consumer_complaint":
                        if full_name:
                            collected_answers["complainant_name"] = full_name
                        if address:
                            collected_answers["complainant_address"] = address
                        if city:
                            collected_answers["forum_city"] = city
        except Exception as exc:
            logger.warning("Could not auto-prefill identity from user profile: %s", exc)

    session_doc = {
        "session_id": session_id,
        "user_id": user_id,
        "doc_type": body.doc_type,
        "collected_answers": collected_answers,
        "status": "in_progress",
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat()
    }

    await db.draft_sessions.insert_one(session_doc)

    agent = get_drafter_agent()
    response_text, _, status_str = await agent.process_turn(body.doc_type, collected_answers)

    # Determine first unanswered question dynamically
    unanswered_q = None
    for q in template_info["questions"]:
        if q["key"] not in collected_answers or not str(collected_answers[q["key"]]).strip():
            unanswered_q = q["question"]
            break

    prefilled_keys = [k for k in template_info["questions"] if k["key"] in collected_answers and str(collected_answers[k["key"]]).strip()]
    num_answered = len(prefilled_keys)

    return DraftSessionResponse(
        session_id=session_id,
        doc_type=body.doc_type,
        doc_type_name=template_info["name"],
        status="in_progress",
        current_question=unanswered_q,
        questions_answered=num_answered,
        total_questions=len(template_info["questions"]),
        assembled_document=None,
        draft_id=None,
        prefilled_fields=[q["key"] for q in prefilled_keys],
    )



@router.post("/session/{session_id}/answer", response_model=DraftSessionResponse, summary="Submit answer for multi-turn draft session")
async def submit_draft_answer(
    session_id: str,
    body: AnswerRequest,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_database)
):
    user_id = current_user.get("sub", "anonymous")

    # Enforce user_id at query level
    session = await db.draft_sessions.find_one({"session_id": session_id, "user_id": user_id})
    if not session:
        raise HTTPException(status_code=404, detail="Draft session not found or unauthorized access.")

    if session["status"] == "completed":
        raise HTTPException(status_code=400, detail="This drafting session is already completed.")

    doc_type = session["doc_type"]
    template_info = TEMPLATES[doc_type]
    questions = template_info["questions"]
    collected = session.get("collected_answers", {})

    # Determine which question was being answered
    answered_key = None
    for q in questions:
        if q["key"] not in collected or not str(collected[q["key"]]).strip():
            answered_key = q["key"]
            break

    if not answered_key:
        raise HTTPException(status_code=400, detail="All questions have already been answered.")

    # Update answers
    collected[answered_key] = body.answer.strip()

    agent = get_drafter_agent()
    response_text, updated_answers, status_str = await agent.process_turn(doc_type, collected)

    num_answered = len(updated_answers)
    total_q = len(questions)

    draft_id = None
    assembled_doc = None

    if status_str == "ok":
        # Final assembly complete! Save as a permanent draft for this user
        draft_id = str(uuid.uuid4())
        assembler = template_info["assembler"]
        assembled_doc = assembler(updated_answers)

        permanent_draft = {
            "draft_id": draft_id,
            "user_id": user_id,  # Mandatory for access control
            "doc_type": doc_type,
            "doc_type_name": template_info["name"],
            "title": f"{template_info['name']} — {updated_answers.get('city', 'Draft')}",
            "collected_answers": updated_answers,
            "document_text": assembled_doc,
            "created_at": datetime.utcnow().isoformat(),
            "status": "completed"
        }
        await db.user_drafts.insert_one(permanent_draft)

        # Update session status
        await db.draft_sessions.update_one(
            {"session_id": session_id, "user_id": user_id},
            {"$set": {"status": "completed", "collected_answers": updated_answers, "updated_at": datetime.utcnow().isoformat()}}
        )

        return DraftSessionResponse(
            session_id=session_id,
            doc_type=doc_type,
            doc_type_name=template_info["name"],
            status="completed",
            current_question=None,
            questions_answered=num_answered,
            total_questions=total_q,
            assembled_document=assembled_doc,
            draft_id=draft_id
        )

    else:
        # Questions remain
        next_q_idx = num_answered
        next_question = questions[next_q_idx]["question"] if next_q_idx < total_q else None

        await db.draft_sessions.update_one(
            {"session_id": session_id, "user_id": user_id},
            {"$set": {"collected_answers": updated_answers, "updated_at": datetime.utcnow().isoformat()}}
        )

        return DraftSessionResponse(
            session_id=session_id,
            doc_type=doc_type,
            doc_type_name=template_info["name"],
            status="in_progress",
            current_question=next_question,
            questions_answered=num_answered,
            total_questions=total_q,
            assembled_document=None,
            draft_id=None
        )


@router.get("", response_model=List[DraftDocumentSummary], summary="List authenticated user's drafted documents")
async def list_user_drafts(
    current_user: dict = Depends(get_current_user),
    db = Depends(get_database)
):
    user_id = current_user.get("sub", "anonymous")
    # MANDATORY: Query level user filtering (Requirement 7)
    cursor = db.user_drafts.find({"user_id": user_id}).sort("created_at", -1)
    drafts = await cursor.to_list(length=100)

    return [
        DraftDocumentSummary(
            draft_id=d["draft_id"],
            doc_type=d["doc_type"],
            doc_type_name=d["doc_type_name"],
            title=d.get("title", d["doc_type_name"]),
            created_at=d["created_at"],
            status=d.get("status", "completed")
        )
        for d in drafts
    ]


@router.get("/{draft_id}/download/{export_format}", summary="Download drafted document as PDF or DOCX")
async def download_draft(
    draft_id: str,
    export_format: str,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_database)
):
    user_id = current_user.get("sub", "anonymous")
    if export_format.lower() not in ("pdf", "docx"):
        raise HTTPException(status_code=400, detail="Invalid export format. Must be 'pdf' or 'docx'.")

    # MANDATORY: Query level access control enforcement (Requirement 7)
    draft = await db.user_drafts.find_one({"draft_id": draft_id, "user_id": user_id})
    if not draft:
        raise HTTPException(status_code=404, detail="Document draft not found or unauthorized access.")

    doc_title = draft.get("doc_type_name", "Legal Document")
    doc_text = draft.get("document_text", "")

    filename_safe = draft.get("doc_type", "document").replace(" ", "_")

    if export_format.lower() == "pdf":
        pdf_bytes = generate_pdf_bytes(doc_title, doc_text)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename_safe}_{draft_id[:8]}.pdf"}
        )
    else:
        docx_bytes = generate_docx_bytes(doc_title, doc_text)
        return Response(
            content=docx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f"attachment; filename={filename_safe}_{draft_id[:8]}.docx"}
        )
