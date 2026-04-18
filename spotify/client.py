"""Thin wrapper around spotipy providing a shared, authenticated client."""

from __future__ import annotations

import spotipy
from spotipy.exceptions import SpotifyException
from spotipy.oauth2 import SpotifyOAuth

from common import config
from common.log import get_logger

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


def get_client() -> spotipy.Spotify:
    """Return a lazily-initialised, authenticated Spotify client."""
    global _client
    if _client is None:
        auth_manager = SpotifyOAuth(
            client_id=config.require("SPOTIFY_CLIENT_ID"),
            client_secret=config.require("SPOTIFY_CLIENT_SECRET"),
            redirect_uri=config.require("SPOTIFY_REDIRECT_URI"),
            scope=SCOPE,
        )
        _client = spotipy.Spotify(auth_manager=auth_manager)
        try:
            user = _client.current_user()
        except SpotifyException as exc:
            _client = None
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
    return _client
