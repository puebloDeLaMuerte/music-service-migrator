"""Unified configuration loader.

Reads the .env file at the project root once and exposes helpers that each
service adapter can call to pull only the keys it needs.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_loaded = False


def _ensure_loaded() -> None:
    global _loaded
    if not _loaded:
        load_dotenv(_PROJECT_ROOT / ".env")
        _loaded = True


def get(key: str, default: str | None = None) -> str | None:
    _ensure_loaded()
    return os.getenv(key, default)


def require(key: str) -> str:
    """Return an env var or raise with a helpful message."""
    _ensure_loaded()
    value = os.getenv(key)
    if not value:
        raise RuntimeError(
            f"Missing required config: {key}  "
            f"(set it in {_PROJECT_ROOT / '.env'})"
        )
    return value


def output_dir() -> Path:
    path = Path(get("OUTPUT_DIR", "./output"))
    if not path.is_absolute():
        path = _PROJECT_ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_level() -> str:
    return get("LOG_LEVEL", "INFO")


def tui_status_flash_seconds() -> float:
    """How long transient TUI status lines stay visible before restoring baseline.

    Override with env ``TUI_STATUS_FLASH_SECONDS`` (seconds, default ``5``).
    """
    _ensure_loaded()
    raw = get("TUI_STATUS_FLASH_SECONDS", "5")
    try:
        value = float(raw or "5")
    except (TypeError, ValueError):
        return 5.0
    return max(0.0, value)
