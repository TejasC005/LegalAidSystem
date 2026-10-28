# backend/utils/logging.py
"""
LEXIS — Structured JSON Logging (Module 1)
-------------------------------------------
Configures the standard Python `logging` library to emit every log line
as a single JSON object.  This makes logs machine-parseable — the Admin
Dashboard (Module 12) will be able to filter, search, and chart them.

Usage anywhere in the codebase:
    import logging
    logger = logging.getLogger(__name__)
    logger.info("User queried rights agent", extra={"user_id": "abc"})
"""

import logging
import sys

from pythonjsonlogger import jsonlogger


def setup_logging(log_level: str = "INFO") -> None:
    """
    Call once at application startup to configure structured JSON logging.

    Args:
        log_level: Minimum severity to emit ("DEBUG", "INFO", "WARNING", …).
                   In production, prefer "WARNING" or higher.
    """
    # Build a JSON formatter — every field added via extra={} appears in the log
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(module)s %(funcName)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        rename_fields={"asctime": "timestamp", "levelname": "level"},
    )

    # Stream handler → stdout (Docker / cloud log collectors read stdout)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    # Root logger — affects all loggers in the app unless they override
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    root_logger.handlers.clear()   # Remove any handlers added before setup
    root_logger.addHandler(handler)

    # Quieten noisy third-party libraries
    logging.getLogger("motor").setLevel(logging.WARNING)
    logging.getLogger("pymongo").setLevel(logging.WARNING)
    logging.getLogger("redis").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
