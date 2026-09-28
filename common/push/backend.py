"""Provider port for push: the primitives each streaming service implements.

Matching, planning, ordering and execution are provider-agnostic and live in
:mod:`common.push`; a backend only translates these calls to its API. Search
methods take a ``narrow`` flag: narrow uses the most specific query the API
supports, broad is the fallback when narrow finds nothing.
"""

from __future__ import annotations

import time
from typing import Callable, Protocol, TypeVar

from common.log import get_logger
from common.push.models import CatalogAlbum, CatalogArtist, CatalogTrack, RemoteSnapshot

log = get_logger(__name__)

T = TypeVar("T")


class PushBackend(Protocol):
    provider_id: str

    # ── Read ──────────────────────────────────────────────────────
    def snapshot(self) -> RemoteSnapshot: ...
    def lookup_tracks(self, ids: list[str]) -> dict[str, CatalogTrack]: ...
    def lookup_albums(self, ids: list[str]) -> dict[str, CatalogAlbum]: ...
    def lookup_artists(self, ids: list[str]) -> dict[str, CatalogArtist]: ...
    def tracks_by_isrc(self, isrc: str) -> list[CatalogTrack]: ...
    def albums_by_upc(self, upc: str) -> list[CatalogAlbum]: ...
    def search_tracks(
        self, title: str, artist: str, album: str | None, *, narrow: bool
    ) -> list[CatalogTrack]: ...
    def search_albums(self, title: str, artist: str, *, narrow: bool) -> list[CatalogAlbum]: ...
    def search_artists(self, name: str) -> list[CatalogArtist]: ...
    def artist_albums(self, artist_id: str) -> list[str]:
        """A few releases as ``"Title (2023)"``, newest first; empty if none are visible.

        Only called for artists the user has to choose between, so namesakes can
        be told apart by what they released.
        """
        ...

    def playlist_version(self, playlist_id: str) -> str | None:
        """Opaque revision marker; must equal ``Playlist.snapshot_id`` from :meth:`snapshot`."""
        ...

    # ── Write ─────────────────────────────────────────────────────
    def find_editable_playlists(self, name: str) -> list[str]: ...
    def create_playlist(self, name: str, description: str) -> str: ...
    def replace_playlist_tracks(self, playlist_id: str, track_ids: list[str]) -> None: ...
    def delete_playlist(self, playlist_id: str, *, owned: bool) -> None: ...
    def add_liked(self, ids: list[str]) -> None: ...
    def remove_liked(self, ids: list[str]) -> None: ...
    def save_albums(self, ids: list[str]) -> None: ...
    def unsave_albums(self, ids: list[str]) -> None: ...
    def follow_artists(self, ids: list[str]) -> None: ...
    def unfollow_artists(self, ids: list[str]) -> None: ...


def chunks(items: list[T], size: int) -> list[list[T]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def call_with_retry(
    fn: Callable[[], T],
    *,
    retry_after: Callable[[Exception], float | None],
    attempts: int = 5,
) -> T:
    """Run ``fn``; on a rate-limit error (``retry_after`` returns seconds) wait and retry."""
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:
            wait = retry_after(exc)
            if wait is None or attempt == attempts:
                raise
            wait = max(1.0, min(wait, 60.0))
            log.warning("Rate limited; retrying in %.0fs (attempt %d/%d)", wait, attempt, attempts)
            time.sleep(wait)
    raise AssertionError("unreachable")
