"""
LEXIS — OTP Provider Base & Dev Stubs
-------------------------------------
Defines the abstract interface for OTP delivery providers.
Phone OTP delivery in production is handled on the client via Firebase Phone Auth,
which sends real SMS directly to the user's phone.

DevLogOTPProvider is maintained for local tests and backend development fallback.
"""

import logging

from abc import ABC, abstractmethod


logger = logging.getLogger(__name__)


class OTPProvider(ABC):
    """
    Abstract interface for OTP delivery providers.
    """

    @abstractmethod
    async def send_otp(self, phone: str, otp: str) -> bool:
        """
        Send an OTP to the supplied phone number.

        Args:
            phone: Phone number in E.164 format.
            otp: 6-digit OTP.

        Returns:
            True if SMS was successfully submitted.
            False otherwise.
        """
        ...


class DevLogOTPProvider(OTPProvider):
    """
    Development stub provider that logs the generated OTP to console/logs.
    """

    async def send_otp(self, phone: str, otp: str) -> bool:
        logger.info("DEV OTP generated for %s: %s", phone, otp)
        print(f"\n[DEV MODE] OTP for {phone}: {otp}\n")
        return True