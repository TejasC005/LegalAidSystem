"""
=============================================================================
LEXIS — OCR Text Extraction Service (Module 7)
=============================================================================

HOW OCR WORKS (PLAIN-LANGUAGE EXPLANATION FOR BEGINNERS)
----------------------------------------------------------
OCR = Optical Character Recognition.  It's how a computer "reads" text from
an image or a scanned document.

Step 1 — Image Pre-processing:
  The raw image is converted to greyscale and contrast is boosted so that
  dark characters stand out clearly from the white/light background.
  Any noise (speckles, shadows) is reduced.

Step 2 — Character Recognition:
  The OCR engine scans the image line by line, top to bottom.  For each
  dark pixel blob it finds, it compares the blob's shape against thousands
  of learned letter shapes.  The best match is recorded as a character.
  Spaces and line breaks are detected from the gaps between blobs.

Step 3 — Output:
  The recognized characters are assembled into strings and returned as
  plain text, which our clause classifier can then process.

TWO PATHS: DIGITAL PDF vs. SCANNED IMAGE
------------------------------------------
Not all PDFs need OCR.  When a PDF is created digitally (Word → Save as PDF),
the text is already stored inside the file as machine-readable characters.
We can extract it directly — no image processing needed.

  Path A — Digital PDF (via PyMuPDF / fitz):
    → Open PDF → iterate pages → extract text layer → return as string.
    Fast (<100ms), no external binary needed.

  Path B — Scanned PDF or Image (via Pillow + pytesseract):
    → Convert image/page to Pillow Image → call Tesseract OCR → return text.
    Slower (~1-3s per page), requires Tesseract binary installed on OS.

    TESSERACT INSTALLATION (required for image OCR, not for digital PDF):
      Windows: Download installer from https://github.com/UB-Mannheim/tesseract/wiki
               Add install path to PATH or set pytesseract.pytesseract.tesseract_cmd
      Linux:   sudo apt install tesseract-ocr
      Docker:  RUN apt-get install -y tesseract-ocr
"""

import logging
import io
from typing import Optional

logger = logging.getLogger(__name__)

# Supported MIME types for each extraction path
PDF_MIME = "application/pdf"
IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp"}


class OCRExtractionError(Exception):
    """Raised when text extraction fails and no fallback is possible."""
    pass


def extract_text(file_bytes: bytes, content_type: str) -> str:
    """
    Extracts plain text from a PDF or image file.

    HOW TO CALL THIS:
        text = extract_text(file_bytes=b"...", content_type="application/pdf")

    RETURNS:
        Extracted text as a UTF-8 string.
        Returns empty string if no text could be extracted (e.g., blank page).

    RAISES:
        OCRExtractionError if the file type is unsupported or extraction fails fatally.

    NOTE: This function is synchronous.  The calling async endpoint should use
    asyncio.to_thread() to run it without blocking the event loop.
    """
    ct = content_type.lower()

    if ct == PDF_MIME:
        return _extract_from_pdf(file_bytes)
    elif ct in IMAGE_MIMES:
        return _extract_from_image(file_bytes)
    else:
        raise OCRExtractionError(
            f"Unsupported content type for OCR extraction: {ct}"
        )


def _extract_from_pdf(file_bytes: bytes) -> str:
    """
    Extracts text from a PDF file using PyMuPDF (fitz).

    Path A: Digital text PDFs — PyMuPDF reads the text layer directly.
    Path B: If a page has no text layer (scanned page), we attempt Tesseract OCR.

    PyMuPDF is imported here (not at module level) so that the import is
    deferred — if PyMuPDF is not installed, only PDF paths fail, not
    the whole service.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise OCRExtractionError(
            "PyMuPDF is not installed. Run: pip install PyMuPDF"
        )

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception as exc:
        raise OCRExtractionError(f"Failed to open PDF: {exc}") from exc

    extracted_pages = []
    for page_num, page in enumerate(doc):
        # Try digital text first (fast path)
        text = page.get_text("text").strip()

        if text:
            extracted_pages.append(text)
            logger.debug("PDF page %d: digital text extracted (%d chars)", page_num + 1, len(text))
        else:
            # No digital text on this page — try OCR on the rendered image
            logger.debug("PDF page %d: no digital text, attempting OCR", page_num + 1)
            try:
                # Render page to a pixmap (image) at 150 DPI (balance of speed/accuracy)
                mat = fitz.Matrix(150 / 72, 150 / 72)
                pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
                img_bytes = pix.tobytes("png")
                ocr_text = _run_tesseract(img_bytes)
                if ocr_text:
                    extracted_pages.append(ocr_text)
                    logger.debug("PDF page %d: OCR extracted %d chars", page_num + 1, len(ocr_text))
            except Exception as ocr_exc:
                # OCR failure on a single page is non-fatal — log and skip
                logger.warning(
                    "OCR failed on PDF page %d: %s", page_num + 1, ocr_exc
                )

    doc.close()
    full_text = "\n\n".join(extracted_pages).strip()
    logger.info("PDF extraction complete: %d chars from %d pages", len(full_text), len(extracted_pages))
    return full_text


def _extract_from_image(file_bytes: bytes) -> str:
    """
    Extracts text from a JPEG, PNG, or WebP image using Tesseract OCR.

    Requires:
      - Pillow (`pip install Pillow`)
      - pytesseract (`pip install pytesseract`)
      - Tesseract binary on PATH
    """
    return _run_tesseract(file_bytes)


def _run_tesseract(image_bytes: bytes) -> str:
    """
    Runs Tesseract OCR on raw image bytes and returns extracted text.

    Returns empty string if Tesseract is not installed (graceful degradation).
    """
    try:
        from PIL import Image
        import pytesseract
    except ImportError:
        logger.warning(
            "Tesseract OCR not available (Pillow/pytesseract not installed). "
            "Returning empty string. Install: pip install Pillow pytesseract"
        )
        return ""

    try:
        image = Image.open(io.BytesIO(image_bytes))
        # lang='eng+hin' would add Hindi support if Tesseract's Hindi language pack is installed.
        # Default 'eng' is used here for maximum compatibility in dev.
        text = pytesseract.image_to_string(image, lang="eng")
        return text.strip()
    except Exception as exc:
        logger.warning("Tesseract OCR error: %s", exc)
        return ""
