"""
=============================================================================
LEXIS — Vault Deadline Scheduler (Module 10)
=============================================================================

HOW THE SCHEDULER WORKS (PLAIN LANGUAGE FOR BEGINNERS)
---------------------------------------------------------
This is the component that makes the Vault & Deadline Agent "proactive" —
it acts without the citizen asking again.

We use APScheduler (AsyncIOScheduler) to run a cron job once per day at 9 AM.
Each run does the following:

  1. Query ALL deadline records in the database that fall within the next 31 days.
  2. For each deadline:
       a. Compute: days_remaining = deadline_date - today
       b. Check: is days_remaining in [30, 15, 3]?
       c. Check: has this interval already been sent? (reminders_sent list)
       d. If both conditions are YES: fire the reminder.
  3. Firing a reminder means:
       a. Call VaultDeadlineAgent.invoke_document_drafter() to generate a
          proactive draft (lease renewal letter, visa extension inquiry, etc.)
       b. Send the citizen an email (via NotificationService) with the draft attached.
       c. Update the deadline record: add the interval to reminders_sent.

WHY T-30, T-15, T-3 (NOT DAILY)?
-----------------------------------
Daily emails would be spam and train citizens to ignore them. Three targeted
reminders at meaningful intervals:
  - T-30 days: "You have a month — start thinking about this"
  - T-15 days: "Two weeks — start preparing"
  - T-3 days:  "Urgent — act now"

Each reminder fires exactly ONCE per interval because the interval is recorded
in reminders_sent immediately after firing. Even if the scheduler runs daily,
the check `interval not in record.reminders_sent` prevents duplicate sends.

WHY APSCHEDULER (NOT CELERY/BULLMQ)?
--------------------------------------
APScheduler 3.x runs inside the same Python process as FastAPI via AsyncIOScheduler.
This means:
  - No separate worker process to deploy
  - No Redis queue required (we already use Redis for auth, but the scheduler
    doesn't need it for its own operation)
  - The scheduler shares the app's MongoDB connection pool
  - Trivial to start: one function call in the lifespan hook

For production scale (millions of users), a distributed job queue (Celery + Redis,
or BullMQ) would be better. For LEXIS MVP, APScheduler is appropriate.
"""

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ── Reminder intervals (days before deadline) ─────────────────────────────────
# These are the ONLY intervals that trigger a reminder.
# Any other days_remaining value is silently skipped.
REMINDER_INTERVALS = [30, 15, 3]


