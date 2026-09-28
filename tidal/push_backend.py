"""TIDAL implementation of :class:`common.push.backend.PushBackend` (tidalapi)."""

from __future__ import annotations

from typing import Any, Callable, TypeVar

from tidalapi.exceptions import InvalidISRC, InvalidUPC, ObjectNotFound, TooManyRequests
from tidalapi.media import Track as TidalTrack
from tidalapi.playlist import UserPlaylist

from common.log import get_logger
from common.models import Library
from common.push.backend import call_with_retry, chunks
from common.push.models import CatalogAlbum, CatalogArtist, CatalogTrack, RemoteSnapshot
from tidal.client import get_session
from tidal.export import (
    SERVICE,
    _followed_artist_row,
    _liked_track_to_row,
    _saved_album_row,
    _tidal_playlist_to_common,
)

log = get_logger(__name__)

T = TypeVar("T")

_SEARCH_LIMIT = 10
_PLAYLIST_BATCH = 100
_FAVORITES_BATCH = 50
_ARTIST_ALBUMS = 4


def _retry_after(exc: Exception) -> float | None:
    if isinstance(exc, TooManyRequests):
        return float(exc.retry_after) if exc.retry_after and exc.retry_after > 0 else 5.0
    return None


def _track(t: Any) -> CatalogTrack:
    arts = list(t.artists or [])
    return CatalogTrack(
        id=str(t.id),
        title=t.name or getattr(t, "full_name", "") or "",
        artists=[a.name or "" for a in arts],
        artist_ids=[str(a.id) for a in arts],
        album=t.album.name if getattr(t, "album", None) else None,
        duration_ms=int(t.duration * 1000) if getattr(t, "duration", None) else None,
        isrc=getattr(t, "isrc", None),
    )


def _artist(a: Any) -> CatalogArtist:
    return CatalogArtist(
        id=str(a.id),
        name=a.name or "",
        url=getattr(a, "share_url", None) or getattr(a, "listen_url", None),
    )


def _album(a: Any) -> CatalogAlbum:
    arts = list(a.artists or []) or ([a.artist] if getattr(a, "artist", None) else [])
    year = a.release_date.date().isoformat() if getattr(a, "release_date", None) else None
    return CatalogAlbum(
        id=str(a.id),
        title=a.name or "",
        artists=[x.name or "" for x in arts],
        artist_ids=[str(x.id) for x in arts],
        year=year,
        total_tracks=getattr(a, "num_tracks", None),
    )


