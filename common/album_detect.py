"""Detect playlists that contain full or near-full albums.

Analyses every album represented in a playlist, not just the most common one.
Cross-references against the user's saved albums when available.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from common.log import get_logger
from common.models import Playlist

log = get_logger(__name__)

MINIMUM_ALBUM_TRACKS = 3


@dataclass
class AlbumGroup:
    """One album's presence within a playlist."""

    album_name: str
    album_id: str
    album_total_tracks: int
    album_artists: str = ""
    album_url: str | None = None
    album_type: str | None = None
    present_track_ids: set[str] = field(default_factory=set)
    missing_tracks: list[str] = field(default_factory=list)
    in_library: bool = False

    @property
    def present_count(self) -> int:
        return len(self.present_track_ids)

    @property
    def match_ratio(self) -> float:
        if self.album_total_tracks == 0:
            return 0.0
        return self.present_count / self.album_total_tracks

    @property
    def is_complete(self) -> bool:
        return self.present_count >= self.album_total_tracks > 0


@dataclass
class PlaylistAnalysis:
    """Full album-detection result for one playlist."""

    playlist_name: str
    playlist_id: str | None
    total_tracks: int
    album_groups: list[AlbumGroup] = field(default_factory=list)

    @property
    def loose_track_count(self) -> int:
        """Tracks not accounted for by any detected album group."""
        accounted = set()
        for ag in self.album_groups:
            accounted |= ag.present_track_ids
        return self.total_tracks - len(accounted)


def analyse_playlist(
    playlist: Playlist,
    threshold: float = 0.8,
    saved_album_ids: set[str] | None = None,
) -> PlaylistAnalysis:
    """Analyse a playlist for album content.

    Args:
        playlist: The playlist to check.
        threshold: Minimum fraction of an album's tracks that must be present
            for the album to be included in the results.
        saved_album_ids: Set of album service_ids that are in the user's
            library.  Used to tag ``AlbumGroup.in_library``.
    """
    saved_album_ids = saved_album_ids or set()

    tracks_by_album: dict[str, list[tuple[str, str]]] = defaultdict(list)
    album_names: dict[str, str] = {}
    album_totals: dict[str, int] = {}
    album_artists: dict[str, str] = {}
    album_urls: dict[str, str | None] = {}
    album_types: dict[str, str | None] = {}

    for pt in playlist.tracks:
        album = pt.track.album
        if not album or not album.service_id:
            continue
        aid = album.service_id
        tracks_by_album[aid].append((pt.track.service_id, pt.track.name))
        album_names.setdefault(aid, album.name)
        if album.total_tracks:
            album_totals[aid] = album.total_tracks
        if aid not in album_artists:
            album_artists[aid] = ", ".join(a.name for a in album.artists) if album.artists else ""
            album_urls[aid] = album.service_url
            album_types[aid] = album.album_type

    groups: list[AlbumGroup] = []
    for aid, track_pairs in tracks_by_album.items():
        total = album_totals.get(aid, 0)
        if total < MINIMUM_ALBUM_TRACKS:
            continue

        present_ids = {tid for tid, _ in track_pairs}
        ratio = len(present_ids) / total if total else 0.0
        if ratio < threshold:
            continue

        group = AlbumGroup(
            album_name=album_names[aid],
            album_id=aid,
            album_total_tracks=total,
            album_artists=album_artists.get(aid, ""),
            album_url=album_urls.get(aid),
            album_type=album_types.get(aid),
            present_track_ids=present_ids,
            in_library=aid in saved_album_ids,
        )
        missing_count = total - len(present_ids)
        if missing_count > 0:
            group.missing_tracks = [f"({missing_count} track(s) not in playlist)"]

        groups.append(group)

    groups.sort(key=lambda g: g.match_ratio, reverse=True)

    if groups:
        log.info(
            "Playlist '%s': found %d album(s) above %.0f%% threshold",
            playlist.name,
            len(groups),
            threshold * 100,
        )

    return PlaylistAnalysis(
        playlist_name=playlist.name,
        playlist_id=playlist.service_id,
        total_tracks=playlist.track_count,
        album_groups=groups,
    )
