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


def _find_tesseract_binary() -> Optional[str]:
    """Scans system PATH and common Windows installation directories for tesseract executable."""
    import shutil
    import os
    which_tess = shutil.which("tesseract")
    if which_tess:
        return which_tess

    common_windows_paths = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.expanduser(r"~\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"),
    ]
    for p in common_windows_paths:
        if os.path.exists(p):
            return p
    return None


def _preprocess_image(image_bytes: bytes) -> bytes:
    """
    Normalizes EXIF orientation (fixing mobile camera photo rotation)
    and downscales oversized images (max 2048px) to reduce transfer latency
    and prevent API timeouts while preserving crisp text legibility.
    """
    try:
        from PIL import Image, ImageOps
        img = Image.open(io.BytesIO(image_bytes))

        # 1. Normalize EXIF orientation tag
        img = ImageOps.exif_transpose(img)

        # 2. Downscale if longest dimension exceeds 2048px
        max_dim = 2048
        if max(img.size) > max_dim:
            img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

        # 3. Convert RGBA to RGB for standard JPEG encoding
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        out_io = io.BytesIO()
        img.save(out_io, format="JPEG", quality=90)
        return out_io.getvalue()
    except Exception as exc:
        logger.warning("Image pre-processing failed, using raw bytes: %s", exc)
        return image_bytes


def _extract_from_image(file_bytes: bytes, content_type: str = "image/jpeg") -> str:
    """
    Extracts text from a JPEG, PNG, or WebP image.
    Applies EXIF normalization, attempts local Tesseract OCR, and falls back to
    resilient multi-model Gemini/OpenAI Multimodal Vision.
    """
    processed_bytes = _preprocess_image(file_bytes)

    text = _run_tesseract(processed_bytes)
    if text.strip():
        return text

    # Fallback to Multimodal Vision cascade
    logger.info("Local OCR empty or unavailable. Attempting Multimodal Vision OCR cascade...")
    vision_text = _run_gemini_vision(processed_bytes, mime_type=content_type)
    if vision_text.strip():
        logger.info("Multimodal Vision OCR extracted %d characters", len(vision_text))
        return vision_text

    return text


def _run_tesseract(image_bytes: bytes) -> str:
    """
    Runs Tesseract OCR on raw image bytes and returns extracted text.
    Configures tesseract_cmd if found in common Windows locations.
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

    tess_path = _find_tesseract_binary()
    if tess_path:
        pytesseract.pytesseract.tesseract_cmd = tess_path

    try:
        image = Image.open(io.BytesIO(image_bytes))
        text = pytesseract.image_to_string(image, lang="eng")
        return text.strip()
    except Exception as exc:
        logger.warning("Tesseract OCR error: %s", exc)
        return ""


def _run_gemini_vision(image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
    """
    Multimodal Vision OCR fallback using Google GenAI SDK with multi-model cascade.
    Sequentially attempts active flash models (gemini-2.5-flash, gemini-flash-latest,
    gemini-3.8-flash, gemini-1.5-flash) and falls back to OpenAI Vision if needed.
    """
    from core.config import get_settings
    settings = get_settings()

    # ── Tier 1: Google Gemini Multi-Model Cascade ──────────────────────────────
    api_key = settings.GEMINI_API_KEY
    if api_key and not api_key.startswith("sk-replace"):
        # Prioritize high-availability active flash and lite models
        candidate_models = [
            settings.GEMINI_MODEL_DEV or "gemini-3.5-flash",
            "gemini-3.5-flash",
            "gemini-3.1-flash-lite",
            "gemini-3.5-flash-lite",
            "gemini-2.5-flash",
            "gemini-3.7-flash",
            "gemini-3.6-flash",
            "gemini-3.8-flash",
            "gemini-flash-latest",
        ]
        # Preserve order while deduplicating
        seen = set()
        models_to_try = [m for m in candidate_models if not (m in seen or seen.add(m))]

        try:
            import time
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=api_key)

            for model_name in models_to_try:
                for attempt in range(2):
                    try:
                        response = client.models.generate_content(
                            model=model_name,
                            contents=[
                                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                                "Extract and transcribe all text from this document image verbatim. "
                                "Include all names (in both English and Devanagari/regional script if present), "
                                "identification numbers, addresses, dates, and clauses accurately. "
                                "Return only the extracted text without introductory commentary."
                            ]
                        )
                        text = response.text.strip() if response.text else ""
                        if text:
                            logger.info("Gemini Vision OCR succeeded with model '%s' (%d chars)", model_name, len(text))
                            return text
                        break
                    except Exception as exc:
                        err_str = str(exc)
                        logger.warning(
                            "Gemini Vision OCR attempt %d failed with model '%s': %s",
                            attempt + 1,
                            model_name,
                            err_str[:200],
                        )
                        # On temporary rate limits (429) or transient server load (503), wait 1s and retry once
                        if attempt == 0 and ("429" in err_str or "503" in err_str):
                            time.sleep(1.0)
                            continue
                        break
        except Exception as client_exc:
            logger.warning("Google GenAI client initialization failed: %s", client_exc)

    # ── Tier 2: OpenAI GPT-4o-mini Vision Fallback ─────────────────────────────
    openai_key = settings.OPENAI_API_KEY
    if openai_key and not openai_key.startswith("sk-replace"):
        try:
            import base64
            from openai import OpenAI
            b64_img = base64.b64encode(image_bytes).decode("utf-8")
            oai_client = OpenAI(api_key=openai_key)
            completion = oai_client.chat.completions.create(
                model=settings.OPENAI_MODEL_DEV or "gpt-4o-mini",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Extract and transcribe all text from this document image verbatim. "
                                        "Include all names, identification numbers, addresses, dates, and clauses. "
                                        "Return only the extracted text."
                            },
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:{mime_type};base64,{b64_img}"}
                            }
                        ]
                    }
                ]
            )
            oai_text = (completion.choices[0].message.content or "").strip()
            if oai_text:
                logger.info("OpenAI Vision OCR fallback succeeded (%d chars)", len(oai_text))
                return oai_text
        except Exception as oai_exc:
            logger.warning("OpenAI Vision OCR fallback failed: %s", oai_exc)

    return ""

