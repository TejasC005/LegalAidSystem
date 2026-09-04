"""
=============================================================================
LEXIS — Vault Encryption Service (Module 10)
=============================================================================

WHY WE ENCRYPT NOW (NOT IN MODULE 14)
---------------------------------------
The original implementation plan deferred encryption to Module 14
(Security Hardening Pass). That plan assumed the Vault would be a later
module added on top of existing agents. In practice, this module handles the
MOST sensitive data in LEXIS — uploaded Aadhaar cards, passports, lease
agreements, and legal notices. There is no safe "encrypt it later" window:

    A document stored TODAY is stored TODAY.

If we deferred to Module 14, every document uploaded in Modules 10–13 would
sit in plaintext on disk — readable by anyone with server filesystem access,
including an attacker who gains a foothold or a cloud provider employee with
access to the underlying storage. For data of this sensitivity, encryption
must happen at the moment of write. Module 14 will VERIFY and AUDIT that the
encryption is correct (read a raw file, confirm it is ciphertext, not plaintext)
— not enable it for the first time.

HOW AES-256-GCM WORKS (PLAIN LANGUAGE)
-----------------------------------------
AES = Advanced Encryption Standard. 256 = the key is 256 bits (32 bytes).
GCM = Galois/Counter Mode — the mode that turns AES (a block cipher) into an
authenticated encryption scheme.

Three components:
  KEY   — 32 random bytes. This is the secret. It lives ONLY in the VAULT_ENCRYPTION_KEY
           env variable, never on disk alongside the encrypted files.
  NONCE — 12 random bytes generated fresh for every single encryption call.
           Also called an IV (initialization vector). Even if two files have
           identical content, different nonces produce completely different
           ciphertext — preventing pattern analysis.
  TAG   — 16 bytes automatically appended by GCM. It is a cryptographic
           checksum. If anyone tampers with the ciphertext (even one bit),
           decryption fails with an InvalidTag error — not silently returning
           wrong data.

Storage layout on disk (per encrypted file):
    [12-byte nonce][ciphertext bytes][16-byte GCM tag]
    ↑ prepended                                      ↑ appended by cryptography

Why nonce is stored WITH the ciphertext: the nonce is NOT a secret —
it just needs to be unique per encryption. Storing it alongside the
ciphertext is the standard practice. The KEY must never be stored there.

KEY MANAGEMENT
---------------
The VAULT_ENCRYPTION_KEY setting must be a base64-encoded 32-byte random key.

Generate one with:
    python -c "import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"

Store it in backend/.env:
    VAULT_ENCRYPTION_KEY=<your_generated_base64_key>

NEVER store the key:
  - In the same directory as encrypted files
  - In the database alongside encrypted records
  - In version control
  - In application logs

In production: use a proper key management service (AWS KMS, HashiCorp Vault,
Google Cloud KMS) — the key in .env is for development only.
"""

import base64
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# ── Key size constants ────────────────────────────────────────────────────────
AES_KEY_SIZE_BYTES = 32   # 256 bits
GCM_NONCE_SIZE_BYTES = 12  # 96 bits — standard for GCM


class VaultCryptoError(Exception):
    """
    Raised when encryption or decryption fails.
    Wrapping the cryptography library's exceptions in a domain-specific
    error class prevents leaking implementation details to callers.
    """
    pass


def _get_vault_key() -> bytes:
    """
    Reads and decodes the VAULT_ENCRYPTION_KEY from settings.

    Returns the raw 32-byte AES key.
    Raises VaultCryptoError if the key is missing or malformed.

    WHY LAZY IMPORT:
    Settings are loaded from .env. During unit tests, we patch the key
    in environment variables. Calling get_settings() at module import time
    would read the (empty) env before the test patches it. Lazy import means
    we read it at the moment it is first needed.
    """
    try:
        from core.config import get_settings
        settings = get_settings()
        key_b64 = settings.VAULT_ENCRYPTION_KEY
    except Exception:
        # Fallback: check environment directly (useful in tests)
        key_b64 = os.environ.get("VAULT_ENCRYPTION_KEY", "")

    if not key_b64:
        raise VaultCryptoError(
            "VAULT_ENCRYPTION_KEY is not set in .env. "
            "Generate one with: python -c \"import secrets, base64; "
            "print(base64.b64encode(secrets.token_bytes(32)).decode())\""
        )

    try:
        key_bytes = base64.b64decode(key_b64)
    except Exception as exc:
        raise VaultCryptoError(
            f"VAULT_ENCRYPTION_KEY is not valid base64: {exc}"
        ) from exc

    if len(key_bytes) != AES_KEY_SIZE_BYTES:
        raise VaultCryptoError(
            f"VAULT_ENCRYPTION_KEY must be exactly 32 bytes when decoded. "
            f"Got {len(key_bytes)} bytes. Regenerate the key."
        )

    return key_bytes


