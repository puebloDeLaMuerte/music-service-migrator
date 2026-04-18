"""Service-agnostic data models.

These dataclasses are the common language shared across all service adapters
(Spotify, Tidal, …) and the migrator. Service-specific API responses should be
converted into these models at the adapter boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Image:
    url: str
    height: int | None = None
    width: int | None = None


@dataclass
class Artist:
    name: str
    genres: list[str] = field(default_factory=list)
    images: list[Image] = field(default_factory=list)
    service_id: str | None = None
    service_url: str | None = None
    uri: str | None = None
    service: str | None = None


@dataclass
class Album:
    name: str
    artists: list[Artist] = field(default_factory=list)
    album_type: str | None = None
    release_date: str | None = None
    release_date_precision: str | None = None
    total_tracks: int | None = None
    tracks: list[Track] = field(default_factory=list)
    images: list[Image] = field(default_factory=list)
    genres: list[str] = field(default_factory=list)
    copyrights: list[dict] = field(default_factory=list)
    upc: str | None = None
    service_id: str | None = None
    service_url: str | None = None
    uri: str | None = None
    service: str | None = None


@dataclass
class Track:
    name: str
    artists: list[Artist] = field(default_factory=list)
    album: Album | None = None
    track_number: int | None = None
    disc_number: int | None = None
    duration_ms: int | None = None
    explicit: bool | None = None
    is_local: bool | None = None
    isrc: str | None = None
    service_id: str | None = None
    service_url: str | None = None
    uri: str | None = None
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
    collaborative: bool | None = None
    public: bool | None = None
    snapshot_id: str | None = None
    images: list[Image] = field(default_factory=list)
    tracks: list[PlaylistTrack] = field(default_factory=list)
    service_id: str | None = None
    service_url: str | None = None
    uri: str | None = None
    service: str | None = None

    @property
    def track_count(self) -> int:
        return len(self.tracks)


@dataclass
class SavedAlbum:
    """An album the user has saved/added to their library."""

    album: Album
    saved_at: datetime | None = None


@dataclass
class FollowedArtist:
    """An artist the user follows."""

    artist: Artist
    followed_at: datetime | None = None


@dataclass
class Library:
    """Complete snapshot of a user's music library on a given service."""

    service: str
    exported_at: datetime | None = None
    playlists: list[Playlist] = field(default_factory=list)
    liked_songs: list[PlaylistTrack] = field(default_factory=list)
    saved_albums: list[SavedAlbum] = field(default_factory=list)
    followed_artists: list[FollowedArtist] = field(default_factory=list)
