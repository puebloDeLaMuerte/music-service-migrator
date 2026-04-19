"""Thin wrapper around spotipy providing a shared, authenticated client."""

from __future__ import annotations

import webbrowser
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse

import spotipy
from spotipy.cache_handler import CacheFileHandler
from spotipy.exceptions import SpotifyException
from spotipy.oauth2 import SpotifyOAuth

from common import config
from common.log import get_logger
from common.store import meta_dir

log = get_logger(__name__)

_client: spotipy.Spotify | None = None

SCOPE = " ".join([
    "user-read-private",
    "user-library-read",
    "user-follow-read",
    "playlist-read-private",
    "playlist-read-collaborative",
])


class SpotifyAuthError(Exception):
    """Raised when authentication succeeds but the API rejects requests."""


def token_cache_path() -> Path:
    """OAuth token file used by spotipy (under ``<work_dir>/meta``)."""
    return meta_dir() / "spotify_token.json"


def reset_client_cache() -> None:
    """Drop the in-memory client (e.g. after replacing the token file on disk)."""
    global _client
    _client = None


def _is_usable_http_url(url: str) -> bool:
    """True if *url* is safe to pass to the OS browser (avoids empty tabs)."""
    try:
        p = urlparse(url.strip())
    except Exception:
        return False
    return p.scheme in ("http", "https") and bool(p.netloc)


@contextmanager
def _guard_webbrowser_open() -> object:
    """Reject invalid URLs spotipy might pass to ``webbrowser.open`` during OAuth."""
    orig = webbrowser.open

    def guarded(url: object, *args: object, **kwargs: object) -> bool:
        s = str(url) if url is not None else ""
        if not _is_usable_http_url(s):
            log.debug("Skipping webbrowser.open for invalid URL: %r", url)
            return False
        return bool(orig(s, *args, **kwargs))

    webbrowser.open = guarded  # type: ignore[method-assign]
    try:
        yield
    finally:
        webbrowser.open = orig  # type: ignore[method-assign]


def _authenticate() -> tuple[spotipy.Spotify, dict]:
    """Build a Spotify client and validate with ``current_user()``."""
    auth_manager = SpotifyOAuth(
        client_id=config.require("SPOTIFY_CLIENT_ID"),
        client_secret=config.require("SPOTIFY_CLIENT_SECRET"),
        redirect_uri=config.require("SPOTIFY_REDIRECT_URI"),
        scope=SCOPE,
        cache_handler=CacheFileHandler(cache_path=str(token_cache_path())),
    )
    sp = spotipy.Spotify(auth_manager=auth_manager)
    try:
        user = sp.current_user()
    except SpotifyException as exc:
        if exc.http_status == 403 and "premium" in str(exc).lower():
            raise SpotifyAuthError(
                "Spotify requires the developer app owner to have an active "
                "Premium subscription. Check your subscription status and try "
                "again in a few hours if you just subscribed."
            ) from exc
        raise SpotifyAuthError(
            f"Spotify API rejected the request (HTTP {exc.http_status}): {exc}"
        ) from exc
    log.info("Authenticated as %s", user["display_name"])
    return sp, user


def get_client() -> spotipy.Spotify:
    """Return a lazily-initialised, authenticated Spotify client."""
    global _client
    if _client is None:
        sp, _ = _authenticate()
        _client = sp
    return _client


def login_interactive() -> str:
    """Run a full OAuth flow (clears cached token first). Returns ``display_name``."""
    global _client
    _client = None
    path = token_cache_path()
    if path.exists():
        path.unlink()
    with _guard_webbrowser_open():
        sp, user = _authenticate()
    _client = sp
    return user["display_name"]


def _rich_escape(s: str) -> str:
    return s.replace("[", "\\[")


def spotify_login_status() -> tuple[bool, str]:
    """Probe cached credentials without opening a browser.

    Returns ``(logged_in, rich_markup)`` for the service login details pane.
    """
    try:
        config.require("SPOTIFY_CLIENT_ID")
        config.require("SPOTIFY_CLIENT_SECRET")
        config.require("SPOTIFY_REDIRECT_URI")
    except RuntimeError:
        return False, (
            "[yellow]SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET / SPOTIFY_REDIRECT_URI "
            "are not set in .env — add them before signing in.[/]"
        )

    path = token_cache_path()
    if not path.exists():
        return False, "[dim]No token cache on disk — not signed in yet.[/]"

    try:
        auth_manager = SpotifyOAuth(
            client_id=config.require("SPOTIFY_CLIENT_ID"),
            client_secret=config.require("SPOTIFY_CLIENT_SECRET"),
            redirect_uri=config.require("SPOTIFY_REDIRECT_URI"),
            scope=SCOPE,
            cache_handler=CacheFileHandler(cache_path=str(path)),
        )
        token_info = auth_manager.cache_handler.get_cached_token()
        if not token_info:
            return False, "[yellow]Token file exists but contains no usable token.[/]"
        validated = auth_manager.validate_token(token_info)
        if validated is None:
            return False, "[yellow]Cached token is invalid or scopes changed — sign in again.[/]"
        sp = spotipy.Spotify(auth_manager=auth_manager)
        user = sp.current_user()
        name = user.get("display_name") or user.get("id") or "?"
        safe = _rich_escape(str(name))
        return True, f"[green]Signed in as [bold]{safe}[/].[/] [dim]Token: {path}[/]"
    except SpotifyAuthError as exc:
        return False, (
            f"[yellow]Token on disk, but Spotify rejected the account: {exc}[/]"
        )
    except SpotifyException as exc:
        return False, f"[yellow]Could not verify session: {exc}[/]"
    except Exception as exc:
        return False, f"[yellow]Could not verify session: {exc}[/]"