class TidalPushBackend:
    provider_id = SERVICE

    def __init__(self, session: Any = None) -> None:
        self._session = session

    @property
    def session(self):
        if self._session is None:
            self._session = get_session()
        return self._session

    @property
    def fav(self):
        return self.session.user.favorites

    def _call(self, fn: Callable[[], T]) -> T:
        return call_with_retry(fn, retry_after=_retry_after)

    # ── Read ──────────────────────────────────────────────────────

    def _raw_playlists(self) -> list[Any]:
        out: list[Any] = []
        offset = 0
        while True:
            batch = self._call(
                lambda: self.session.user.playlist_and_favorite_playlists(offset=offset, limit=50)
            )
            if not batch:
                break
            out.extend(batch)
            offset += len(batch)
            if len(batch) < 50:
                break
        return out

    def _editable(self, pl: Any) -> bool:
        return isinstance(pl, UserPlaylist)

    def snapshot(self) -> RemoteSnapshot:
        """Current library. Contents are read only for playlists we could write to.

        Playlists you merely follow can never be a push target, so reading their
        tracks would only cost time.
        """
        s = self.session
        playlists = []
        editable: set[str] = set()
        followed = 0
        for pl in self._raw_playlists():
            mine = self._editable(pl)
            try:
                common = self._call(
                    lambda: _tidal_playlist_to_common(s, pl, with_tracks=mine)
                )
            except (ObjectNotFound, TooManyRequests) as exc:
                log.warning("Skipping playlist %s: %s", getattr(pl, "name", "?"), exc)
                continue
            if mine and common.service_id:
                editable.add(common.service_id)
                if not common.snapshot_id:
                    common.snapshot_id = self.playlist_version(common.service_id)
            else:
                followed += 1
            playlists.append(common)
        if followed:
            log.info(
                "%d playlists you only follow — kept in the plan, contents not read "
                "(they can't be push targets)",
                followed,
            )
        library = Library(
            last_pull_provider=SERVICE,
            playlists=playlists,
            liked_songs=[_liked_track_to_row(s, t) for t in self._call(self.fav.tracks_paginated)],
            saved_albums=[_saved_album_row(s, a) for a in self._call(self.fav.albums_paginated)],
            followed_artists=[_followed_artist_row(s, a) for a in self._call(self.fav.artists_paginated)],
        )
        return RemoteSnapshot(library=library, editable_playlist_ids=editable)

    def _lookup(self, ids: list[str], fetch: Callable[[str], Any], parse: Callable[[Any], T]) -> dict[str, T]:
        out: dict[str, T] = {}
        for i in ids:
            try:
                obj = self._call(lambda: fetch(i))
            except ObjectNotFound:
                continue
            if obj is not None:
                out[i] = parse(obj)
        return out

    def lookup_tracks(self, ids: list[str]) -> dict[str, CatalogTrack]:
        return self._lookup(ids, self.session.track, _track)

    def lookup_albums(self, ids: list[str]) -> dict[str, CatalogAlbum]:
        return self._lookup(ids, self.session.album, _album)

    def lookup_artists(self, ids: list[str]) -> dict[str, CatalogArtist]:
        return self._lookup(ids, self.session.artist, lambda a: CatalogArtist(id=str(a.id), name=a.name or ""))

    def tracks_by_isrc(self, isrc: str) -> list[CatalogTrack]:
        from common.push.isrc import valid_isrc

        if not valid_isrc(isrc):
            return []
        try:
            return [_track(t) for t in self._call(lambda: self.session.get_tracks_by_isrc(isrc))]
        except (InvalidISRC, ObjectNotFound):
            return []

    def albums_by_upc(self, upc: str) -> list[CatalogAlbum]:
        try:
            return [_album(a) for a in self._call(lambda: self.session.get_albums_by_barcode(upc))]
        except (InvalidUPC, ObjectNotFound):
            return []

    def _search(self, query: str, model: Any, key: str) -> list[Any]:
        res = self._call(lambda: self.session.search(query, models=[model], limit=_SEARCH_LIMIT))
        return [x for x in (res or {}).get(key) or [] if x is not None and getattr(x, "id", None)]

    def search_tracks(self, title: str, artist: str, album: str | None, *, narrow: bool) -> list[CatalogTrack]:
        query = f"{artist} {title}".strip() if narrow else title
        return [_track(t) for t in self._search(query, TidalTrack, "tracks")]

    def search_albums(self, title: str, artist: str, *, narrow: bool) -> list[CatalogAlbum]:
        from tidalapi.album import Album

        query = f"{artist} {title}".strip() if narrow else title
        return [_album(a) for a in self._search(query, Album, "albums")]

    def search_artists(self, name: str) -> list[CatalogArtist]:
        from tidalapi.artist import Artist

        return [_artist(a) for a in self._search(name, Artist, "artists")]

    def artist_albums(self, artist_id: str) -> list[str]:
        try:
            albums = self._call(lambda: self.session.artist(artist_id).get_albums(limit=_ARTIST_ALBUMS))
        except (ObjectNotFound, AttributeError):
            return []
        seen: set[str] = set()
        out = []
        for a in albums or []:
            title = getattr(a, "name", "") or ""
            if not title or title.casefold() in seen:
                continue
            seen.add(title.casefold())
            year = getattr(a, "year", None) or (
                a.release_date.year if getattr(a, "release_date", None) else None
            )
            out.append(f"{title} ({year})" if year else title)
        return out

    def playlist_version(self, playlist_id: str) -> str | None:
        res = self._call(lambda: self.session.request.request("GET", f"playlists/{playlist_id}"))
        return res.headers.get("etag")

    # ── Write ─────────────────────────────────────────────────────

    def find_editable_playlists(self, name: str) -> list[str]:
        wanted = name.strip().casefold()
        return [
            str(p.id)
            for p in self._raw_playlists()
            if (p.name or "").strip().casefold() == wanted and self._editable(p)
        ]

    def create_playlist(self, name: str, description: str) -> str:
        pl = self._call(lambda: self.session.user.create_playlist(name, description or ""))
        return str(pl.id)

    def replace_playlist_tracks(self, playlist_id: str, track_ids: list[str]) -> None:
        pl = self._call(lambda: UserPlaylist(self.session, playlist_id))
        self._call(pl.clear)
        for batch in chunks(track_ids, _PLAYLIST_BATCH):
            self._call(lambda b=batch: pl.add(b, allow_duplicates=True, limit=len(b)))

    def delete_playlist(self, playlist_id: str, *, owned: bool) -> None:
        if owned:
            pl = self._call(lambda: UserPlaylist(self.session, playlist_id))
            self._call(pl.delete)
        else:
            self._call(lambda: self.fav.remove_playlist(playlist_id))

    def _each(self, fn: Callable[[str], Any], ids: list[str]) -> None:
        """Removals are one id per request in tidalapi."""
        for i in ids:
            self._call(lambda i=i: fn(i))

    def add_liked(self, ids: list[str]) -> None:
        for batch in chunks(ids, _FAVORITES_BATCH):
            self._call(lambda b=batch: self.fav.add_track(b))

    def remove_liked(self, ids: list[str]) -> None:
        self._each(self.fav.remove_track, ids)

    def save_albums(self, ids: list[str]) -> None:
        for batch in chunks(ids, _FAVORITES_BATCH):
            self._call(lambda b=batch: self.fav.add_album(b))

    def unsave_albums(self, ids: list[str]) -> None:
        self._each(self.fav.remove_album, ids)

    def follow_artists(self, ids: list[str]) -> None:
        for batch in chunks(ids, _FAVORITES_BATCH):
            self._call(lambda b=batch: self.fav.add_artist(b))

    def unfollow_artists(self, ids: list[str]) -> None:
        self._each(self.fav.remove_artist, ids)
