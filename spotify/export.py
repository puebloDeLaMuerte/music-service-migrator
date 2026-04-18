"""Fetch playlists from Spotify and convert to common models."""

from __future__ import annotations

from datetime import datetime, timezone

from common.log import get_logger
from common.models import Album, Artist, Playlist, PlaylistTrack, Track
from spotify.client import get_client

log = get_logger(__name__)


def _parse_track(item: dict) -> PlaylistTrack:
    """Convert a Spotify playlist-track item into a common PlaylistTrack."""
    t = item["track"]
    if t is None:
        return None  # type: ignore[return-value]

    artists = [
        Artist(name=a["name"], service_id=a["id"], service="spotify")
        for a in t.get("artists", [])
    ]
    album_data = t.get("album") or {}
    album = Album(
        name=album_data.get("name", ""),
        release_date=album_data.get("release_date"),
        total_tracks=album_data.get("total_tracks"),
        service_id=album_data.get("id"),
        service="spotify",
    )

    added_at = None
    if item.get("added_at"):
        try:
            added_at = datetime.fromisoformat(item["added_at"].replace("Z", "+00:00"))
        except ValueError:
            pass

    return PlaylistTrack(
        track=Track(
            name=t["name"],
            artists=artists,
            album=album,
            duration_ms=t.get("duration_ms"),
            isrc=t.get("external_ids", {}).get("isrc"),
            service_id=t["id"],
            service_url=t.get("external_urls", {}).get("spotify"),
            service="spotify",
        ),
        added_at=added_at,
        added_by=item.get("added_by", {}).get("id"),
    )


def fetch_playlist_tracks(playlist_id: str) -> list[PlaylistTrack]:
    sp = get_client()
    results = sp.playlist_items(playlist_id, limit=100)
    tracks: list[PlaylistTrack] = []
    position = 0
    while True:
        for item in results["items"]:
            pt = _parse_track(item)
            if pt is not None:
                pt.position = position
                tracks.append(pt)
                position += 1
        if results["next"]:
            results = sp.next(results)
        else:
            break
    return tracks


def fetch_all_playlists() -> list[Playlist]:
    """Return all of the current user's playlists with full track data."""
    sp = get_client()
    playlists: list[Playlist] = []
    results = sp.current_user_playlists(limit=50)
    while True:
        for item in results["items"]:
            log.info("Fetching tracks for '%s' (%d tracks)…", item["name"], item["tracks"]["total"])
            tracks = fetch_playlist_tracks(item["id"])
            playlists.append(
                Playlist(
                    name=item["name"],
                    description=item.get("description"),
                    owner=item.get("owner", {}).get("display_name"),
                    tracks=tracks,
                    service_id=item["id"],
                    service="spotify",
                )
            )
        if results["next"]:
            results = sp.next(results)
        else:
            break
    log.info("Fetched %d playlists", len(playlists))
    return playlists


def fetch_liked_songs() -> list[PlaylistTrack]:
    """Return the user's Liked Songs collection."""
    sp = get_client()
    results = sp.current_user_saved_tracks(limit=50)
    tracks: list[PlaylistTrack] = []
    position = 0
    while True:
        for item in results["items"]:
            pt = _parse_track(item)
            if pt is not None:
                pt.position = position
                tracks.append(pt)
                position += 1
        if results["next"]:
            results = sp.next(results)
        else:
            break
    log.info("Fetched %d liked songs", len(tracks))
    return tracks
