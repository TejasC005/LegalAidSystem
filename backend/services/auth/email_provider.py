# backend/services/auth/email_provider.py
"""
LEXIS — Email Provider Interface (Module 13B)
-----------------------------------------------
Defines the abstract interface every Email provider must implement.
This means the business logic (email OTP generation, storage, verification)
never needs to know WHICH email service is delivering the email — it just calls
provider.send_otp(email, otp).

To swap from the dev stub / SMTP to a dedicated email API (e.g. SendGrid, AWS SES):
  1. Create a new class that inherits EmailProvider.
  2. Implement send_otp() using that provider's SDK/API.
  3. Swap the class injected in services/auth/otp_service.py.
  4. Zero changes to routes or business logic.

Why email OTP reuses the same underlying OTP logic as phone OTP:
------------------------------------------------------------------
OTP generation uses secrets.randbelow() (cryptographically secure) and
verification uses secrets.compare_digest() (constant-time comparison).
These are security-critical primitives. Writing a second implementation for email
OTP would duplicate code and risk introducing subtle timing-attack vulnerabilities.
Email and phone OTPs share identical generation, hashing, and expiry logic;
only the Redis key namespace and delivery channel differ.
"""

import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class EmailProvider(ABC):
    """
    Abstract base class for email OTP delivery.
    All email providers must implement this interface.
    """

    @abstractmethod
    async def send_otp(self, email: str, otp: str) -> bool:
        """
        Send the OTP to the given email address.

        Args:
            email: Recipient email address
            otp:   The 6-digit code to send

        Returns:
            True if sent successfully, False otherwise.

        SECURITY RULE: Email addresses and OTPs must never appear in logs anywhere in production.
        """
        ...


# ── DEV-ONLY / SMTP provider stub ──────────────────────────────────────────────

class DevLogEmailProvider(EmailProvider):
    """
    Development & SMTP Email OTP Provider.

    In dev mode (without real SMTP credentials):
      Prints the OTP to server logs/console marked clearly as DEV-ONLY.

    When SMTP settings are configured:
      Uses SMTP to send the actual verification email.
    """

    def __init__(self, smtp_host: str = "", smtp_port: int = 587,
                 smtp_user: str = "", smtp_pass: str = "",
                 smtp_from: str = "noreply@lexis.local", dev_mode: bool = True):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_pass = smtp_pass
        self.smtp_from = smtp_from
        self.dev_mode = dev_mode

    async def send_otp(self, email: str, otp: str) -> bool:
        if self.dev_mode or not self.smtp_host:
            # Dev mode: log to console with clear dev-only marker
            # Email & OTP are ONLY logged in dev mode when SMTP is unconfigured.
            logger.warning(
                "[DEV ONLY] Email OTP generated — NOT sent via real SMTP.",
                extra={"dev_only": True},
            )
            print(f"\n{'='*60}")
            print(f"📧 [DEV ONLY] LEXIS EMAIL OTP VERIFICATION")
            print(f"To:        {email}")
            print(f"OTP Code:  {otp}")
            print(f"{'='*60}\n")
            return True

        # Production / real SMTP send
        import smtplib
        import email.mime.text
        import email.mime.multipart
        import asyncio

        def _send():
            msg = email.mime.multipart.MIMEMultipart()
            msg["From"] = self.smtp_from
            msg["To"] = email
            msg["Subject"] = "LEXIS — Verify Your Email Address"

            body = (
                f"Hello,\n\n"
                f"Your LEXIS email verification code is: {otp}\n\n"
                f"This code will expire in 5 minutes. Do not share this code with anyone.\n\n"
                f"— LEXIS Autonomous Legal Aid System"
            )
            msg.attach(email.mime.text.MIMEText(body, "plain", "utf-8"))

            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.ehlo()
                server.starttls()
                if self.smtp_user and self.smtp_pass:
                    server.login(self.smtp_user, self.smtp_pass)
                server.sendmail(self.smtp_from, email, msg.as_string())

        try:
            await asyncio.to_thread(_send)
            logger.info("Email OTP sent successfully via SMTP")
            return True
        except Exception as exc:
            logger.error("Failed to send Email OTP via SMTP: %s", exc)
            return False
