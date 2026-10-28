# backend/tests/conftest.py
"""
Shared pytest configuration for LEXIS backend tests.

IMPORTANT — why we set env vars here:
  Pydantic Settings reads required vars (SECRET_KEY, MONGODB_URI, REDIS_URL)
  when Settings() is first instantiated.  In tests we don't have a real .env
  file, so we inject minimal test values via environment variables BEFORE any
  module-level code runs.  conftest.py is guaranteed to load before any test
  module, so this is the right place.
"""
import os

# Set required env vars before any module-level imports run
os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-long-enough-for-hs256-signing")
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ENVIRONMENT", "test")
