"""Unified configuration loader.

Reads the .env file at the project root once and exposes helpers that each
service adapter can call to pull only the keys it needs.

Workspace data lives under :func:`work_dir` (env ``WORK_DIR``, default ``./work``).
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv, set_key

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_loaded = False


def _ensure_loaded() -> None:
    global _loaded
    if not _loaded:
        load_dotenv(_PROJECT_ROOT / ".env")
        _loaded = True


def env_file_path() -> Path:
    """Path to the project root ``.env`` file (created on first write)."""
    return _PROJECT_ROOT / ".env"


def write_env_key(key: str, value: str) -> None:
    """Persist ``key=value`` to ``.env`` and reload the process environment."""
    _ensure_loaded()
    path = env_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    set_key(str(path), key, value)
    global _loaded
    _loaded = False
    load_dotenv(path, override=True)


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


def work_dir() -> Path:
    """Root directory for all on-disk workspace data (playlists, meta, …).

    Layout under this path (see module docstring in ``common.store``):

    - ``playlists/*.json`` — one file per playlist
    - ``liked_songs.json``, ``saved_albums.json``, ``followed_artists.json``
    - ``workspace_meta.json`` — schema version, counts, ``last_pull_provider``
    - ``meta/`` — dedupe ignore list, P2A log, image cache, …

    Set env ``WORK_DIR`` (default ``./work``). Relative paths are under the
    project root.
    """
    path = Path(get("WORK_DIR", "./work"))
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


def p2a_always_keep_leftovers() -> bool:
    """Playlist→Album Extract+delete: skip the loose-tracks modal and always keep the playlist file.

    When album tracks are removed but other tracks remain, the TUI normally asks
    whether to keep a trimmed playlist file or delete it. If this is true, the
    file is always kept (same as choosing “Keep file” in that dialog).

    Set env ``P2A_ALWAYS_KEEP_LEFTOVERS`` to ``1``, ``true``, ``yes``, or ``on``.
    """
    _ensure_loaded()
    raw = (get("P2A_ALWAYS_KEEP_LEFTOVERS", "") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")
