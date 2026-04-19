"""Authenticated TIDAL session via tidalapi (OAuth token file)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import tidalapi
from tidalapi.session import Session

from common import config
from common.log import get_logger
from common.store import meta_dir

log = get_logger(__name__)

_client: Session | None = None


class TidalAuthError(Exception):
    """Raised when no valid TIDAL session is available."""


def session_file_path() -> Path:
    """Path to JSON written by tidalapi (tokens). Override with ``TIDAL_SESSION_FILE``."""
    raw = config.get("TIDAL_SESSION_FILE", "")
    if raw and raw.strip():
        p = Path(raw.strip()).expanduser()
        return p if p.is_absolute() else config.project_root() / p
    return meta_dir() / "tidal_session.json"


def get_session() -> Session:
    """Return a lazily initialised, logged-in TIDAL session."""
    global _client
    if _client is not None and _client.check_login():
        return _client

    path = session_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    session = Session(tidalapi.Config())
    if path.exists():
        session.load_session_from_file(path)
        if session.check_login():
            log.info("TIDAL session loaded from %s", path)
            _client = session
            return _client

    raise TidalAuthError(
        "No valid TIDAL session. Create one first, e.g. run in a terminal from the "
        "project venv:\n\n"
        f"  .venv/bin/python -c \"from pathlib import Path; import tidalapi; "
        f"s=tidalapi.Session(tidalapi.Config()); "
        f"s.login_session_file(Path('{path}'))\"\n\n"
        "Then open the link, complete device login, and retry Pull. "
        f"Session file: {path}"
    )


def reset_session_cache() -> None:
    """Clear cached session (e.g. after token refresh on disk)."""
    global _client
    _client = None


def _rich_escape(s: str) -> str:
    return s.replace("[", "\\[")


def tidal_login_status() -> tuple[bool, str]:
    """Probe session file without mutating the cached :func:`get_session` client.

    Returns ``(logged_in, rich_markup)`` for the service login details pane.
    May perform a short network call to validate tokens (same as a pull).
    """
    path = session_file_path()
    if not path.exists():
        return False, "[dim]No session file on disk — not signed in yet.[/]"

    session = Session(tidalapi.Config())
    try:
        if not session.load_session_from_file(path):
            return False, "[yellow]Session file exists but could not be loaded.[/]"
        if not session.check_login():
            return False, "[yellow]Session file exists but login is no longer valid.[/]"

        label = "TIDAL"
        u = session.user
        if u is not None:
            for attr in ("full_name", "first_name", "name", "username"):
                raw = getattr(u, attr, None)
                if raw:
                    label = str(raw)
                    break
            else:
                uid = getattr(u, "id", None)
                if uid is not None:
                    label = f"id {uid}"
        safe = _rich_escape(label)
        return True, f"[green]Signed in as [bold]{safe}[/].[/] [dim]Session: {path}[/]"
    except Exception as exc:
        return False, f"[yellow]Could not verify session: {exc}[/]"


def run_interactive_login(fn_print: Callable[[str], None]) -> bool:
    """Replace the session file with a fresh device login. ``fn_print`` mirrors tidalapi output."""
    path = session_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    reset_session_cache()
    session = Session(tidalapi.Config())
    ok = session.login_session_file(path, do_pkce=False, fn_print=fn_print)
    reset_session_cache()
    return bool(ok)