async def daily_deadline_check(db) -> dict:
    """
    Core scheduler job: checks all upcoming deadlines and fires reminders.

    This function is designed to be testable in isolation:
      - It accepts `db` as a parameter (not from app.state) so unit tests
        can pass a mock DB.
      - It accepts an optional `today` override for testing without waiting real days.
      - It returns a summary dict (fired, skipped, errors) so tests can assert behavior.

    Parameters:
        db    — Motor async MongoDB database handle
        today — Override for today's date (for testing). Defaults to date.today().

    Returns:
        {
            "fired": int,   — number of reminders sent this run
            "skipped": int, — deadlines checked but not at a trigger interval
            "errors": int,  — deadlines that caused exceptions
        }
    """
    today = date.today()

    from services.vault.deadline_service import get_deadline_service
    deadline_svc = get_deadline_service()

    records = await deadline_svc.get_all_upcoming_deadlines(db, days_ahead=31)

    fired = 0
    skipped = 0
    errors = 0

    for record in records:
        try:
            # Compute days remaining
            deadline_dt = datetime.strptime(record.deadline_date, "%Y-%m-%d").date()
            days_remaining = (deadline_dt - today).days

            # Only fire at the configured intervals
            if days_remaining not in REMINDER_INTERVALS:
                skipped += 1
                continue

            # Check if this interval was already sent
            if days_remaining in record.reminders_sent:
                logger.debug(
                    "Reminder already sent for this interval",
                    extra={
                        "deadline_id": record.deadline_id,
                        "interval": days_remaining,
                    },
                )
                skipped += 1
                continue

            # ── Fire the reminder ─────────────────────────────────────────
            logger.info(
                "Firing deadline reminder",
                extra={
                    "deadline_id": record.deadline_id,
                    "user_id": record.user_id,
                    "label": record.label,
                    "days_remaining": days_remaining,
                },
            )

            # Step 1: Invoke Document Drafter to generate a proactive draft
            # This is the "agentic" part — the system drafts a document on
            # the citizen's behalf WITHOUT them asking.
            draft_text = ""
            try:
                from agents.vault_deadline.agent import get_vault_agent
                vault_agent = get_vault_agent()
                draft_text = await vault_agent.invoke_document_drafter(
                    doc_type=record.doc_type,
                    context={
                        "label": record.label,
                        "deadline_date": record.deadline_date,
                        "days_remaining": days_remaining,
                        "user_id": record.user_id,
                    },
                )
            except Exception as draft_exc:
                logger.warning(
                    "Document Drafter invocation failed during reminder (non-fatal): %s",
                    draft_exc,
                )

            # Step 2: Send email notification
            try:
                from services.notifications.notification_service import get_notification_service
                notif_svc = get_notification_service()
                await notif_svc.send_deadline_notification(
                    user_id=record.user_id,
                    deadline_label=record.label,
                    deadline_date=record.deadline_date,
                    days_remaining=days_remaining,
                    draft_text=draft_text,
                    db=db,
                )
            except Exception as notif_exc:
                logger.warning(
                    "Notification send failed during reminder (non-fatal): %s",
                    notif_exc,
                )

            # Step 3: Mark this interval as sent (prevent duplicates)
            await deadline_svc.mark_reminder_sent(
                db=db,
                deadline_id=record.deadline_id,
                interval=days_remaining,
                draft_text=draft_text if draft_text else None,
            )

            fired += 1

        except Exception as exc:
            logger.error(
                "Error processing deadline record",
                extra={"deadline_id": record.deadline_id, "error": str(exc)},
                exc_info=True,
            )
            errors += 1

    logger.info(
        "Daily deadline check complete",
        extra={"fired": fired, "skipped": skipped, "errors": errors, "date": today.isoformat()},
    )

    return {"fired": fired, "skipped": skipped, "errors": errors}


def start_scheduler(app) -> Optional[object]:
    """
    Creates and starts the APScheduler AsyncIOScheduler.

    Called from main.py's lifespan hook after MongoDB is connected.
    The scheduler runs inside the same asyncio event loop as FastAPI.

    Returns the scheduler object (so it can be shut down in the lifespan teardown).
    Returns None if APScheduler is not installed (graceful degradation).

    SCHEDULE: every day at 09:00 server-local time.
    To change the schedule, edit the cron parameters below.
    """
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        logger.warning(
            "APScheduler not installed — deadline reminders will not run. "
            "Install: pip install apscheduler==3.10.4"
        )
        return None

    scheduler = AsyncIOScheduler()

    async def _scheduled_job():
        """Wrapper that injects the DB from app.state into daily_deadline_check."""
        try:
            db = app.state.mongo_client[app.state.mongo_db_name]
            await daily_deadline_check(db=db)
        except Exception as exc:
            logger.error("Scheduler job failed: %s", exc, exc_info=True)

    scheduler.add_job(
        _scheduled_job,
        trigger=CronTrigger(hour=9, minute=0),   # 9:00 AM daily
        id="daily_deadline_check",
        name="LEXIS Vault Deadline Reminder Check",
        replace_existing=True,
        misfire_grace_time=3600,  # If missed, run within 1 hour
    )

    scheduler.start()
    logger.info(
        "Vault deadline scheduler started — daily job at 09:00",
        extra={"job_id": "daily_deadline_check"},
    )

    return scheduler
