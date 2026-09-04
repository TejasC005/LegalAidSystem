# backend/services/storage/__init__.py
# Secure per-user file storage service — used by Module 7 (Document Analyzer)
# and reused by Module 10 (Vault & Deadline Agent).
from .secure_storage import SecureStorageService, StoredFileMeta, get_storage_service

__all__ = ["SecureStorageService", "StoredFileMeta", "get_storage_service"]
