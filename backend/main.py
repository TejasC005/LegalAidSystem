"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    LEXIS Backend — Main Entrypoint                          ║
║                    Module 1: Core Backend Foundation                        ║
╚══════════════════════════════════════════════════════════════════════════════╝

WHAT EACH MAJOR PIECE DOES
───────────────────────────
• create_app()          App factory function.  Creates and configures the
                        FastAPI instance. Using a factory (instead of a
                        bare `app = FastAPI()`) lets tests call
                        create_app() with a fresh app each time without
                        polluting global state.

• @asynccontextmanager  The "lifespan" function runs code BEFORE the app
  lifespan()            starts accepting requests (startup) and AFTER it
                        stops (shutdown).  The `yield` in the middle is
                        where the app lives.  Everything before yield =
                        startup. Everything after yield = teardown.

• app.state             FastAPI's built-in key-value store attached to the
                        app object.  We store the Mongo client, Redis
                        client, DB name, and settings here so any request
                        can access them via `request.app.state`.

• CORSMiddleware        Tells browsers which origins are allowed to make
                        requests to this API.  We read FRONTEND_ORIGIN
                        from .env — never hardcode "*" which would allow
                        ANY website to call our API.

• /api/v1 prefix        All routes are versioned.  When we need breaking
                        changes later, we can add /api/v2 alongside v1
                        without breaking existing clients.

• setup_logging()       Configures every log in the app to emit JSON so
                        the Admin Dashboard (Module 12) can parse them.

WHY THE LIFESPAN PATTERN INSTEAD OF CONNECTING PER REQUEST
────────────────────────────────────────────────────────────
If we connected to MongoDB or Redis on EVERY incoming request:
  1. Each HTTP call would pay a ~20-100 ms TCP handshake to connect.
  2. Under load (100 req/s), we'd open 100 connections/second — the DB
     server would refuse or crash.
  3. We'd need complex error-handling everywhere.

With the lifespan pattern we connect ONCE at startup, hold the connection
pool open, and every request reuses an existing connection from the pool.
This is ~1000× faster per request and uses a predictable, bounded number
of database connections regardless of traffic.

WHAT TO PUT IN YOUR .env FILE TO RUN LOCALLY
──────────────────────────────────────────────
Copy .env.example to .env (cp .env.example .env) and fill in:

  SECRET_KEY          → Any long random string (run: python -c "import secrets; print(secrets.token_hex(32))")
  MONGODB_URI         → mongodb://localhost:27017  (or your Atlas URI)
  MONGODB_DB_NAME     → lexis  (default, leave as-is for dev)
  REDIS_URL           → redis://localhost:6379/0   (or your Redis Cloud URL)
  FRONTEND_ORIGIN     → http://localhost:5173       (Vite dev server default)
  ENVIRONMENT         → development

You do NOT need real Firebase/OpenAI keys yet — those are used in later
modules. Leave them empty or with placeholder values for Module 1.

HOW TO START THE SERVER
────────────────────────
  cd backend
  python -m venv venv
  venv\\Scripts\\activate         # Windows
  pip install -r requirements.txt
  uvicorn main:app --reload
  → http://localhost:8000/api/v1/health
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import get_settings
from db.database import connect_mongo, disconnect_mongo
from db.redis_client import connect_redis, disconnect_redis
from utils.logging import setup_logging
from api.routes.health import router as health_router

# ── Logger for this module ─────────────────────────────────────────────────────
logger = logging.getLogger(__name__)


