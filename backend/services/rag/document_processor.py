"""
=============================================================================
LEXIS — Legal Knowledge Base Document Processor & Chunker
=============================================================================
Handles text extraction (PDF, DOCX, JSON), legal chunking, embedding generation,
and Qdrant vector indexing for admin-uploaded legal documents.
"""

import hashlib
import io
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from qdrant_client import QdrantClient
from qdrant_client.http import models as rest_models

from services.ocr.extractor import extract_text, OCRExtractionError
from services.rag.embedder import BGEM3Embedder

logger = logging.getLogger(__name__)

# Maximum file size for knowledge base uploads (15 MB)
MAX_KB_FILE_SIZE_BYTES = 15 * 1024 * 1024

# Allowed file extensions & content types
ALLOWED_KB_EXTENSIONS = {".pdf", ".docx", ".json"}
ALLOWED_KB_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/json",
    "text/json",
    "text/plain",
}

# Regex to detect legal section/article headings
SECTION_HEADING_PATTERN = re.compile(
    r'(?:^|\n)(Section\s+\d+[A-Za-z]*(?:\s*\([0-9a-zA-Z]+\))*|Article\s+\d+[A-Za-z]*|Chapter\s+[IVXLCDM\d]+|\bCLAUSE\s+\d+)\b[.:\s\-]*([^\n]*)',
    re.IGNORECASE,
)


class DocumentProcessingError(Exception):
    """Raised when parsing, extracting, or chunking a legal document fails."""
    pass


def validate_kb_file(file_bytes: bytes, filename: str, content_type: str) -> str:
    """
    Validates file extension, size, and magic bytes.
    Returns normalized file_type: 'pdf', 'docx', or 'json'.
    """
    if len(file_bytes) == 0:
        raise DocumentProcessingError("Uploaded file is empty.")

    if len(file_bytes) > MAX_KB_FILE_SIZE_BYTES:
        mb = len(file_bytes) / (1024 * 1024)
        raise DocumentProcessingError(f"File size ({mb:.1f} MB) exceeds maximum limit of 15 MB.")

    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_KB_EXTENSIONS:
        raise DocumentProcessingError(
            f"Unsupported file extension '{ext}'. Only .pdf, .docx, and .json files are supported."
        )

    # Magic byte checks
    if ext == ".pdf":
        if not file_bytes.startswith(b"%PDF"):
            raise DocumentProcessingError("Invalid PDF file: Missing %PDF signature.")
        return "pdf"

    elif ext == ".docx":
        # DOCX is a ZIP container: starts with PK\x03\x04
        if not file_bytes.startswith(b"PK\x03\x04"):
            raise DocumentProcessingError("Invalid DOCX file: Missing ZIP container signature.")
        return "docx"

    elif ext == ".json":
        try:
            json.loads(file_bytes.decode("utf-8"))
        except Exception as exc:
            raise DocumentProcessingError(f"Malformed JSON file: {exc}")
        return "json"

    raise DocumentProcessingError(f"Unsupported file type: {ext}")


def compute_file_hash(file_bytes: bytes) -> str:
    """Computes SHA-256 hash of file bytes for duplicate detection."""
    return hashlib.sha256(file_bytes).hexdigest()


def extract_text_from_kb_file(file_bytes: bytes, file_type: str) -> str:
    """
    Extracts text from PDF, DOCX, or JSON.
    """
    if file_type == "pdf":
        try:
            text = extract_text(file_bytes=file_bytes, content_type="application/pdf")
            if not text or not text.strip():
                raise DocumentProcessingError(
                    "PDF text extraction returned empty content. "
                    "If this is a scanned document, ensure Tesseract OCR is available."
                )
            return text
        except OCRExtractionError as exc:
            raise DocumentProcessingError(f"OCR/PDF extraction error: {exc}")
        except Exception as exc:
            raise DocumentProcessingError(f"Failed to read PDF content: {exc}")

    elif file_type == "docx":
        try:
            import docx
            doc = docx.Document(io.BytesIO(file_bytes))
            parts = []
            for p in doc.paragraphs:
                p_text = p.text.strip()
                if p_text:
                    parts.append(p_text)
            for table in doc.tables:
                for row in table.rows:
                    row_cells = [c.text.strip() for c in row.cells if c.text.strip()]
                    if row_cells:
                        parts.append(" | ".join(row_cells))
            full_text = "\n\n".join(parts)
            if not full_text.strip():
                raise DocumentProcessingError("DOCX file contains no readable text.")
            return full_text
        except Exception as exc:
            raise DocumentProcessingError(f"Failed to extract DOCX text: {exc}")

    elif file_type == "json":
        try:
            data = json.loads(file_bytes.decode("utf-8"))
            if isinstance(data, list):
                # Will be handled in chunking directly
                return json.dumps(data)
            elif isinstance(data, dict):
                return data.get("content") or data.get("text") or json.dumps(data)
            return str(data)
        except Exception as exc:
            raise DocumentProcessingError(f"Failed to decode JSON: {exc}")

    raise DocumentProcessingError(f"Unsupported file type '{file_type}' for extraction.")


