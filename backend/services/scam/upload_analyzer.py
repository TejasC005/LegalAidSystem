"""
=============================================================================
LEXIS — Scam Document & Media Upload Parser
=============================================================================
Validates citizen-submitted files (PDF, DOCX, TXT, JSON, PNG, JPG, JPEG, WEBP),
enforces security limits (max 15MB, magic byte checks, zero-execution sandbox),
and extracts normalized text using PyMuPDF, python-docx, Pillow/Tesseract, and
fallback Vision OCR.
"""

import io
import json
import logging
from pathlib import Path
from typing import Tuple

from services.ocr.extractor import extract_text, OCRExtractionError

logger = logging.getLogger(__name__)

# Maximum file size for citizen uploads (15 MB)
MAX_SCAM_UPLOAD_SIZE = 15 * 1024 * 1024

SUPPORTED_EXTENSIONS = {
    ".pdf", ".docx", ".txt", ".json", ".png", ".jpg", ".jpeg", ".webp"
}

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
    "application/json",
    "text/json",
    "image/png",
    "image/jpeg",
    "image/webp",
}


class ScamUploadValidationError(Exception):
    """Raised when an uploaded document fails security, format, or size validation."""
    pass


class ScamUploadParser:
    """
    Validates and extracts content from citizen uploaded documents and images.
    """

    @classmethod
    def validate_file(cls, file_bytes: bytes, filename: str, content_type: str = "") -> str:
        """
        Validates file size, extension, and magic signatures.
        Returns normalized file type: 'pdf', 'docx', 'txt', 'json', 'image'.
        """
        if not file_bytes or len(file_bytes) == 0:
            raise ScamUploadValidationError("The uploaded file is empty.")

        if len(file_bytes) > MAX_SCAM_UPLOAD_SIZE:
            mb = len(file_bytes) / (1024 * 1024)
            raise ScamUploadValidationError(
                f"File size ({mb:.1f} MB) exceeds maximum limit of 15 MB."
            )

        ext = Path(filename).suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            raise ScamUploadValidationError(
                f"Unsupported file format '{ext}'. "
                f"Supported formats: PDF, DOCX, TXT, JSON, PNG, JPG, JPEG, WEBP."
            )

        # Magic byte signature verification
        if ext == ".pdf":
            if not file_bytes.startswith(b"%PDF"):
                raise ScamUploadValidationError("Invalid PDF: Missing %PDF signature.")
            return "pdf"

        elif ext == ".docx":
            if not file_bytes.startswith(b"PK\x03\x04"):
                raise ScamUploadValidationError("Invalid DOCX: Missing ZIP container signature.")
            return "docx"

        elif ext == ".json":
            try:
                json.loads(file_bytes.decode("utf-8"))
            except Exception as exc:
                raise ScamUploadValidationError(f"Invalid JSON file: {exc}")
            return "json"

        elif ext == ".txt":
            try:
                file_bytes.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    file_bytes.decode("latin-1")
                except Exception:
                    raise ScamUploadValidationError("Invalid TXT file: Unable to decode text encoding.")
            return "txt"

        elif ext in {".png", ".jpg", ".jpeg", ".webp"}:
            if ext == ".png" and not file_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ScamUploadValidationError("Invalid PNG image signature.")
            elif ext in {".jpg", ".jpeg"} and not file_bytes.startswith(b"\xff\xd8\xff"):
                raise ScamUploadValidationError("Invalid JPEG image signature.")
            elif ext == ".webp" and not (file_bytes.startswith(b"RIFF") and b"WEBP" in file_bytes[:16]):
                raise ScamUploadValidationError("Invalid WebP image signature.")
            return "image"

        return "unknown"

    @classmethod
    def extract_text_content(cls, file_bytes: bytes, file_type: str, content_type: str = "") -> str:
        """
        Extracts plain text content from validated file bytes.
        """
        if file_type == "pdf":
            try:
                text = extract_text(file_bytes=file_bytes, content_type="application/pdf")
                if not text or not text.strip():
                    raise ScamUploadValidationError(
                        "PDF text extraction returned empty content. "
                        "If this is a scanned document, ensure Tesseract OCR is available."
                    )
                return text.strip()
            except OCRExtractionError as exc:
                raise ScamUploadValidationError(f"OCR/PDF extraction error: {exc}")
            except Exception as exc:
                raise ScamUploadValidationError(f"Failed to read PDF file: {exc}")

        elif file_type == "docx":
            try:
                import docx
                doc = docx.Document(io.BytesIO(file_bytes))
                lines = [p.text for p in doc.paragraphs if p.text.strip()]
                for table in doc.tables:
                    for row in table.rows:
                        row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                        if row_text:
                            lines.append(row_text)
                full_text = "\n".join(lines).strip()
                if not full_text:
                    raise ScamUploadValidationError("DOCX document contains no readable text.")
                return full_text
            except Exception as exc:
                raise ScamUploadValidationError(f"Failed to extract text from DOCX: {exc}")

        elif file_type == "txt":
            try:
                return file_bytes.decode("utf-8").strip()
            except UnicodeDecodeError:
                return file_bytes.decode("latin-1", errors="replace").strip()

        elif file_type == "json":
            try:
                data = json.loads(file_bytes.decode("utf-8"))
                return cls._flatten_json_to_text(data)
            except Exception as exc:
                raise ScamUploadValidationError(f"Failed to parse JSON content: {exc}")

        elif file_type == "image":
            try:
                # Use standard extraction (Tesseract with fallback to multimodal vision)
                ct = content_type or "image/jpeg"
                text = extract_text(file_bytes=file_bytes, content_type=ct)
                if not text or not text.strip():
                    raise ScamUploadValidationError(
                        "Could not extract legible text from this image. "
                        "Please provide a clearer screenshot or paste the text directly."
                    )
                return text.strip()
            except Exception as exc:
                raise ScamUploadValidationError(f"Image text extraction error: {exc}")

        raise ScamUploadValidationError(f"Unsupported file extraction type: {file_type}")

    @classmethod
    def _flatten_json_to_text(cls, data) -> str:
        """
        Recursively flattens JSON data structures into readable text blocks.
        """
        if isinstance(data, str):
            return data
        elif isinstance(data, (int, float, bool)):
            return str(data)
        elif isinstance(data, list):
            return "\n".join(cls._flatten_json_to_text(item) for item in data if item)
        elif isinstance(data, dict):
            # Prioritize standard message keys
            parts = []
            for k in ["title", "subject", "message", "body", "text", "description", "content"]:
                if k in data and isinstance(data[k], str):
                    parts.append(f"{k.capitalize()}: {data[k]}")
            # Add remaining keys
            for k, v in data.items():
                if k.lower() not in ["title", "subject", "message", "body", "text", "description", "content"]:
                    flat_v = cls._flatten_json_to_text(v)
                    if flat_v:
                        parts.append(f"{k}: {flat_v}")
            return "\n".join(parts)
        return ""
