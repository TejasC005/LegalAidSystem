"""
=============================================================================
LEXIS — Deadline Service (Module 10)
=============================================================================

Manages the `vault_deadlines` MongoDB collection.
Each deadline record tracks:
  - Which vault document it relates to
  - The citizen-confirmed date
  - Which T-minus reminder intervals have already been sent
    (to prevent duplicate notifications across daily scheduler runs)
"""

import logging
from datetime import datetime, timezone, date
from typing import Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)

DEADLINE_COLLECTION = "vault_deadlines"


class DeadlineRecord(BaseModel):
    """
    MongoDB record for a tracked deadline.

    Fields:
        deadline_id       — UUID string, unique identifier
        user_id           — JWT sub of the document owner
        vault_doc_id      — file_id of the vault document this deadline relates to
        label             — Human-readable label (e.g., "Lease End Date")
        deadline_date     — ISO 8601 date string: "YYYY-MM-DD"
        doc_type          — Document type for Document Drafter handoff (e.g., "legal_notice")
        reminders_sent    — List of T-minus intervals already fired: [30, 15, 3]
        created_at        — ISO 8601 timestamp
        last_draft_text   — Most recent proactively-generated draft text (for frontend preview)
    """
    deadline_id: str
    user_id: str
    vault_doc_id: str
    label: str
    deadline_date: str          # "YYYY-MM-DD"
    doc_type: str = "legal_notice"  # for Document Drafter handoff
    reminders_sent: list[int] = []  # which T-minus intervals have fired
    created_at: str
    last_draft_text: Optional[str] = None


class DeadlineService:
    """CRUD for vault_deadlines MongoDB collection."""

    async def create_deadline(
        self,
        db,
        user_id: str,
        vault_doc_id: str,
        deadline_date_str: str,
        label: str,
        doc_type: str = "legal_notice",
    ) -> DeadlineRecord:
        """
        Creates a new deadline record.

        deadline_date_str must be "YYYY-MM-DD" format.
        Raises ValueError if the format is wrong.
        """
        import uuid

        # Validate date format
        try:
            datetime.strptime(deadline_date_str, "%Y-%m-%d")
        except ValueError:
            raise ValueError(
                f"deadline_date must be in YYYY-MM-DD format. Got: '{deadline_date_str}'"
            )

        record = DeadlineRecord(
            deadline_id=str(uuid.uuid4()),
            user_id=user_id,
            vault_doc_id=vault_doc_id,
            label=label,
            deadline_date=deadline_date_str,
            doc_type=doc_type,
            reminders_sent=[],
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        if db is not None:
            await db[DEADLINE_COLLECTION].insert_one(record.model_dump())
            logger.info(
                "Deadline created",
                extra={
                    "user_id": user_id,
                    "deadline_id": record.deadline_id,
                    "deadline_date": deadline_date_str,
                },
            )

        return record

    async def list_deadlines(
        self,
        db,
        user_id: str,
    ) -> list[DeadlineRecord]:
        """Returns all deadlines for a user, sorted by deadline_date ascending."""
        if db is None:
            return []
        cursor = db[DEADLINE_COLLECTION].find({"user_id": user_id}).sort("deadline_date", 1)
        docs = await cursor.to_list(length=200)
        result = []
        for doc in docs:
            doc.pop("_id", None)
            result.append(DeadlineRecord(**doc))
        return result

    async def get_all_upcoming_deadlines(
        self,
        db,
        days_ahead: int = 31,
    ) -> list[DeadlineRecord]:
        """
        Returns all deadline records (across ALL users) where deadline_date
        is within the next `days_ahead` days.

        Used exclusively by the daily scheduler to determine which reminders to fire.
        This is a cross-user query — only the scheduler calls this, not user-facing routes.
        """
        if db is None:
            return []

        today = date.today()
        # Build a date range: today to today + days_ahead
        from datetime import timedelta
        cutoff = (today + timedelta(days=days_ahead)).isoformat()
        today_str = today.isoformat()

        cursor = db[DEADLINE_COLLECTION].find({
            "deadline_date": {"$gte": today_str, "$lte": cutoff}
        })
        docs = await cursor.to_list(length=10000)
        result = []
        for doc in docs:
            doc.pop("_id", None)
            result.append(DeadlineRecord(**doc))
        return result

    async def mark_reminder_sent(
        self,
        db,
        deadline_id: str,
        interval: int,
        draft_text: Optional[str] = None,
    ) -> None:
        """
        Records that a reminder has been sent for the given T-minus interval.

        This prevents the scheduler from re-sending the same reminder on the
        next daily run. Optionally stores the generated draft text for frontend preview.

        interval: one of [30, 15, 3] (days before deadline)
        """
        if db is None:
            return

        update = {
            "$addToSet": {"reminders_sent": interval}
        }
        if draft_text:
            update["$set"] = {"last_draft_text": draft_text}

        await db[DEADLINE_COLLECTION].update_one(
            {"deadline_id": deadline_id},
            update,
        )
        logger.info(
            "Reminder marked as sent",
            extra={"deadline_id": deadline_id, "interval": interval},
        )

    async def get_deadline(
        self,
        db,
        deadline_id: str,
        user_id: str,
    ) -> Optional[DeadlineRecord]:
        """Fetches a single deadline record — access-controlled by user_id."""
        if db is None:
            return None
        doc = await db[DEADLINE_COLLECTION].find_one(
            {"deadline_id": deadline_id, "user_id": user_id}
        )
        if not doc:
            return None
        doc.pop("_id", None)
        return DeadlineRecord(**doc)

    async def delete_deadlines_for_doc(
        self,
        db,
        vault_doc_id: str,
        user_id: str,
    ) -> None:
        """Deletes all deadlines associated with a vault document (called on hard delete)."""
        if db is None:
            return
        await db[DEADLINE_COLLECTION].delete_many(
            {"vault_doc_id": vault_doc_id, "user_id": user_id}
        )


# ── Singleton ─────────────────────────────────────────────────────────────────

_deadline_service: Optional[DeadlineService] = None


def get_deadline_service() -> DeadlineService:
    global _deadline_service
    if _deadline_service is None:
        _deadline_service = DeadlineService()
    return _deadline_service