def chunk_legal_text(
    raw_text: str,
    file_type: str,
    act_name: str,
    topic: str,
    title: str,
    document_id: str,
) -> List[Dict[str, Any]]:
    """
    Splits legal text into appropriately sized chunks while preserving section headings
    and source references. If JSON array is passed, parses structured records directly.
    """
    chunks: List[Dict[str, Any]] = []

    # Case 1: Structured JSON input
    if file_type == "json":
        try:
            data = json.loads(raw_text)
            if isinstance(data, list):
                for idx, item in enumerate(data, 1):
                    if not isinstance(item, dict):
                        continue
                    content = (item.get("content") or item.get("text") or "").strip()
                    if not content:
                        continue
                    item_act = item.get("act_name") or act_name
                    item_section = item.get("section") or f"Item {idx}"
                    item_title = item.get("title") or title
                    item_topic = item.get("topic") or topic
                    citation = (
                        item.get("citation")
                        or f"{item_act}, {item_section}".strip(", ")
                    )
                    chunks.append({
                        "chunk_id": item.get("id") or f"{document_id}_c{idx}",
                        "section": item_section,
                        "title": item_title,
                        "content": content,
                        "citation": citation,
                        "topic": item_topic,
                        "act_name": item_act,
                    })
                if chunks:
                    return chunks
        except Exception:
            pass

    # Case 2: Unstructured/Structured text from PDF, DOCX, or narrative JSON
    text = raw_text.strip()
    if not text:
        return []

    # Try section boundary splitting
    matches = list(SECTION_HEADING_PATTERN.finditer(text))

    if len(matches) >= 2:
        for idx, match in enumerate(matches):
            section_header = match.group(1).strip()
            section_title = match.group(2).strip()
            start_pos = match.start()
            end_pos = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            section_body = text[start_pos:end_pos].strip()

            # If section body is excessively long (> 1500 chars), split into sub-chunks
            if len(section_body) > 1500:
                paragraphs = [p.strip() for p in section_body.split("\n\n") if p.strip()]
                current_sub = ""
                sub_idx = 1
                for p in paragraphs:
                    if len(current_sub) + len(p) < 1200:
                        current_sub += "\n\n" + p if current_sub else p
                    else:
                        if current_sub:
                            citation = f"{act_name}, {section_header}".strip(", ")
                            chunks.append({
                                "chunk_id": f"{document_id}_c{len(chunks)+1}",
                                "section": section_header,
                                "title": section_title or title,
                                "content": current_sub.strip(),
                                "citation": citation,
                                "topic": topic,
                                "act_name": act_name,
                            })
                            sub_idx += 1
                        current_sub = f"[{section_header} Continued]\n" + p
                if current_sub:
                    citation = f"{act_name}, {section_header}".strip(", ")
                    chunks.append({
                        "chunk_id": f"{document_id}_c{len(chunks)+1}",
                        "section": section_header,
                        "title": section_title or title,
                        "content": current_sub.strip(),
                        "citation": citation,
                        "topic": topic,
                        "act_name": act_name,
                    })
            else:
                citation = f"{act_name}, {section_header}".strip(", ")
                chunks.append({
                    "chunk_id": f"{document_id}_c{len(chunks)+1}",
                    "section": section_header,
                    "title": section_title or title,
                    "content": section_body,
                    "citation": citation,
                    "topic": topic,
                    "act_name": act_name,
                })
    else:
        # Fallback: Sliding window / paragraph chunking (~800 characters)
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        current_chunk = ""
        for p in paragraphs:
            if len(current_chunk) + len(p) < 1000:
                current_chunk += "\n\n" + p if current_chunk else p
            else:
                if current_chunk:
                    idx = len(chunks) + 1
                    citation = f"{act_name}, Part {idx}".strip(", ")
                    chunks.append({
                        "chunk_id": f"{document_id}_c{idx}",
                        "section": f"Part {idx}",
                        "title": title,
                        "content": current_chunk.strip(),
                        "citation": citation,
                        "topic": topic,
                        "act_name": act_name,
                    })
                current_chunk = p
        if current_chunk:
            idx = len(chunks) + 1
            citation = f"{act_name}, Part {idx}".strip(", ")
            chunks.append({
                "chunk_id": f"{document_id}_c{idx}",
                "section": f"Part {idx}",
                "title": title,
                "content": current_chunk.strip(),
                "citation": citation,
                "topic": topic,
                "act_name": act_name,
            })

    return chunks


