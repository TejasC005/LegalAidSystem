"""
=============================================================================
LEXIS — File Upload Validator (Module 7)
=============================================================================

WHY WE CHECK FILE CONTENT, NOT JUST THE EXTENSION
----------------------------------------------------
A file extension (.pdf, .jpg) is just a label — any user can rename a file
to have any extension they want.  For example, a user could rename:
  my_script.py  →  my_document.pdf

If we only checked the extension, we would accept that file and pass it to
our PDF processing library.  Unexpected file formats can cause parsing
libraries to behave incorrectly or crash.

The real identity of a file is in its "magic bytes" — the first few bytes
of the file's raw binary content.  Every file format has a standardized
signature:
  PDF:  starts with  %PDF  (bytes: 25 50 44 46)
  JPEG: starts with  FF D8 FF
  PNG:  starts with  89 50 4E 47 (= .PNG in ASCII)

By reading and comparing these bytes against the claimed MIME type, we
confirm the file actually is what it claims to be — regardless of the
extension or what the browser reports in the Content-Type header.

THIS DOES NOT PREVENT ALL ATTACKS — it prevents mislabeled file types.
Module 14 (Security Hardening) will add deeper sandboxing.

ALLOWLISTED FILE TYPES
-----------------------
  application/pdf   — PDF documents (contracts, notices)
  image/jpeg        — JPEG photographs (scanned documents)
  image/png         — PNG screenshots / scans

Max size is configurable via UPLOAD_MAX_SIZE_MB in settings.
"""

import logging
from typing import Tuple

logger = logging.getLogger(__name__)

# ── Allowlisted MIME types ────────────────────────────────────────────────────
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
}

# ── Magic byte signatures ──────────────────────────────────────────────────────
# Maps the expected MIME type to its magic byte prefix.
# We only need to check the first few bytes — no need to read the whole file.
MAGIC_BYTE_SIGNATURES: dict[str, list[bytes]] = {
    "application/pdf": [b"%PDF"],              # All PDFs start with %PDF
    "image/jpeg":      [b"\xff\xd8\xff"],      # JPEG magic bytes (SOI marker)
    "image/png":       [b"\x89PNG\r\n\x1a\n"],  # PNG signature (8 bytes)
}

# How many bytes to read for magic byte detection
MAGIC_BYTE_READ_SIZE = 16


def validate_upload(
    file_bytes: bytes,
    claimed_content_type: str,
    max_size_mb: int = 10,
) -> Tuple[bool, str]:
    """
    Validates an uploaded file for safety before any processing.

    Checks performed (in order):
      1. Size: file must not exceed max_size_mb.
      2. MIME type allowlist: claimed content type must be in ALLOWED_MIME_TYPES.
      3. Magic bytes: actual file content must match the claimed MIME type.

    ARGS:
        file_bytes           — Raw bytes of the uploaded file.
        claimed_content_type — MIME type reported by the browser/client.
                               We normalize and verify this; we do NOT trust it blindly.
        max_size_mb          — Maximum allowed file size in megabytes.

    RETURNS:
        (True, verified_mime_type)  if all checks pass.
        (False, error_message)      if any check fails.

    DESIGN NOTE:
        This function returns a tuple instead of raising an exception so that
        the caller (the FastAPI endpoint) can return a clean HTTP 400 with a
        user-friendly message rather than an unhandled 500.
    """
    max_size_bytes = max_size_mb * 1024 * 1024

    # ── Check 1: File size ─────────────────────────────────────────────────
    if len(file_bytes) == 0:
        return False, "Uploaded file is empty."
    if len(file_bytes) > max_size_bytes:
        size_mb = len(file_bytes) / (1024 * 1024)
        return False, (
            f"File is too large ({size_mb:.1f} MB). "
            f"Maximum allowed size is {max_size_mb} MB."
        )

    # ── Check 2: MIME type allowlist ───────────────────────────────────────
    # Normalize: strip parameters (e.g., "image/jpeg; charset=utf-8" → "image/jpeg")
    normalized_ct = claimed_content_type.split(";")[0].strip().lower()

    if normalized_ct not in ALLOWED_MIME_TYPES:
        return False, (
            f"File type '{normalized_ct}' is not allowed. "
            f"Accepted types: PDF, JPEG, PNG."
        )

    # ── Check 3: Magic bytes — verify actual content matches claimed type ───
    # This catches files where a user renamed e.g. a .py file to .pdf.
    magic_ok, detected_type = _verify_magic_bytes(file_bytes, normalized_ct)
    if not magic_ok:
        logger.warning(
            "Magic byte mismatch: claimed=%s, detected=%s",
            normalized_ct, detected_type,
        )
        return False, (
            f"File content does not match the claimed type '{normalized_ct}'. "
            f"The file appears to be a different format. "
            f"Please upload a genuine PDF, JPEG, or PNG file."
        )

    logger.debug(
        "File validation passed: type=%s, size=%d bytes",
        normalized_ct, len(file_bytes),
    )
    return True, normalized_ct


def _verify_magic_bytes(file_bytes: bytes, claimed_mime: str) -> Tuple[bool, str]:
    """
    Reads the first MAGIC_BYTE_READ_SIZE bytes and checks them against
    the expected signature for claimed_mime.

    Returns (True, claimed_mime) if the signature matches.
    Returns (False, "unknown") if it doesn't.
    """
    header = file_bytes[:MAGIC_BYTE_READ_SIZE]

    expected_signatures = MAGIC_BYTE_SIGNATURES.get(claimed_mime, [])
    for sig in expected_signatures:
        if header.startswith(sig):
            return True, claimed_mime

    # Try to detect what the file actually IS (for logging purposes only)
    detected = "unknown"
    for mime, sigs in MAGIC_BYTE_SIGNATURES.items():
        for sig in sigs:
            if header.startswith(sig):
                detected = mime
                break

    return False, detected


def detect_content_type(file_bytes: bytes) -> str:
    """
    Detects the content type of a file from its magic bytes alone.
    Returns the detected MIME type, or "application/octet-stream" if unknown.

    Used as a helper when the client-provided Content-Type is not trusted.
    """
    header = file_bytes[:MAGIC_BYTE_READ_SIZE]

    for mime, sigs in MAGIC_BYTE_SIGNATURES.items():
        for sig in sigs:
            if header.startswith(sig):
                return mime

    return "application/octet-stream"
