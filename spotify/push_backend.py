"""Spotify implementation of :class:`common.push.backend.PushBackend`.

Uses the 2026 Web API surface where available (``/me/library``,
``/me/playlists``, ``/playlists/{id}/items``) and falls back to the older
endpoints where spotipy or the account still needs them. Catalog lookups go
one id at a time because batch lookups are restricted for development-mode apps.
"""

from __future__ import annotations

from typing import Any, Callable, TypeVar

from spotipy.exceptions import SpotifyException

from common.log import get_logger
from common.models import Library, Playlist, record_meta_for_pull
from common.push.backend import call_with_retry, chunks
from common.push.errors import PushError, PushErrorCode
from common.push.models import CatalogAlbum, CatalogArtist, CatalogTrack, RemoteSnapshot
from spotify.client import get_client
from spotify.export import (
    SERVICE,
    _paginate,
    _parse_images,
    fetch_followed_artists,
    fetch_liked_songs,
    fetch_playlist_tracks,
    fetch_saved_albums,
)

log = get_logger(__name__)

T = TypeVar("T")

_SEARCH_LIMIT = 10
_LIBRARY_BATCH = 40
_PLAYLIST_BATCH = 100
_ARTIST_ALBUMS = 4


def _retry_after(exc: Exception) -> float | None:
    if isinstance(exc, SpotifyException) and exc.http_status == 429:
        headers = getattr(exc, "headers", None) or {}
        try:
            return float(headers.get("Retry-After", 5))
        except (TypeError, ValueError):
            return 5.0
    return None


def _q(s: str) -> str:
    return (s or "").replace('"', " ").strip()


def _track(d: dict) -> CatalogTrack:
    return CatalogTrack(
        id=d["id"],
        title=d.get("name") or "",
        artists=[a.get("name") or "" for a in d.get("artists") or []],
        artist_ids=[a.get("id") or "" for a in d.get("artists") or []],
        album=(d.get("album") or {}).get("name"),
        duration_ms=d.get("duration_ms"),
        isrc=(d.get("external_ids") or {}).get("isrc"),
    )


def _artist(d: dict) -> CatalogArtist:
    return CatalogArtist(
        id=d["id"],
        name=d.get("name") or "",
        url=(d.get("external_urls") or {}).get("spotify"),
    )


def _album(d: dict) -> CatalogAlbum:
    return CatalogAlbum(
        id=d["id"],
        title=d.get("name") or "",
        artists=[a.get("name") or "" for a in d.get("artists") or []],
        artist_ids=[a.get("id") or "" for a in d.get("artists") or []],
        year=d.get("release_date"),
        total_tracks=d.get("total_tracks"),
    )


