# backend/services/ocr/__init__.py
# OCR text extraction service for Document Analyzer (Module 7).
from .extractor import extract_text, OCRExtractionError

__all__ = ["extract_text", "OCRExtractionError"]
