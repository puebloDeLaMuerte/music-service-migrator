"""Detect duplicate tracks within and across playlists."""

from __future__ import annotations

from dataclasses import dataclass, field

from common.log import get_logger
from common.models import Playlist, PlaylistTrack

log = get_logger(__name__)


@dataclass
class Duplicate:
    """A group of playlist-track entries that refer to the same underlying track."""

    track_name: str
    artists: str
    occurrences: list[tuple[str, int]] = field(default_factory=list)
    """List of (playlist_name, position) pairs."""


def _track_key(pt: PlaylistTrack) -> str:
    """Normalised key for comparing tracks regardless of re-releases etc."""
    artists = ", ".join(
        sorted(a.name.lower().strip() for a in pt.track.artists)
    )
    return f"{pt.track.name.lower().strip()}|{artists}"


def playlist_track_key(pt: PlaylistTrack) -> str:
    """Public alias for the same identity string used by :class:`Duplicate` detection."""
    return _track_key(pt)


def duplicate_fingerprint(d: Duplicate) -> str:
    """Stable id for a duplicate group (matches :func:`playlist_track_key` for member tracks)."""
    return f"{d.track_name}|{d.artists}"


def find_duplicates_within(playlist: Playlist) -> list[Duplicate]:
    """Find tracks that appear more than once inside a single playlist."""
    seen: dict[str, list[tuple[str, int]]] = {}
    for pt in playlist.tracks:
        key = _track_key(pt)
        seen.setdefault(key, []).append((playlist.name, pt.position or 0))

    dupes = []
    for key, entries in seen.items():
        if len(entries) > 1:
            name_part, artists_part = key.split("|", 1)
            dupes.append(Duplicate(name_part, artists_part, entries))
    return dupes


def find_duplicates_across(playlists: list[Playlist]) -> list[Duplicate]:
    """Find tracks that appear in more than one playlist."""
    seen: dict[str, list[tuple[str, int]]] = {}
    for pl in playlists:
        for pt in pl.tracks:
            key = _track_key(pt)
            seen.setdefault(key, []).append((pl.name, pt.position or 0))

    dupes = []
    for key, entries in seen.items():
        unique_playlists = {name for name, _ in entries}
        if len(unique_playlists) > 1:
            name_part, artists_part = key.split("|", 1)
            dupes.append(Duplicate(name_part, artists_part, entries))
    return dupes
