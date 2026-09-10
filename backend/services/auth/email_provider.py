# backend/services/auth/email_provider.py
"""
LEXIS — Brevo REST API Email Provider
-------------------------------------
Provides production-ready email delivery exclusively through the Brevo
v3 Transactional Email REST API (https://api.brevo.com/v3/smtp/email).

SECURITY & ARCHITECTURAL RULES:
  - Uses ONLY the Brevo REST API with the `api-key` HTTP header.
  - SMTP is completely disabled: no smtplib, no SMTP credentials, no relays.
  - The Brevo API key remains strictly server-side and is never sent to frontend.
  - API keys, passwords, tokens, and OTP codes are NEVER logged.
  - Recipient email addresses are masked in logs for privacy.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


# ── Data Models & Results ─────────────────────────────────────────────────────

@dataclass
class EmailSendResult:
    """
    Structured result returned by the email service.
    Implements __bool__ so callers can use `if result:` seamlessly.
    """
    success: bool
    message_id: Optional[str] = None
    error: Optional[str] = None
    status_code: Optional[int] = None

    def __bool__(self) -> bool:
        return self.success


# ── Email Provider Interface ──────────────────────────────────────────────────

class EmailProvider(ABC):
    """
    Abstract base class for email delivery providers.
    """

    @abstractmethod
    async def send_otp(self, email: str, otp: str) -> bool:
        """
        Send the verification OTP to the given email address.

        Args:
            email: Recipient email address
            otp:   The 6-digit code to send

        Returns:
            True if sent successfully, False otherwise.
        """
        raise NotImplementedError


# ── Utilities & Templates ─────────────────────────────────────────────────────

def mask_email(email: str) -> str:
    """Safely masks an email address for logging without leaking PII."""
    if not email or "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        masked_local = local[:1] + "*"
    else:
        masked_local = local[:2] + "****" + local[-1:]
    return f"{masked_local}@{domain}"


def build_otp_email_templates(otp: str, expire_minutes: int = 5) -> tuple[str, str, str]:
    """
    Constructs the subject, responsive HTML email, and plain text content for LEXIS OTP verification.

    Args:
        otp: The 6-digit verification code.
        expire_minutes: Validity window in minutes (default 5).

    Returns:
        tuple of (subject, html_content, text_content)
    """
    subject = "LEXIS Email Verification Code"

    text_content = (
        f"LEXIS — Autonomous Legal Aid System\n\n"
        f"Your email verification code is: {otp}\n\n"
        f"This code will expire in {expire_minutes} minutes.\n"
        f"Never share this code with anyone. LEXIS representatives will never ask for your code.\n\n"
        f"If you did not request this verification code, you can safely ignore this email.\n\n"
        f"— LEXIS Autonomous Legal Aid System\n"
        f"© 2026 LEXIS. All rights reserved."
    )

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{subject}</title>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; color: #1e293b;">
  <table width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color: #f8fafc; padding: 40px 16px;">
    <tr>
      <td align="center">
        <table width="100%" border="0" cellspacing="0" cellpadding="0" style="max-width: 520px; background-color: #ffffff; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.06); overflow: hidden; border: 1px solid #e2e8f0;">
          <!-- Header -->
          <tr>
            <td style="background-color: #1a6b5a; padding: 32px 24px; text-align: center;">
              <div style="font-size: 38px; line-height: 1; margin-bottom: 6px;">⚖️</div>
              <h1 style="color: #ffffff; margin: 0; font-size: 24px; font-weight: 700; letter-spacing: 0.05em;">LEXIS</h1>
              <p style="color: #e6f4ea; margin: 4px 0 0 0; font-size: 13px;">Autonomous Legal Aid System</p>
            </td>
          </tr>
          <!-- Body -->
          <tr>
            <td style="padding: 36px 32px;">
              <h2 style="margin: 0 0 16px 0; font-size: 18px; color: #0f172a; font-weight: 600;">Email Verification Code</h2>
              <p style="margin: 0 0 24px 0; font-size: 14px; line-height: 1.6; color: #475569;">
                Please use the following 6-digit verification code to authenticate with LEXIS:
              </p>
              <!-- Code Box -->
              <div style="background-color: #f0fdf4; border: 2px dashed #1a6b5a; border-radius: 8px; padding: 18px 24px; text-align: center; margin-bottom: 24px;">
                <span style="font-size: 36px; font-weight: 800; letter-spacing: 8px; color: #1a6b5a; font-family: monospace; display: inline-block;">
                  {otp}
                </span>
              </div>
              <!-- Expiration & Security Notice -->
              <div style="background-color: #fffbeb; border-left: 4px solid #f59e0b; padding: 12px 16px; border-radius: 4px; margin-bottom: 24px;">
                <p style="margin: 0; font-size: 13px; color: #b45309; line-height: 1.5;">
                  ⏱ <strong>Valid for {expire_minutes} minutes.</strong> Never share this code with anyone. LEXIS representatives will never ask for your code.
                </p>
              </div>
              <!-- Disclaimer -->
              <p style="margin: 0; font-size: 13px; line-height: 1.5; color: #64748b;">
                If you did not request this verification code, you can safely ignore this email.
              </p>
            </td>
          </tr>
          <!-- Footer -->
          <tr>
            <td style="background-color: #f1f5f9; padding: 20px 24px; text-align: center; border-top: 1px solid #e2e8f0;">
              <p style="margin: 0; font-size: 12px; color: #64748b;">
                © 2026 LEXIS Autonomous Legal Aid System. All rights reserved.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    return subject, html_content, text_content


# ── Brevo REST API Email Provider ─────────────────────────────────────────────

class BrevoEmailProvider(EmailProvider):
    """
    Production-grade transactional email service powered by the Brevo REST API.
    Sends requests to POST https://api.brevo.com/v3/smtp/email using httpx.
    """

    BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"

    def __init__(
        self,
        api_key: str = "",
        sender_email: str = "",
        sender_name: str = "LEXIS",
        timeout: float = 10.0,
    ):
        self.api_key = (api_key or "").strip()
        self.sender_email = (sender_email or "").strip()
        self.sender_name = (sender_name or "LEXIS").strip()
        self.timeout = timeout
        self.last_error: str = ""
        self.last_message_id: Optional[str] = None

    def validate_configuration(self) -> tuple[bool, str]:
        """
        Checks that required Brevo credentials and settings are present.
        Never prints or exposes the actual API key.
        """
        missing = []
        if not self.api_key:
            missing.append("BREVO_API_KEY")
        if not self.sender_email:
            missing.append("BREVO_SENDER_EMAIL")
        if not self.sender_name:
            missing.append("BREVO_SENDER_NAME")

        if missing:
            err = f"Brevo email configuration incomplete. Missing: {', '.join(missing)}."
            return False, err
        return True, ""

    def validate_recipient_email(self, email: str) -> tuple[bool, str]:
        """
        Validates recipient email address syntax.
        """
        if not email or not isinstance(email, str) or not email.strip():
            return False, "Recipient email address cannot be empty."

        cleaned = email.strip()
        try:
            from email_validator import validate_email
            validate_email(cleaned, check_deliverability=False)
            return True, cleaned
        except Exception:
            import re
            pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
            if re.match(pattern, cleaned):
                return True, cleaned
            return False, f"Invalid recipient email address syntax: '{mask_email(cleaned)}'."

    async def send_email(
        self,
        recipient_email: str,
        subject: str,
        html_content: str,
        text_content: Optional[str] = None,
    ) -> EmailSendResult:
        """
        Dispatches a transactional email through Brevo's v3 REST API.

        Args:
            recipient_email: Destination email address
            subject: Subject line
            html_content: Rendered HTML body
            text_content: Optional plain-text fallback body

        Returns:
            EmailSendResult containing success boolean, message_id, error, and status_code.
        """
        self.last_error = ""
        self.last_message_id = None

        # 1. Configuration Validation
        is_cfg_valid, cfg_err = self.validate_configuration()
        if not is_cfg_valid:
            logger.error("[Brevo] %s", cfg_err)
            self.last_error = cfg_err
            return EmailSendResult(success=False, error=cfg_err)

        # 2. Recipient Email Validation
        is_email_valid, cleaned_email_or_err = self.validate_recipient_email(recipient_email)
        if not is_email_valid:
            logger.warning("[Brevo] %s", cleaned_email_or_err)
            self.last_error = cleaned_email_or_err
            return EmailSendResult(success=False, error=cleaned_email_or_err)

        clean_recipient = cleaned_email_or_err
        masked_recipient = mask_email(clean_recipient)

        # 3. Warning if someone mistakenly provided an SMTP Relay key
        if self.api_key.startswith("xsmtpsib-"):
            logger.warning(
                "[Brevo] BREVO_API_KEY starts with 'xsmtpsib-', which is an SMTP key. "
                "Brevo REST API requires an API v3 key starting with 'xkeysib-...' "
                "from https://app.brevo.com/settings/keys/api."
            )

        # 4. Construct Payload strictly following Brevo REST API v3 schema
        payload = {
            "sender": {
                "name": self.sender_name,
                "email": self.sender_email,
            },
            "to": [
                {
                    "email": clean_recipient,
                }
            ],
            "subject": subject,
            "htmlContent": html_content,
        }
        if text_content:
            payload["textContent"] = text_content

        # 5. Headers (api-key strictly server-side)
        headers = {
            "accept": "application/json",
            "api-key": self.api_key,
            "content-type": "application/json",
        }

        # 6. Execute Asynchronous REST Request
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(self.BREVO_API_URL, json=payload, headers=headers)

                # Brevo returns 201 Created on success (or 200/202)
                if response.status_code in (200, 201, 202):
                    message_id = None
                    try:
                        res_data = response.json()
                        message_id = res_data.get("messageId")
                    except Exception:
                        pass

                    self.last_message_id = message_id
                    logger.info(
                        "Brevo transactional email dispatched successfully to %s (message_id=%s)",
                        masked_recipient,
                        message_id or "n/a",
                    )
                    return EmailSendResult(
                        success=True,
                        message_id=message_id,
                        status_code=response.status_code,
                    )

                # Handle HTTP Error Responses
                detail_msg = ""
                try:
                    res_json = response.json()
                    detail_msg = res_json.get("message") or str(res_json)
                except Exception:
                    detail_msg = response.text

                # Specific HTTP Status Error Analysis
                if response.status_code == 401:
                    if self.api_key.startswith("xsmtpsib-"):
                        err_msg = (
                            "Brevo API authentication failed (401 Unauthorized): an SMTP key was provided "
                            "instead of a Brevo REST API key ('xkeysib-...'). Please generate a REST API key at "
                            "https://app.brevo.com/settings/keys/api and update BREVO_API_KEY in backend/.env."
                        )
                    else:
                        detail_suffix = f": {detail_msg}" if detail_msg else ""
                        err_msg = (
                            f"Brevo API authentication failed (401 Unauthorized){detail_suffix}. "
                            "Please verify your BREVO_API_KEY in backend/.env."
                        )
                elif response.status_code == 400:
                    err_msg = (
                        f"Brevo API error (400 Bad Request): {detail_msg}. "
                        f"Please ensure sender email '{self.sender_email}' is verified at https://app.brevo.com/senders."
                    )
                elif response.status_code == 402:
                    err_msg = f"Brevo email sending quota exceeded (402 Payment Required): {detail_msg}."
                elif response.status_code == 429:
                    err_msg = "Brevo rate limit reached (429 Too Many Requests). Please retry shortly."
                elif response.status_code >= 500:
                    err_msg = f"Brevo service temporarily unavailable ({response.status_code}). Please try again later."
                else:
                    err_msg = f"Brevo API returned unexpected HTTP status {response.status_code}: {detail_msg}."

                logger.error(
                    "Brevo API request failed for %s: status=%d, error=%s",
                    masked_recipient,
                    response.status_code,
                    err_msg,
                )
                self.last_error = err_msg
                return EmailSendResult(
                    success=False,
                    error=err_msg,
                    status_code=response.status_code,
                )

        except httpx.TimeoutException:
            err_msg = f"Network timeout after {self.timeout}s while connecting to Brevo email service."
            logger.error("Brevo API timeout for %s", masked_recipient)
            self.last_error = err_msg
            return EmailSendResult(success=False, error=err_msg)

        except httpx.RequestError as exc:
            err_msg = f"Network or connection error communicating with Brevo: {type(exc).__name__}."
            logger.error("Brevo API connection failure for %s: %s", masked_recipient, exc)
            self.last_error = err_msg
            return EmailSendResult(success=False, error=err_msg)

        except Exception as exc:
            err_msg = f"Unexpected error during Brevo email dispatch: {type(exc).__name__}."
            logger.error("Brevo dispatch error for %s: %s", masked_recipient, exc)
            self.last_error = err_msg
            return EmailSendResult(success=False, error=err_msg)

    async def send_otp(self, email: str, otp: str) -> bool:
        """
        Constructs the responsive LEXIS OTP email and dispatches it via Brevo REST API.
        The OTP code is never logged.
        """
        subject, html_content, text_content = build_otp_email_templates(otp)
        result = await self.send_email(
            recipient_email=email,
            subject=subject,
            html_content=html_content,
            text_content=text_content,
        )
        self.last_error = result.error or ""
        self.last_message_id = result.message_id
        return result.success


# ── Provider Factory Singleton ────────────────────────────────────────────────

_email_provider: Optional[BrevoEmailProvider] = None


def get_email_provider() -> BrevoEmailProvider:
    """Returns the BrevoEmailProvider singleton, keeping credentials synchronized with settings."""
    global _email_provider
    try:
        from core.config import get_settings
        settings = get_settings()
        api_key = (settings.BREVO_API_KEY or "").strip()
        sender_email = (settings.BREVO_SENDER_EMAIL or "").strip()
        sender_name = (settings.BREVO_SENDER_NAME or "LEXIS").strip()

        if _email_provider is None:
            _email_provider = BrevoEmailProvider(
                api_key=api_key,
                sender_email=sender_email,
                sender_name=sender_name,
            )
        else:
            _email_provider.api_key = api_key
            _email_provider.sender_email = sender_email
            _email_provider.sender_name = sender_name
    except Exception as exc:
        logger.error("Failed to initialize BrevoEmailProvider from settings: %s", exc)
        if _email_provider is None:
            _email_provider = BrevoEmailProvider()
    return _email_provider
