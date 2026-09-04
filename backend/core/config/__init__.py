# backend/core/config/__init__.py
"""
Expose the settings singleton so any module can do:
    from core.config import settings
"""
from .settings import get_settings, Settings

settings = get_settings()

__all__ = ["settings", "get_settings", "Settings"]