# ── Lifespan: startup & shutdown hooks ────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Everything BEFORE `yield` runs at startup (once, before any request).
    Everything AFTER `yield` runs at shutdown (once, after last request).

    This is the recommended FastAPI pattern (since v0.93) replacing the
    old on_startup / on_shutdown event decorators.
    """
    settings = get_settings()

    # ── STARTUP ────────────────────────────────────────────────────────────
    # 1. Structured JSON logging — must be first so all subsequent logs are JSON
    log_level = "DEBUG" if not settings.is_production else "WARNING"
    setup_logging(log_level=log_level)

    logger.info(
        "LEXIS backend starting up",
        extra={"env": settings.ENVIRONMENT, "version": settings.APP_VERSION},
    )

    # 2. MongoDB
    mongo_client = await connect_mongo(settings.MONGODB_URI, settings.MONGODB_DB_NAME)

    # 3. Redis
    redis_client = await connect_redis(settings.REDIS_URL)

    # 4. Store everything in app.state so routes can access it via request.app.state
    app.state.settings = settings
    app.state.mongo_client = mongo_client
    app.state.mongo_db_name = settings.MONGODB_DB_NAME
    app.state.redis = redis_client

    # 5. Start the Vault Deadline Scheduler (Module 10)
    # APScheduler fires daily at 09:00 to check deadlines and send proactive reminders.
    # If APScheduler is not installed, a warning is logged and the app starts normally.
    from services.vault.scheduler import start_scheduler
    scheduler = start_scheduler(app)
    app.state.scheduler = scheduler

    # 6. Ensure legal knowledge base is seeded in Qdrant (server or in-memory fallback)
    try:
        from db.qdrant_client import get_qdrant_client
        from services.rag.ingestion import seed_starter_knowledge_base
        from agents.rights_agent.agent import get_rights_agent

        q_client = get_qdrant_client()
        count = seed_starter_knowledge_base(client=q_client, force_recreate=False)
        r_agent = get_rights_agent()
        r_agent.qdrant_client = q_client
        logger.info("Qdrant knowledge base initialized/seeded successfully with %d chunks.", count)
    except Exception as exc:
        logger.warning("Could not seed Qdrant knowledge base at startup: %s", exc)

    # 7. Validate Brevo REST API Email Service configuration
    is_brevo_valid, missing_brevo_fields = settings.validate_brevo_config()
    if not is_brevo_valid:
        logger.warning(
            "⚠️  [CONFIG] Brevo email service is not fully configured (missing: %s). "
            "Email OTP delivery will fail until valid Brevo credentials are set in backend/.env.",
            ", ".join(missing_brevo_fields),
        )
    elif settings.BREVO_API_KEY.startswith("xsmtpsib-"):
        logger.warning(
            "⚠️  [CONFIG] Configured BREVO_API_KEY appears to be an SMTP key (starts with 'xsmtpsib-'). "
            "Brevo REST API requires an API v3 key starting with 'xkeysib-...' from https://app.brevo.com/settings/keys/api."
        )
    else:
        logger.info("Brevo REST API email service configured for sender: %s", settings.BREVO_SENDER_EMAIL)

    logger.info("All connections established. API is ready.")

    # ── Hand control to the running app ───────────────────────────────────
    yield

    # ── SHUTDOWN ───────────────────────────────────────────────────────────
    logger.info("LEXIS backend shutting down — closing connections…")
    # Shut down the scheduler gracefully before closing DB/Redis connections
    _scheduler = getattr(app.state, "scheduler", None)
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
            logger.info("Vault scheduler shut down.")
        except Exception:
            pass
    await disconnect_redis(redis_client)
    await disconnect_mongo(mongo_client)
    logger.info("Shutdown complete.")


# ── App factory ───────────────────────────────────────────────────────────────
def create_app() -> FastAPI:
    """
    App factory: creates and fully configures a FastAPI instance.

    Returning the app from a function (instead of module-level `app = FastAPI()`)
    makes it trivial to create isolated test instances and to parameterise
    config for different environments.
    """
    settings = get_settings()

    application = FastAPI(
        title=settings.APP_NAME,
        description=(
            "Autonomous Multi-Agent Legal Aid System for Indian Citizens. "
            "Provides rights explanation, document drafting, contract analysis, "
            "scam detection, complaint filing guidance, and document vault."
        ),
        version=settings.APP_VERSION,
        docs_url="/api/docs",        # Swagger UI
        redoc_url="/api/redoc",      # ReDoc UI
        openapi_url="/api/openapi.json",
        lifespan=lifespan,           # Attach our startup/shutdown manager
    )

    # ── CORS — restrict to the configured frontend origin ─────────────────
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.FRONTEND_ORIGIN],  # Read from .env, never "*"
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept"],
    )

    # ── Versioned API router ──────────────────────────────────────────────
    # All routes live under /api/v1 — add future routers here
    from fastapi import APIRouter
    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(health_router)

    # Module 2: auth router registered under /api/v1/auth/
    from api.routes.auth import router as auth_router
    api_v1.include_router(auth_router)

    # Module 4: query router registered under /api/v1/query/
    from api.routes.query import router as query_router
    api_v1.include_router(query_router)

    # Module 6: drafts router registered under /api/v1/drafts/
    from api.routes.drafts import router as drafts_router
    api_v1.include_router(drafts_router)

    # Module 7: analysis router registered under /api/v1/analysis/
    from api.routes.analysis import router as analysis_router
    api_v1.include_router(analysis_router)

    # Module 8: scam router registered under /api/v1/scam/
    from api.routes.scam import router as scam_router
    api_v1.include_router(scam_router)

    # Module 9: filing guide router registered under /api/v1/filing/
    from api.routes.filing import router as filing_router
    api_v1.include_router(filing_router)

    # Module 10: vault router registered under /api/v1/vault/
    from api.routes.vault import router as vault_router
    api_v1.include_router(vault_router)

    # Module 12: admin router registered under /api/v1/admin/
    from api.routes.admin import router as admin_router
    api_v1.include_router(admin_router)

    # Module 13: lawyer router registered under /api/v1/lawyer/
    # Scaffold only — no functional features. Role guard: require_role(["lawyer"]).
    from api.routes.lawyer import router as lawyer_router
    api_v1.include_router(lawyer_router)

    # Module 13B: users router registered under /api/v1/users/
    from api.routes.users import router as users_router
    api_v1.include_router(users_router)

    application.include_router(api_v1)

    return application


# ── Application instance ──────────────────────────────────────────────────────
# `uvicorn main:app` references this name.
app = create_app()
