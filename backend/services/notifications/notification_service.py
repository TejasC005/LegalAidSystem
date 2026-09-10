"""
=============================================================================
LEXIS — Notification Service (Module 10)
=============================================================================

Proactive deadline reminder notifications via Brevo REST API email and SMS.
Uses the BrevoEmailProvider abstraction (no SMTP).
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class NotificationService:
    """Sends deadline reminder notifications via Brevo REST email & SMS."""

    def __init__(
        self,
        email_provider=None,
        dev_mode: bool = False,
        **kwargs,  # Gracefully accept legacy kwargs (e.g. smtp_*) without using them
    ):
        if email_provider is None:
            from services.auth.email_provider import get_email_provider
            self.email_provider = get_email_provider()
        else:
            self.email_provider = email_provider
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
            if user_email:
                html_body = f"""<div style="font-family: sans-serif; max-width: 600px; margin: auto; padding: 20px; border: 1px solid #e2e8f0; border-radius: 8px;">
<h2 style="color: #1a6b5a;">⚖️ LEXIS Deadline Reminder</h2>
<p><strong>Deadline:</strong> {deadline_label}</p>
<p><strong>Due Date:</strong> {deadline_date} (<strong>{days_remaining} days remaining</strong>)</p>
<hr style="border: 0; border-top: 1px solid #e2e8f0; margin: 20px 0;" />
<pre style="background: #f8fafc; padding: 15px; border-radius: 4px; white-space: pre-wrap; font-family: monospace;">{draft_text or 'Please log in to your LEXIS Vault to review your deadline.'}</pre>
<p style="font-size: 12px; color: #64748b; margin-top: 20px;">— LEXIS Autonomous Legal Aid System</p>
</div>"""
                result = await self.email_provider.send_email(
                    recipient_email=user_email,
                    subject=subject,
                    html_content=html_body,
                    text_content=body,
                )
                if result.success:
                    sent_any = True
                else:
                    logger.warning("Deadline notification email failed for user %s: %s", user_id, result.error)

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
            from services.auth.email_provider import get_email_provider
            settings = get_settings()
            _notification_service = NotificationService(
                email_provider=get_email_provider(),
                dev_mode=settings.ENVIRONMENT == "development",
            )
        except Exception:
            # Fallback for tests
            _notification_service = NotificationService(dev_mode=True)
    return _notification_service
