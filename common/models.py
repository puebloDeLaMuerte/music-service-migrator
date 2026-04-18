"""Service-agnostic data models.

These dataclasses are the common language shared across all service adapters
(Spotify, Tidal, …) and the migrator. Service-specific API responses should be
converted into these models at the adapter boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Artist:
    name: str
    service_id: str | None = None
    service: str | None = None


@dataclass
class Album:
    name: str
    release_date: str | None = None
    total_tracks: int | None = None
    service_id: str | None = None
    service: str | None = None


@dataclass
class Track:
    name: str
    artists: list[Artist] = field(default_factory=list)
    album: Album | None = None
    duration_ms: int | None = None
    isrc: str | None = None
    service_id: str | None = None
    service_url: str | None = None
    service: str | None = None


@dataclass
class PlaylistTrack:
    """A track in the context of a specific playlist."""

    track: Track
    position: int | None = None
    added_at: datetime | None = None
    added_by: str | None = None


@dataclass
class Playlist:
    name: str
    description: str | None = None
    owner: str | None = None
    tracks: list[PlaylistTrack] = field(default_factory=list)
    service_id: str | None = None
    service: str | None = None

    @property
    def track_count(self) -> int:
        return len(self.tracks)
