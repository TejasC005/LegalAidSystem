"""
LEXIS — Application Settings (Module 1)
-----------------------------------------
Pydantic Settings reads every value from the .env file (or environment
variables in production).  Nothing is hardcoded here — if a required
variable is missing, the app fails immediately with a clear error
instead of silently using a wrong default.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    All application configuration lives here.
    Every field maps 1-to-1 to a line in .env / environment variables.
    """

    # ── App ─────────────────────────────────────────────────────────────
    APP_NAME: str = "LEXIS API"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"     # "development" | "production"
    SECRET_KEY: str                       # Required — JWT / session signing

    # ── MongoDB (Motor async driver) ─────────────────────────────────────
    MONGODB_URI: str                      # e.g. mongodb://localhost:27017
    MONGODB_DB_NAME: str = "lexis"        # Database name inside Mongo

    # ── Redis ────────────────────────────────────────────────────────────
    REDIS_URL: str                        # e.g. redis://localhost:6379/0

    # ── JWT ───────────────────────────────────────────────────────
    JWT_ACCESS_EXPIRE_MINUTES: int = 15   # Access token lifetime (15 min)
    JWT_REFRESH_EXPIRE_DAYS: int = 7      # Refresh token lifetime (7 days)

    # ── OTP ───────────────────────────────────────────────────────
    OTP_TTL_SECONDS: int = 300            # OTP valid for 5 minutes
    OTP_MAX_ATTEMPTS: int = 3             # Max wrong guesses before OTP is invalidated
    OTP_RATE_LIMIT_MAX: int = 3           # Max send-otp calls per window per phone
    OTP_RATE_LIMIT_WINDOW_SECONDS: int = 60  # Rate limit window duration

    # ── CORS — frontend origin (never use "*") ───────────────────────────
    FRONTEND_ORIGIN: str = "http://localhost:5173"

    # ── LLM (Gemini) ──────────────────────────────────────────────────────
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL_DEV: str = "gemini-3.6-flash"
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL_DEV: str = "gpt-4o-mini"
    OPENAI_MODEL_DEMO: str = "gpt-4o"

    # ── Firebase Auth ─────────────────────────────────────────────────────
    FIREBASE_PROJECT_ID: str = ""
    FIREBASE_PRIVATE_KEY: str = ""
    FIREBASE_CLIENT_EMAIL: str = ""

    # ── Qdrant Vector DB (Module 5) ───────────────────────────────────────
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    QDRANT_COLLECTION_NAME: str = "legal_knowledge_base"
    QDRANT_API_KEY: str = ""
    QDRANT_STORAGE_PATH: str = "./qdrant_storage"

    # ── Scam Detection (Module 8) ─────────────────────────────────────────
    # Separate Qdrant collection for scam pattern embeddings.
    # MongoDB collection `scam_patterns` is the authoritative source for alert content.
    SCAM_COLLECTION_NAME: str = "scam_patterns"

    # ── Filing Guide (Module 9) ───────────────────────────────────────────────
    # MongoDB collection storing the verified filing authority directory.
    # Seeded from backend/data/filing_authorities/filing_seed.json.
    # No Qdrant collection — exact-match lookup by doc_type only (no semantic search).
    FILING_COLLECTION_NAME: str = "filing_authorities"

    # ── Vault / Storage (Module 7 + Module 10) ──────────────────────────────
    VAULT_STORAGE_PATH: str = "./vault_storage"
    UPLOAD_MAX_SIZE_MB: int = 10        # Max uploaded file size for Document Analyzer

    # ── Vault Encryption (Module 10) ─────────────────────────────────────────
    # AES-256-GCM key for encrypting vault documents at rest.
    # Must be a base64-encoded 32-byte (256-bit) random key.
    # Generate: python -c "import secrets,base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"
    # WHY NOT DEFERRED TO MODULE 14: Vault stores passports/Aadhaar. Data written
    # today is stored today. Deferring encryption to Module 14 means sensitive
    # documents sit as plaintext on disk for 4 modules — unacceptable.
    # Module 14 will VERIFY this encryption is in place, not enable it.
    VAULT_ENCRYPTION_KEY: str = ""      # Required for vault uploads; app warns if empty
    VAULT_COLLECTION_NAME: str = "vault_documents"
    DEADLINE_COLLECTION_NAME: str = "vault_deadlines"

    # -- Memory & Reflection (Module 11) -----------------------------------------
    # MongoDB collection for Confirmation Agent reflection pass logs.
    # Queryable by the Admin Dashboard (Module 12) for quality analytics.
    REFLECTION_LOG_COLLECTION: str = "reflection_logs"
    # Redis session TTL in seconds (default: 24 hours).
    # Sessions older than this are automatically expired from Redis.
    SESSION_TTL_SECONDS: int = 86_400

    # ── Email Notifications (Module 10) ──────────────────────────────────────
    # SMTP settings for deadline reminder emails.
    # In ENVIRONMENT=development or when SMTP_HOST is empty, emails are logged
    # to the console instead of being sent — no real SMTP server needed for dev/tests.
    SMTP_HOST: str = ""                  # e.g. smtp.gmail.com
    SMTP_PORT: int = 587                 # TLS port (use 465 for SSL)
    SMTP_USER: str = ""                  # SMTP login username
    SMTP_PASS: str = ""                  # SMTP login password
    SMTP_FROM: str = "noreply@lexis.local"  # From address in sent emails

    # ── Scheduling ────────────────────────────────────────────────────────────
    NOTIFICATION_CHECK_INTERVAL_MINUTES: int = 60

    # Pydantic v2 config: look for a .env file in the backend directory
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",  # silently ignore any unrecognised env vars
    )

    @property
    def is_production(self) -> bool:
        """True when running in a production environment."""
        return self.ENVIRONMENT.lower() == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Returns a cached Settings singleton.
    Using lru_cache means .env is parsed exactly once at startup —
    subsequent calls get the same object instantly.
    """
    return Settings()
