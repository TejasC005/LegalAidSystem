# backend/services/auth/otp_provider.py
"""
LEXIS — OTP Provider Interface (Module 2)
------------------------------------------
Defines the abstract interface every SMS provider must implement.
This means the business logic (OTP generation, storage, verification)
never needs to know WHICH provider is sending the SMS — it just calls
provider.send_otp(phone, otp).

To swap from the dev stub to a real provider (e.g. Twilio, MSG91, Sarvam AI):
  1. Create a new class that inherits OTPProvider.
  2. Implement send_otp() using that provider's SDK/API.
  3. Change which class gets injected in services/auth/otp_service.py.
  4. Zero changes to routes or business logic.

This pattern is called "Dependency Inversion" — high-level code
(our auth flow) does not depend on low-level details (which SMS company).
"""

import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class OTPProvider(ABC):
    """
    Abstract base class for OTP delivery.
    All SMS providers must implement this interface.
    """

    @abstractmethod
    async def send_otp(self, phone: str, otp: str) -> bool:
        """
        Send the OTP to the given phone number.

        Args:
            phone: Phone number in E.164 format (e.g. +919876543210)
            otp:   The 6-digit code to send

        Returns:
            True if the OTP was sent successfully, False otherwise.

        IMPORTANT: Never log the otp value. Log only the phone (masked)
        and the result (success/failure).
        """
        ...


# ── ⚠️  DEV-ONLY stub — replace before going to production ────────────────────

import os
from datetime import datetime


class DevLogOTPProvider(OTPProvider):
    """
    ⚠️  DEVELOPMENT ONLY — does NOT send a real SMS.

    Prints the OTP to the server console/logs and writes it to
    backend/latest_otp.txt so you can easily check it manually.

    Before going to production:
      - Remove this class (or keep it disabled).
      - Implement a real provider (TwilioOTPProvider, MSG91OTPProvider, etc.)
      - Switch the provider in otp_service.py.
    """

    async def send_otp(self, phone: str, otp: str) -> bool:
        # Mask the middle of the phone number before logging (privacy practice)
        masked_phone = phone[:3] + "****" + phone[-3:] if len(phone) > 6 else "***"

        # ⚠️  OTP shown in logs ONLY in dev mode — this line must be removed
        #    (or the provider swapped) before production deployment.
        logger.warning(
            "[DEV STUB] OTP generated — NOT sent via SMS. Check logs or latest_otp.txt for code.",
            extra={
                "phone_masked": masked_phone,
                "otp_code": otp,          # DEV ONLY — real providers never log otp
                "dev_only": True,
            },
        )

        # 📄 DEV CONVENIENCE: Write the OTP to backend/latest_otp.txt for quick manual checking
        try:
            latest_otp_path = os.path.join(os.path.dirname(__file__), "..", "..", "latest_otp.txt")
            content = (
                f"=========================================\n"
                f"LEXIS DEV OTP (Latest Request)\n"
                f"=========================================\n"
                f"Phone Number : {phone}\n"
                f"Your OTP Code: {otp}\n"
                f"Generated At : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"=========================================\n"
            )
            with open(latest_otp_path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as exc:
            logger.warning("Could not write latest_otp.txt file: %s", exc)

        return True