def encrypt_bytes(plaintext: bytes, key: Optional[bytes] = None) -> bytes:
    """
    Encrypts plaintext bytes using AES-256-GCM.

    The key defaults to the VAULT_ENCRYPTION_KEY from settings if not provided.
    Providing a key explicitly is useful for unit tests.

    Returns a single bytes blob:
        [12-byte nonce] + [ciphertext] + [16-byte GCM auth tag]

    This format is self-contained — everything needed to decrypt is in the blob,
    except for the key (which stays in env, never in the blob).

    RAISES:
        VaultCryptoError — if the key is missing, wrong size, or encryption fails.
    """
    if key is None:
        key = _get_vault_key()

    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        raise VaultCryptoError(
            "cryptography library not installed. Run: pip install cryptography"
        )

    try:
        # Generate a fresh random nonce for each encryption call.
        # NEVER reuse a nonce with the same key — GCM security breaks if you do.
        nonce = os.urandom(GCM_NONCE_SIZE_BYTES)

        aesgcm = AESGCM(key)
        # encrypt() returns ciphertext + tag concatenated (tag appended by the library)
        ciphertext_with_tag = aesgcm.encrypt(nonce, plaintext, associated_data=None)

        # Prepend the nonce so we can recover it during decryption
        result = nonce + ciphertext_with_tag

        logger.debug(
            "AES-256-GCM encryption complete",
            extra={
                "plaintext_size": len(plaintext),
                "ciphertext_size": len(result),
            },
        )
        return result

    except Exception as exc:
        raise VaultCryptoError(f"Encryption failed: {exc}") from exc


def decrypt_bytes(encrypted_blob: bytes, key: Optional[bytes] = None) -> bytes:
    """
    Decrypts a blob produced by encrypt_bytes().

    Expected format:
        [12-byte nonce] + [ciphertext] + [16-byte GCM auth tag]

    The key defaults to the VAULT_ENCRYPTION_KEY from settings if not provided.

    RAISES:
        VaultCryptoError — if:
          - The blob is too short (< 28 bytes: 12 nonce + at least 1 byte + 16 tag)
          - The GCM auth tag is invalid (data was tampered with)
          - The key is wrong
    """
    if key is None:
        key = _get_vault_key()

    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        raise VaultCryptoError(
            "cryptography library not installed. Run: pip install cryptography"
        )

    # Minimum valid blob: 12 (nonce) + 1 (data) + 16 (tag) = 29 bytes
    if len(encrypted_blob) < GCM_NONCE_SIZE_BYTES + 16 + 1:
        raise VaultCryptoError(
            f"Encrypted blob is too short ({len(encrypted_blob)} bytes). "
            "It may be corrupted or not an encrypted blob."
        )

    try:
        # Extract the nonce from the beginning
        nonce = encrypted_blob[:GCM_NONCE_SIZE_BYTES]
        ciphertext_with_tag = encrypted_blob[GCM_NONCE_SIZE_BYTES:]

        aesgcm = AESGCM(key)
        # decrypt() verifies the GCM tag and raises InvalidTag if tampered
        plaintext = aesgcm.decrypt(nonce, ciphertext_with_tag, associated_data=None)

        logger.debug(
            "AES-256-GCM decryption complete",
            extra={"plaintext_size": len(plaintext)},
        )
        return plaintext

    except Exception as exc:
        # The cryptography library raises InvalidTag on authentication failure.
        # We wrap it to avoid leaking internal details, but keep the message clear.
        error_msg = str(exc)
        if "InvalidTag" in type(exc).__name__ or "tag" in error_msg.lower():
            raise VaultCryptoError(
                "Decryption failed: authentication tag mismatch. "
                "The data may have been tampered with, or the wrong key was used."
            ) from exc
        raise VaultCryptoError(f"Decryption failed: {exc}") from exc


def generate_vault_key() -> str:
    """
    Utility: generates a fresh base64-encoded 32-byte AES key.

    Run this once to generate a key for your .env:
        python -c "from security.vault_crypto import generate_vault_key; print(generate_vault_key())"

    Copy the output into VAULT_ENCRYPTION_KEY in backend/.env.
    """
    raw_key = os.urandom(AES_KEY_SIZE_BYTES)
    return base64.b64encode(raw_key).decode()
