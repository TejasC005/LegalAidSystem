# backend/api/routes/lawyer.py
"""
LEXIS — Lawyer Dashboard Route (Module 13)
-------------------------------------------
This router exposes a single GET endpoint that is strictly protected by
require_role(["lawyer"]).

WHAT THIS MODULE IS AND IS NOT
───────────────────────────────
This is a role-isolation scaffold — NOT a functional feature set.

What IS built here:
  • A real, working HTTP route at GET /api/v1/lawyer/dashboard
  • A real role guard: only JWTs with role="lawyer" can reach it
  • A structured JSON response explaining the Coming Soon scope

What is explicitly NOT built here:
  • Case referral logic
  • Lawyer verification / onboarding flow
  • Consultation booking
  • Any read or write access to citizen data

WHY SCAFFOLD THIS NOW (for academic report / architectural rationale):
─────────────────────────────────────────────────────────────────────────
Establishing the permission boundary in code *now* — before the feature
exists — is a deliberate architectural discipline, not wasted effort:

1.  **Zero accidental privilege leak**: If we wait until Module N to create
    the lawyer route, there is a window where a lawyer-role JWT (already
    issuable since Module 2) could fall through to citizen routes or, worse,
    admin routes.  The scaffold closes that gap today.

2.  **Single change, not a refactor**: Adding the real lawyer feature later
    means filling in the route handler body.  Without the scaffold, a future
    session would also need to add the router, register it in main.py, add
    the frontend route, update the auth dependency, update tests, and update
    docs — a risky multi-file refactor instead of a one-function addition.

3.  **Testable boundary**: We can write and run role-isolation tests RIGHT NOW
    (see test_lawyer_scaffold.py) that will catch regressions if anyone
    accidentally grants lawyers access to admin endpoints or vice versa.
    Tests written against a placeholder are just as valid as tests against
    a real feature — they protect the boundary, not the implementation.

4.  **Honest documentation**: README + docs already note the lawyer role as
    "future scope".  A corresponding empty-but-guarded route makes that
    documentation literally true in code, not just in prose.

FUTURE SCOPE (what will be built in a later phase, NOT in this MVP):
  - Case referral: citizens submit referral requests → lawyer receives them
  - Lawyer verification: document submission → admin approval workflow
  - Consultation booking: calendar slot selection + notification
"""

import logging
from fastapi import APIRouter, Depends
from api.dependencies.auth import require_role

logger = logging.getLogger(__name__)

# ── Router setup ──────────────────────────────────────────────────────────────
# prefix="/lawyer" → all routes here are under /api/v1/lawyer/
# tags=["Lawyer (Module 13)"] → groups them in Swagger UI
router = APIRouter(
    prefix="/lawyer",
    tags=["Lawyer (Module 13 — Future Scope)"],
)


# ── GET /api/v1/lawyer/dashboard ──────────────────────────────────────────────

@router.get(
    "/dashboard",
    summary="Lawyer Dashboard (Coming Soon — future scope)",
    response_description="Scaffold response: confirms lawyer role access and lists future planned features.",
)
async def lawyer_dashboard(
    current_user: dict = Depends(require_role(["lawyer"])),
):
    """
    Lawyer-role dashboard endpoint.

    This endpoint is STRICTLY protected by require_role(["lawyer"]).

    - A JWT with role="admin" → HTTP 403 Forbidden
    - A JWT with role="user"  → HTTP 403 Forbidden
    - A JWT with role="anonymous" → HTTP 403 Forbidden
    - A JWT with role="lawyer"   → HTTP 200 (this response)
    - No JWT at all              → HTTP 401 Unauthorized

    The response body is static Coming Soon text — no real data is
    fetched or processed.  This is intentional: the feature set described
    below is explicitly deferred to a future phase.
    """
    logger.info(
        "Lawyer dashboard accessed",
        extra={"lawyer_id": current_user.get("sub"), "role": current_user.get("role")},
    )

    return {
        "role": "lawyer",
        "status": "coming_soon",
        "message": (
            "Welcome to LEXIS for Legal Professionals. "
            "The lawyer portal is currently in its scaffolding phase. "
            "This page confirms your role and permission boundary — "
            "no functional features are available yet."
        ),
        "coming_soon_features": [
            {
                "feature": "Case Referrals",
                "description": (
                    "Receive referral requests from citizens whose legal needs "
                    "exceed self-help. Review case summaries and accept or decline. "
                    "Not implemented — future phase only."
                ),
            },
            {
                "feature": "Lawyer Verification",
                "description": (
                    "Submit Bar Council registration number and practice certificate "
                    "for admin review. Verified badge unlocks referral visibility. "
                    "Not implemented — future phase only."
                ),
            },
            {
                "feature": "Consultation Booking",
                "description": (
                    "Citizens book 30-minute consultation slots via an in-app calendar. "
                    "Lawyers set availability windows and receive booking notifications. "
                    "Not implemented — future phase only."
                ),
            },
        ],
        "scope_note": (
            "These features are explicitly outside the LEXIS MVP scope "
            "(Modules 0–16). This scaffold exists to: "
            "(a) lock the role-permission boundary in code now, "
            "(b) prevent future accidental privilege leak, and "
            "(c) provide a clear extension point for the next development phase."
        ),
    }
