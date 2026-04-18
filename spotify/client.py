"""Thin wrapper around spotipy providing a shared, authenticated client."""

from __future__ import annotations

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from common import config
from common.log import get_logger

log = get_logger(__name__)

_client: spotipy.Spotify | None = None

SCOPE = (
    "user-library-read "
    "playlist-read-private "
    "playlist-read-collaborative"
)


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
        user = _client.current_user()
        log.info("Authenticated as %s", user["display_name"])
    return _client
