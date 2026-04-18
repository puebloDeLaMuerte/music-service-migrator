"""Pull the user's complete Spotify library into common models."""

from __future__ import annotations

from datetime import datetime, timezone

from common.log import get_logger
from common.models import (
    Album,
    Artist,
    FollowedArtist,
    Image,
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


def _parse_images(data: list[dict] | None) -> list[Image]:
    if not data:
        return []
    return [Image(url=img["url"], height=img.get("height"), width=img.get("width"))
            for img in data if img.get("url")]


def _parse_artist(data: dict) -> Artist:
    return Artist(
        name=data["name"],
        genres=data.get("genres", []),
        images=_parse_images(data.get("images")),
        service_id=data.get("id"),
        service_url=(data.get("external_urls") or {}).get("spotify"),
        uri=data.get("uri"),
        service=SERVICE,
    )


def _parse_album(data: dict) -> Album:
    return Album(
        name=data.get("name", ""),
        artists=[_parse_artist(a) for a in data.get("artists", [])],
        album_type=data.get("album_type"),
        release_date=data.get("release_date"),
        release_date_precision=data.get("release_date_precision"),
        total_tracks=data.get("total_tracks"),
        images=_parse_images(data.get("images")),
        genres=data.get("genres", []),
        copyrights=data.get("copyrights", []),
        upc=(data.get("external_ids") or {}).get("upc"),
        service_id=data.get("id"),
        service_url=(data.get("external_urls") or {}).get("spotify"),
        uri=data.get("uri"),
        service=SERVICE,
    )


def _parse_track(t: dict) -> Track:
    """Parse a raw Spotify track object (not the wrapper item)."""
    album_data = t.get("album") or {}
    return Track(
        name=t["name"],
        artists=[_parse_artist(a) for a in t.get("artists", [])],
        album=_parse_album(album_data) if album_data.get("id") else None,
        track_number=t.get("track_number"),
        disc_number=t.get("disc_number"),
        duration_ms=t.get("duration_ms"),
        explicit=t.get("explicit"),
        is_local=t.get("is_local"),
        isrc=(t.get("external_ids") or {}).get("isrc"),
        service_id=t.get("id"),
        service_url=(t.get("external_urls") or {}).get("spotify"),
        uri=t.get("uri"),
        service=SERVICE,
    )


def _parse_playlist_track_item(wrapper: dict) -> PlaylistTrack | None:
    """Parse a playlist item wrapper. Handles both spotipy <2.26 and >=2.26."""
    t = wrapper.get("item") or wrapper.get("track")
    if t is None:
        return None
    if t.get("type") != "track":
        return None

    return PlaylistTrack(
        track=_parse_track(t),
        added_at=_parse_dt(wrapper.get("added_at")),
        added_by=(wrapper.get("added_by") or {}).get("id"),
    )


def _parse_saved_track_item(wrapper: dict) -> PlaylistTrack | None:
    """Parse a saved-track wrapper (liked songs endpoint)."""
    t = wrapper.get("track")
    if t is None:
        return None

    return PlaylistTrack(
        track=_parse_track(t),
        added_at=_parse_dt(wrapper.get("added_at")),
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
    items = _paginate(
        sp.playlist_items(playlist_id, limit=100, market="from_token",
                          additional_types=("track",)),
        sp,
    )
    tracks: list[PlaylistTrack] = []
    for pos, wrapper in enumerate(items):
        pt = _parse_playlist_track_item(wrapper)
        if pt is not None:
            pt.position = pos
            tracks.append(pt)
    return tracks


def fetch_all_playlists() -> list[Playlist]:
    from spotipy.exceptions import SpotifyException

    sp = get_client()
    raw_playlists = _paginate(sp.current_user_playlists(limit=50), sp)
    playlists: list[Playlist] = []
    skipped = 0
    for item in raw_playlists:
        track_total = (item.get("tracks") or item.get("items") or {}).get("total", "?")
        log.info("Fetching tracks for '%s' (%s tracks)…", item["name"], track_total)
        try:
            tracks = fetch_playlist_tracks(item["id"])
        except SpotifyException as exc:
            log.warning(
                "Skipping '%s' – API returned %s: %s",
                item["name"], exc.http_status, exc.msg,
            )
            skipped += 1
            continue
        playlists.append(
            Playlist(
                name=item["name"],
                description=item.get("description"),
                owner=(item.get("owner") or {}).get("display_name"),
                collaborative=item.get("collaborative"),
                public=item.get("public"),
                snapshot_id=item.get("snapshot_id"),
                images=_parse_images(item.get("images")),
                tracks=tracks,
                service_id=item["id"],
                service_url=(item.get("external_urls") or {}).get("spotify"),
                uri=item.get("uri"),
                service=SERVICE,
            )
        )
    log.info("Fetched %d playlists (%d skipped)", len(playlists), skipped)
    return playlists


def fetch_liked_songs() -> list[PlaylistTrack]:
    sp = get_client()
    items = _paginate(sp.current_user_saved_tracks(limit=50), sp)
    tracks: list[PlaylistTrack] = []
    for pos, wrapper in enumerate(items):
        pt = _parse_saved_track_item(wrapper)
        if pt is not None:
            pt.position = pos
            tracks.append(pt)
    log.info("Fetched %d liked songs", len(tracks))
    return tracks


def _parse_album_track(t: dict) -> Track:
    """Parse a track from an album's track listing (no album sub-object)."""
    return Track(
        name=t["name"],
        artists=[_parse_artist(a) for a in t.get("artists", [])],
        track_number=t.get("track_number"),
        disc_number=t.get("disc_number"),
        duration_ms=t.get("duration_ms"),
        explicit=t.get("explicit"),
        is_local=t.get("is_local"),
        isrc=(t.get("external_ids") or {}).get("isrc"),
        service_id=t.get("id"),
        service_url=(t.get("external_urls") or {}).get("spotify"),
        uri=t.get("uri"),
        service=SERVICE,
    )


def fetch_saved_albums() -> list[SavedAlbum]:
    sp = get_client()
    items = _paginate(sp.current_user_saved_albums(limit=50), sp)
    albums: list[SavedAlbum] = []
    for item in items:
        album_data = item.get("album", {})
        album = _parse_album(album_data)
        raw_tracks = album_data.get("tracks", {})
        if raw_tracks and "items" in raw_tracks:
            album.tracks = [
                _parse_album_track(t) for t in _paginate(raw_tracks, sp)
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