def prepare_chunk_embeddings(
    chunks: List[Dict[str, Any]],
    embedder: BGEM3Embedder,
) -> Tuple[List[Dict[str, Any]], List[List[float]]]:
    """
    Prepares embeddable text for each chunk and computes BGE-M3 embeddings.
    Matching format: f"{topic}: {title}\nAct: {act_name} {section}\n{content}"
    """
    texts_to_embed = [
        f"{c.get('topic', '')}: {c.get('title', '')}\nAct: {c.get('act_name', '')} {c.get('section', '')}\n{c.get('content', '')}"
        for c in chunks
    ]
    embeddings = embedder.embed_texts(texts_to_embed)
    return chunks, embeddings


def index_chunks_in_qdrant(
    client: QdrantClient,
    collection_name: str,
    document_id: str,
    chunks: List[Dict[str, Any]],
    embeddings: List[List[float]],
    metadata: Dict[str, Any],
    is_active: bool = True,
) -> int:
    """
    Indexes or updates chunks in Qdrant with deterministic UUID point IDs.
    """
    from db.qdrant_client import init_qdrant_collection
    init_qdrant_collection(client, collection_name, vector_size=384, recreate=False)

    points = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for chunk, vector in zip(chunks, embeddings):
        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{document_id}_{chunk['chunk_id']}"))

        payload = {
            "chunk_id": chunk["chunk_id"],
            "document_id": document_id,
            "topic": chunk.get("topic") or metadata.get("topic", ""),
            "act_name": chunk.get("act_name") or metadata.get("act_name", ""),
            "section": chunk.get("section", ""),
            "title": chunk.get("title") or metadata.get("title", ""),
            "content": chunk.get("content", ""),
            "citation": chunk.get("citation", ""),
            "source_doc": metadata.get("file_name", ""),
            "source_type": metadata.get("source_type", "Administrative Legal Upload"),
            "authority": metadata.get("authority", ""),
            "official_source": metadata.get("authority", ""),
            "source_url": metadata.get("source_url", ""),
            "jurisdiction": metadata.get("jurisdiction", "India"),
            "version": metadata.get("version", "1.0"),
            "effective_date": metadata.get("effective_date", ""),
            "verification_status": "admin_verified",
            "is_active": is_active,
            "uploaded_at": now_iso,
        }

        points.append(
            rest_models.PointStruct(
                id=point_id,
                vector=vector,
                payload=payload,
            )
        )

    logger.info("Upserting %d points for document '%s' into Qdrant '%s'", len(points), document_id, collection_name)
    client.upsert(
        collection_name=collection_name,
        points=points,
    )
    return len(points)


def remove_document_vectors_from_qdrant(
    client: QdrantClient,
    collection_name: str,
    document_id: str,
) -> bool:
    """
    Safely removes only the vector points belonging to the specified document_id,
    leaving seed knowledge base points and other documents intact.
    """
    try:
        selector = rest_models.FilterSelector(
            filter=rest_models.Filter(
                must=[
                    rest_models.FieldCondition(
                        key="document_id",
                        match=rest_models.MatchValue(value=document_id),
                    )
                ]
            )
        )
        client.delete(
            collection_name=collection_name,
            points_selector=selector,
        )
        logger.info("Deleted vectors for document '%s' from Qdrant '%s'", document_id, collection_name)
        return True
    except Exception as exc:
        logger.error("Failed to delete vectors for document '%s' from Qdrant: %s", document_id, exc)
        return False
