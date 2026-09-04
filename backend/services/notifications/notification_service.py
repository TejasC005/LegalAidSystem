"""
=============================================================================
LEXIS — Notification Service (Module 10)
=============================================================================

MVP: Email notifications via SMTP.

In development mode (ENVIRONMENT=development or SMTP_HOST empty),
email content is logged to the console instead of actually sent.
This means all tests and local dev work without any email server.

To enable real email: set SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS,
SMTP_FROM in backend/.env.

Production note: For scale, replace SMTP with a transactional email
provider (SendGrid, AWS SES, Mailgun) by swapping the _send_smtp() function.
"""

import logging
import smtplib
import email.mime.text
import email.mime.multipart
from typing import Optional

logger = logging.getLogger(__name__)


class NotificationService:
    """Sends deadline reminder notifications via email (MVP)."""

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        smtp_user: str,
        smtp_pass: str,
        smtp_from: str,
        dev_mode: bool = True,
    ):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_pass = smtp_pass
        self.smtp_from = smtp_from
        self.dev_mode = dev_mode

    async def send_deadline_notification(
        self,
        user_id: str,
        deadline_label: str,
        deadline_date: str,
        days_remaining: int,
        draft_text: str,
        db=None,
    ) -> bool:
        """
        Sends deadline reminder notification(s) based on the user's notification_preference
        (sms, email, or both).

        Returns True if at least one requested channel sent successfully.
        """
        user_email, user_phone, pref = await self._resolve_user_info(user_id, db)

        # Build notification body
        urgency_emoji = "🔴" if days_remaining <= 3 else ("🟠" if days_remaining <= 15 else "🟡")
        subject = f"{urgency_emoji} LEXIS Reminder: {deadline_label} in {days_remaining} days"

        body_lines = [
            f"Hello,",
            f"",
            f"This is an automated reminder from LEXIS.",
            f"",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"  Deadline: {deadline_label}",
            f"  Date:     {deadline_date}",
            f"  Days Remaining: {days_remaining}",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"",
        ]

        if draft_text:
            body_lines += [
                f"LEXIS has proactively prepared the following document for you:",
                f"",
                f"─── DRAFT DOCUMENT ─────────────────────────────────────────",
                draft_text,
                f"────────────────────────────────────────────────────────────",
                f"",
                f"You can download, edit, and submit this document from your LEXIS Vault.",
            ]
        else:
            body_lines.append(
                f"Please log in to LEXIS Vault to view your upcoming deadline."
            )

        body_lines += [
            f"",
            f"— LEXIS, your autonomous legal aid assistant",
            f"  This is an automated message. Do not reply to this email.",
        ]

        body = "\n".join(body_lines)

        sent_any = False

        # Channel 1: EMAIL (if pref is email or both)
        if pref in ("email", "both"):
            if self.dev_mode or not self.smtp_host:
                logger.info(
                    "📧 [DEV MODE] Deadline notification email (would be sent in production)",
                    extra={
                        "to": user_email or f"user_{user_id}",
                        "subject": subject,
                        "days_remaining": days_remaining,
                        "label": deadline_label,
                        "has_draft": bool(draft_text),
                    },
                )
                print(f"\n{'='*60}")
                print(f"📧 LEXIS EMAIL NOTIFICATION (dev mode — not actually sent)")
                print(f"To:      {user_email or f'user_{user_id}'}")
                print(f"Subject: {subject}")
                print(f"{'─'*60}")
                print(body)
                print(f"{'='*60}\n")
                sent_any = True
            elif user_email:
                sent_email = await self._send_smtp(to_email=user_email, subject=subject, body=body)
                if sent_email:
                    sent_any = True

        # Channel 2: SMS (if pref is sms or both)
        if pref in ("sms", "both"):
            sms_text = f"LEXIS Alert: {deadline_label} is due on {deadline_date} ({days_remaining} days left)."
            logger.info(
                "📱 [DEV STUB] Deadline notification SMS",
                extra={
                    "to": user_phone or f"user_{user_id}",
                    "message": sms_text,
                },
            )
            print(f"\n{'='*60}")
            print(f"📱 LEXIS SMS NOTIFICATION (dev stub)")
            print(f"To:   {user_phone or f'user_{user_id}'}")
            print(f"Text: {sms_text}")
            print(f"{'='*60}\n")
            sent_any = True

        return sent_any

    async def _send_smtp(self, to_email: str, subject: str, body: str) -> bool:
        """Sends email via SMTP. Returns True on success, False on failure."""
        import asyncio

        def _send():
            msg = email.mime.multipart.MIMEMultipart()
            msg["From"] = self.smtp_from
            msg["To"] = to_email
            msg["Subject"] = subject
            msg.attach(email.mime.text.MIMEText(body, "plain", "utf-8"))

            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.ehlo()
                server.starttls()
                if self.smtp_user and self.smtp_pass:
                    server.login(self.smtp_user, self.smtp_pass)
                server.sendmail(self.smtp_from, to_email, msg.as_string())

        try:
            # Run synchronous SMTP in a thread to avoid blocking the event loop
            await asyncio.to_thread(_send)
            logger.info("Email sent", extra={"to": to_email, "subject": subject})
            return True
        except Exception as exc:
            logger.error("SMTP send failed: %s", exc, exc_info=True)
            return False

    async def _resolve_user_info(self, user_id: str, db) -> tuple[Optional[str], Optional[str], str]:
        """
        Looks up user's email, phone, and notification_preference from MongoDB.
        """
        if db is None:
            return (None, None, "sms")
        try:
            from bson import ObjectId
            query = {"_id": ObjectId(user_id)} if len(user_id) == 24 else {"_id": user_id}
            user = await db["users"].find_one(query)
            if user:
                email = user.get("email")
                phone = user.get("phone")
                profile = user.get("profile") or {}
                pref = "sms"
                if isinstance(profile, dict):
                    pref = profile.get("notification_preference", "sms")
                elif hasattr(profile, "notification_preference"):
                    pref = getattr(profile, "notification_preference", "sms")
                return (email, phone, str(pref))
        except Exception:
            pass
        return (None, None, "sms")

    async def _resolve_user_email(self, user_id: str, db) -> Optional[str]:
        email, _, _ = await self._resolve_user_info(user_id, db)
        return email


# ── Singleton factory ─────────────────────────────────────────────────────────

_notification_service: Optional[NotificationService] = None


def get_notification_service() -> NotificationService:
    """Returns a cached NotificationService singleton."""
    global _notification_service
    if _notification_service is None:
        try:
            from core.config import get_settings
            settings = get_settings()
            dev_mode = settings.ENVIRONMENT == "development" or not settings.SMTP_HOST
            _notification_service = NotificationService(
                smtp_host=settings.SMTP_HOST,
                smtp_port=settings.SMTP_PORT,
                smtp_user=settings.SMTP_USER,
                smtp_pass=settings.SMTP_PASS,
                smtp_from=settings.SMTP_FROM,
                dev_mode=dev_mode,
            )
        except Exception:
            # Fallback for tests
            _notification_service = NotificationService(
                smtp_host="", smtp_port=587, smtp_user="",
                smtp_pass="", smtp_from="noreply@lexis.local", dev_mode=True,
            )
    return _notification_service
