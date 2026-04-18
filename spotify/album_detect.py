"""Detect playlists that are essentially just full albums."""

from __future__ import annotations

from dataclasses import dataclass

from common.log import get_logger
from common.models import Playlist
from spotify import catalog
from spotify.client import get_client

log = get_logger(__name__)


@dataclass
class AlbumMatch:
    playlist_name: str
    album_name: str
    album_id: str
    match_ratio: float  # 0.0 – 1.0


def _most_common_album_id(playlist: Playlist) -> str | None:
    """Return the album service_id that appears most frequently in the playlist."""
    counts: dict[str, int] = {}
    for pt in playlist.tracks:
        aid = pt.track.album.service_id if pt.track.album else None
        if aid:
            counts[aid] = counts.get(aid, 0) + 1
    if not counts:
        return None
    return max(counts, key=counts.get)  # type: ignore[arg-type]


def check_playlist(playlist: Playlist, threshold: float = 0.8) -> AlbumMatch | None:
    """Return an AlbumMatch if ``playlist`` looks like a full album.

    ``threshold`` is the minimum fraction of album tracks that must appear in
    the playlist (and vice-versa) to be considered a match.
    """
    album_id = _most_common_album_id(playlist)
    if album_id is None:
        return None

    album = catalog.get_album(album_id)
    album_tracks = catalog.get_album_tracks(album_id)

    if not album_tracks:
        return None

    album_track_ids = {t.service_id for t in album_tracks}
    playlist_track_ids = {
        pt.track.service_id
        for pt in playlist.tracks
        if pt.track.service_id
    }

    overlap = album_track_ids & playlist_track_ids
    ratio = len(overlap) / max(len(album_track_ids), 1)

    if ratio >= threshold:
        log.info(
            "Playlist '%s' matches album '%s' (%.0f%%)",
            playlist.name,
            album.name,
            ratio * 100,
        )
        return AlbumMatch(
            playlist_name=playlist.name,
            album_name=album.name,
            album_id=album_id,
            match_ratio=ratio,
        )
    return None