class SpotifyPushBackend:
    provider_id = SERVICE

    def __init__(self, client: Any = None) -> None:
        self._sp = client
        self._me: dict | None = None

    @property
    def sp(self):
        if self._sp is None:
            self._sp = get_client()
        return self._sp

    @property
    def me_id(self) -> str:
        if self._me is None:
            self._me = self.sp.current_user()
        return self._me["id"]

    def _call(self, fn: Callable[[], T]) -> T:
        return call_with_retry(fn, retry_after=_retry_after)

    def _write(self, what: str, fn: Callable[[], T]) -> T:
        try:
            return self._call(fn)
        except SpotifyException as exc:
            if exc.http_status in (401, 403):
                raise PushError(
                    PushErrorCode.AUTH,
                    f"Spotify refused to {what} (HTTP {exc.http_status}). Sign in again under "
                    "Account → Login so the app gets write access.",
                ) from exc
            raise

    # ── Read ──────────────────────────────────────────────────────

    def _raw_playlists(self) -> list[dict]:
        return self._call(lambda: _paginate(self.sp.current_user_playlists(limit=50), self.sp))

    def _editable(self, item: dict) -> bool:
        return (item.get("owner") or {}).get("id") == self.me_id or bool(item.get("collaborative"))

    def snapshot(self) -> RemoteSnapshot:
        """Current library. Contents are read only for playlists we could write to.

        Playlists you merely follow can never be a push target, so fetching
        their tracks would only cost time — and Spotify refuses it outright for
        some of them (HTTP 403 on the item list, even though their metadata
        reads fine).
        """
        playlists: list[Playlist] = []
        editable: set[str] = set()
        followed = 0
        for item in self._raw_playlists():
            mine = self._editable(item)
            if not mine:
                followed += 1
            tracks = []
            if mine:
                try:
                    tracks = self._call(lambda: fetch_playlist_tracks(item["id"]))
                except SpotifyException as exc:
                    log.warning(
                        "Spotify would not list the tracks of your playlist '%s' (HTTP %s) — "
                        "planning without it",
                        item.get("name"), exc.http_status,
                    )
                    continue
                editable.add(item["id"])
            playlists.append(
                Playlist(
                    name=item.get("name") or "",
                    record_meta=record_meta_for_pull(SERVICE),
                    description=item.get("description"),
                    owner=(item.get("owner") or {}).get("display_name"),
                    collaborative=item.get("collaborative"),
                    public=item.get("public"),
                    snapshot_id=item.get("snapshot_id"),
                    images=_parse_images(item.get("images")),
                    tracks=tracks,
                    service_id=item["id"],
                    service=SERVICE,
                )
            )
        if followed:
            log.info(
                "%d playlists you only follow — kept in the plan, contents not read "
                "(they can't be push targets)",
                followed,
            )
        library = Library(
            last_pull_provider=SERVICE,
            playlists=playlists,
            liked_songs=self._call(fetch_liked_songs),
            saved_albums=self._call(fetch_saved_albums),
            followed_artists=self._call(fetch_followed_artists),
        )
        return RemoteSnapshot(library=library, editable_playlist_ids=editable)

    def _lookup(self, ids: list[str], fetch: Callable[[str], dict], parse: Callable[[dict], T]) -> dict[str, T]:
        out: dict[str, T] = {}
        for i in ids:
            try:
                d = self._call(lambda: fetch(i))
            except SpotifyException as exc:
                if exc.http_status in (400, 404):
                    continue
                raise
            if d and d.get("id"):
                out[i] = parse(d)
        return out

    def lookup_tracks(self, ids: list[str]) -> dict[str, CatalogTrack]:
        return self._lookup(ids, lambda i: self.sp.track(i), _track)

    def lookup_albums(self, ids: list[str]) -> dict[str, CatalogAlbum]:
        return self._lookup(ids, lambda i: self.sp.album(i), _album)

    def lookup_artists(self, ids: list[str]) -> dict[str, CatalogArtist]:
        return self._lookup(ids, lambda i: self.sp.artist(i), _artist)

    def _search(self, q: str, kind: str) -> list[dict]:
        res = self._call(lambda: self.sp.search(q=q, type=kind, limit=_SEARCH_LIMIT))
        return [x for x in ((res or {}).get(f"{kind}s") or {}).get("items") or [] if x and x.get("id")]

    def tracks_by_isrc(self, isrc: str) -> list[CatalogTrack]:
        from common.push.isrc import valid_isrc

        if not valid_isrc(isrc):
            return []
        return [_track(d) for d in self._search(f"isrc:{_q(isrc)}", "track")]

    def albums_by_upc(self, upc: str) -> list[CatalogAlbum]:
        return [_album(d) for d in self._search(f"upc:{_q(upc)}", "album")]

    def search_tracks(self, title: str, artist: str, album: str | None, *, narrow: bool) -> list[CatalogTrack]:
        if narrow:
            q = f'track:"{_q(title)}"' + (f' artist:"{_q(artist)}"' if artist else "")
        else:
            q = f"{_q(title)} {_q(artist)}".strip()
        return [_track(d) for d in self._search(q, "track")]

    def search_albums(self, title: str, artist: str, *, narrow: bool) -> list[CatalogAlbum]:
        if narrow:
            q = f'album:"{_q(title)}"' + (f' artist:"{_q(artist)}"' if artist else "")
        else:
            q = f"{_q(title)} {_q(artist)}".strip()
        return [_album(d) for d in self._search(q, "album")]

    def search_artists(self, name: str) -> list[CatalogArtist]:
        return [_artist(d) for d in self._search(f'artist:"{_q(name)}"', "artist")]

    def artist_albums(self, artist_id: str) -> list[str]:
        try:
            res = self._call(
                lambda: self.sp.artist_albums(
                    artist_id, album_type="album,single", limit=_ARTIST_ALBUMS
                )
            )
        except SpotifyException:
            return []
        seen: set[str] = set()
        out = []
        for d in (res or {}).get("items") or []:
            title = d.get("name") or ""
            if not title or title.casefold() in seen:
                continue
            seen.add(title.casefold())
            year = (d.get("release_date") or "")[:4]
            out.append(f"{title} ({year})" if year else title)
        return out

    def playlist_version(self, playlist_id: str) -> str | None:
        d = self._call(lambda: self.sp.playlist(playlist_id, fields="snapshot_id"))
        return (d or {}).get("snapshot_id")

    # ── Write ─────────────────────────────────────────────────────

    def find_editable_playlists(self, name: str) -> list[str]:
        wanted = name.strip().casefold()
        return [
            p["id"]
            for p in self._raw_playlists()
            if (p.get("name") or "").strip().casefold() == wanted and self._editable(p)
        ]

    def create_playlist(self, name: str, description: str) -> str:
        payload = {"name": name, "public": False, "description": description or ""}
        try:
            res = self._write("create a playlist", lambda: self.sp._post("me/playlists", payload=payload))
        except SpotifyException as exc:
            if exc.http_status not in (404, 405):
                raise
            res = self._write(
                "create a playlist",
                lambda: self.sp.user_playlist_create(self.me_id, name, public=False, description=description or ""),
            )
        return res["id"]

    def replace_playlist_tracks(self, playlist_id: str, track_ids: list[str]) -> None:
        batches = chunks(track_ids, _PLAYLIST_BATCH) or [[]]
        self._write("change a playlist", lambda: self.sp.playlist_replace_items(playlist_id, batches[0]))
        for batch in batches[1:]:
            self._write("change a playlist", lambda b=batch: self.sp.playlist_add_items(playlist_id, b))

    def delete_playlist(self, playlist_id: str, *, owned: bool) -> None:
        uri = f"spotify:playlist:{playlist_id}"
        try:
            self._write("remove a playlist", lambda: self.sp._delete("me/library", uris=uri))
        except SpotifyException as exc:
            if exc.http_status not in (400, 404, 405):
                raise
            self._write("remove a playlist", lambda: self.sp.current_user_unfollow_playlist(playlist_id))

    def _batched(self, what: str, fn: Callable[[list[str]], Any], ids: list[str]) -> None:
        for batch in chunks(ids, _LIBRARY_BATCH):
            self._write(what, lambda b=batch: fn(b))

    def add_liked(self, ids: list[str]) -> None:
        self._batched("like songs", self.sp.current_user_saved_tracks_add, ids)

    def remove_liked(self, ids: list[str]) -> None:
        self._batched("unlike songs", self.sp.current_user_saved_tracks_delete, ids)

    def save_albums(self, ids: list[str]) -> None:
        self._batched("save albums", self.sp.current_user_saved_albums_add, ids)

    def unsave_albums(self, ids: list[str]) -> None:
        self._batched("remove saved albums", self.sp.current_user_saved_albums_delete, ids)

    def follow_artists(self, ids: list[str]) -> None:
        self._batched("follow artists", self.sp.user_follow_artists, ids)

    def unfollow_artists(self, ids: list[str]) -> None:
        self._batched("unfollow artists", self.sp.user_unfollow_artists, ids)
