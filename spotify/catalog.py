"""Query Spotify's catalog for album / artist / track metadata."""

from __future__ import annotations

from common.log import get_logger
from common.models import Album, Artist, Track
from spotify.client import get_client

log = get_logger(__name__)


def get_album(album_id: str) -> Album:
    sp = get_client()
    data = sp.album(album_id)
    return Album(
        name=data["name"],
        release_date=data.get("release_date"),
        total_tracks=data.get("total_tracks"),
        service_id=data["id"],
        service="spotify",
    )


def get_album_tracks(album_id: str) -> list[Track]:
    """Return all tracks on an album, handling pagination."""
    sp = get_client()
    results = sp.album_tracks(album_id, limit=50)
    tracks: list[Track] = []
    while True:
        for item in results["items"]:
            tracks.append(
                Track(
                    name=item["name"],
                    artists=[
                        Artist(name=a["name"], service_id=a["id"], service="spotify")
                        for a in item.get("artists", [])
                    ],
                    duration_ms=item.get("duration_ms"),
                    service_id=item["id"],
                    service="spotify",
                )
            )
        if results["next"]:
            results = sp.next(results)
        else:
            break
    return tracks


def search_tracks(query: str, limit: int = 10) -> list[Track]:
    sp = get_client()
    results = sp.search(q=query, type="track", limit=limit)
    tracks: list[Track] = []
    for item in results["tracks"]["items"]:
        tracks.append(
            Track(
                name=item["name"],
                artists=[
                    Artist(name=a["name"], service_id=a["id"], service="spotify")
                    for a in item.get("artists", [])
                ],
                album=Album(
                    name=item["album"]["name"],
                    service_id=item["album"]["id"],
                    service="spotify",
                ),
                duration_ms=item.get("duration_ms"),
                isrc=item.get("external_ids", {}).get("isrc"),
                service_id=item["id"],
                service_url=item["external_urls"].get("spotify"),
                service="spotify",
            )
        )
    return tracks
