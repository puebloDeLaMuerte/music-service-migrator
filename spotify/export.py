"""Pull the user's complete Spotify library into common models."""

from __future__ import annotations

from datetime import datetime, timezone

from common.log import get_logger
from common.models import (
    Album,
    Artist,
    FollowedArtist,
    Library,
    Playlist,
    PlaylistTrack,
    SavedAlbum,
    Track,
)
from spotify.client import get_client

log = get_logger(__name__)

SERVICE = "spotify"


# ── Parsing helpers ──────────────────────────────────────────────────────────

def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_artist(data: dict) -> Artist:
    return Artist(
        name=data["name"],
        genres=data.get("genres", []),
        service_id=data.get("id"),
        service_url=(data.get("external_urls") or {}).get("spotify"),
        service=SERVICE,
    )


def _parse_album(data: dict) -> Album:
    return Album(
        name=data.get("name", ""),
        artists=[_parse_artist(a) for a in data.get("artists", [])],
        release_date=data.get("release_date"),
        total_tracks=data.get("total_tracks"),
        service_id=data.get("id"),
        service_url=(data.get("external_urls") or {}).get("spotify"),
        service=SERVICE,
    )


def _parse_track_item(item: dict) -> PlaylistTrack | None:
    """Convert a Spotify playlist-track / saved-track item."""
    t = item.get("track")
    if t is None:
        return None

    album_data = t.get("album") or {}

    return PlaylistTrack(
        track=Track(
            name=t["name"],
            artists=[_parse_artist(a) for a in t.get("artists", [])],
            album=_parse_album(album_data) if album_data else None,
            duration_ms=t.get("duration_ms"),
            isrc=t.get("external_ids", {}).get("isrc"),
            service_id=t["id"],
            service_url=t.get("external_urls", {}).get("spotify"),
            service=SERVICE,
        ),
        added_at=_parse_dt(item.get("added_at")),
        added_by=(item.get("added_by") or {}).get("id"),
    )


# ── Paginated fetchers ──────────────────────────────────────────────────────

def _paginate(first_page, sp) -> list[dict]:
    """Collect all items across paginated Spotify responses."""
    items: list[dict] = []
    page = first_page
    while True:
        items.extend(page["items"])
        if page["next"]:
            page = sp.next(page)
        else:
            break
    return items


def fetch_playlist_tracks(playlist_id: str) -> list[PlaylistTrack]:
    sp = get_client()
    items = _paginate(sp.playlist_items(playlist_id, limit=100), sp)
    tracks: list[PlaylistTrack] = []
    for pos, item in enumerate(items):
        pt = _parse_track_item(item)
        if pt is not None:
            pt.position = pos
            tracks.append(pt)
    return tracks


def fetch_all_playlists() -> list[Playlist]:
    sp = get_client()
    raw_playlists = _paginate(sp.current_user_playlists(limit=50), sp)
    playlists: list[Playlist] = []
    for item in raw_playlists:
        log.info("Fetching tracks for '%s' (%d tracks)…", item["name"], item["tracks"]["total"])
        tracks = fetch_playlist_tracks(item["id"])
        playlists.append(
            Playlist(
                name=item["name"],
                description=item.get("description"),
                owner=item.get("owner", {}).get("display_name"),
                tracks=tracks,
                service_id=item["id"],
                service_url=item.get("external_urls", {}).get("spotify"),
                service=SERVICE,
            )
        )
    log.info("Fetched %d playlists", len(playlists))
    return playlists


def fetch_liked_songs() -> list[PlaylistTrack]:
    sp = get_client()
    items = _paginate(sp.current_user_saved_tracks(limit=50), sp)
    tracks: list[PlaylistTrack] = []
    for pos, item in enumerate(items):
        pt = _parse_track_item(item)
        if pt is not None:
            pt.position = pos
            tracks.append(pt)
    log.info("Fetched %d liked songs", len(tracks))
    return tracks


def fetch_saved_albums() -> list[SavedAlbum]:
    sp = get_client()
    items = _paginate(sp.current_user_saved_albums(limit=50), sp)
    albums: list[SavedAlbum] = []
    for item in items:
        album_data = item.get("album", {})
        album = _parse_album(album_data)
        # include the album's own tracks
        album.tracks = [
            Track(
                name=t["name"],
                artists=[_parse_artist(a) for a in t.get("artists", [])],
                duration_ms=t.get("duration_ms"),
                isrc=t.get("external_ids", {}).get("isrc"),
                service_id=t["id"],
                service_url=t.get("external_urls", {}).get("spotify"),
                service=SERVICE,
            )
            for t in _paginate(album_data.get("tracks", {"items": [], "next": None}), sp)
        ]
        albums.append(SavedAlbum(
            album=album,
            saved_at=_parse_dt(item.get("added_at")),
        ))
    log.info("Fetched %d saved albums", len(albums))
    return albums


def fetch_followed_artists() -> list[FollowedArtist]:
    sp = get_client()
    artists: list[FollowedArtist] = []
    result = sp.current_user_followed_artists(limit=50)
    while True:
        for item in result["artists"]["items"]:
            artists.append(FollowedArtist(
                artist=_parse_artist(item),
            ))
        after = result["artists"]["cursors"]["after"] if result["artists"]["cursors"] else None
        if after:
            result = sp.current_user_followed_artists(limit=50, after=after)
        else:
            break
    log.info("Fetched %d followed artists", len(artists))
    return artists


# ── Full library pull ────────────────────────────────────────────────────────

def fetch_library() -> Library:
    """Pull the user's entire Spotify library."""
    log.info("Starting full library export from Spotify…")
    return Library(
        service=SERVICE,
        exported_at=datetime.now(timezone.utc),
        playlists=fetch_all_playlists(),
        liked_songs=fetch_liked_songs(),
        saved_albums=fetch_saved_albums(),
        followed_artists=fetch_followed_artists(),
    )
