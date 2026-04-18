"""Query Spotify's catalog for album / artist / track metadata."""

from __future__ import annotations

from common.log import get_logger
from common.models import Album, Artist, Image, Track
from spotify.client import get_client

log = get_logger(__name__)

SERVICE = "spotify"


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


def get_album(album_id: str) -> Album:
    sp = get_client()
    data = sp.album(album_id)
    return Album(
        name=data["name"],
        artists=[_parse_artist(a) for a in data.get("artists", [])],
        album_type=data.get("album_type"),
        release_date=data.get("release_date"),
        release_date_precision=data.get("release_date_precision"),
        total_tracks=data.get("total_tracks"),
        images=_parse_images(data.get("images")),
        genres=data.get("genres", []),
        copyrights=data.get("copyrights", []),
        upc=(data.get("external_ids") or {}).get("upc"),
        service_id=data["id"],
        service_url=(data.get("external_urls") or {}).get("spotify"),
        uri=data.get("uri"),
        service=SERVICE,
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
                    artists=[_parse_artist(a) for a in item.get("artists", [])],
                    track_number=item.get("track_number"),
                    disc_number=item.get("disc_number"),
                    duration_ms=item.get("duration_ms"),
                    explicit=item.get("explicit"),
                    is_local=item.get("is_local"),
                    service_id=item["id"],
                    service_url=(item.get("external_urls") or {}).get("spotify"),
                    uri=item.get("uri"),
                    service=SERVICE,
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
        album_data = item.get("album", {})
        tracks.append(
            Track(
                name=item["name"],
                artists=[_parse_artist(a) for a in item.get("artists", [])],
                album=Album(
                    name=album_data.get("name", ""),
                    artists=[_parse_artist(a) for a in album_data.get("artists", [])],
                    album_type=album_data.get("album_type"),
                    release_date=album_data.get("release_date"),
                    release_date_precision=album_data.get("release_date_precision"),
                    total_tracks=album_data.get("total_tracks"),
                    images=_parse_images(album_data.get("images")),
                    service_id=album_data.get("id"),
                    service_url=(album_data.get("external_urls") or {}).get("spotify"),
                    uri=album_data.get("uri"),
                    service=SERVICE,
                ),
                track_number=item.get("track_number"),
                disc_number=item.get("disc_number"),
                duration_ms=item.get("duration_ms"),
                explicit=item.get("explicit"),
                is_local=item.get("is_local"),
                isrc=(item.get("external_ids") or {}).get("isrc"),
                service_id=item["id"],
                service_url=(item.get("external_urls") or {}).get("spotify"),
                uri=item.get("uri"),
                service=SERVICE,
            )
        )
    return tracks
