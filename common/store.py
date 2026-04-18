"""Read and write library data to disk as JSON.

Directory layout under the configured output dir:

    <service>/
    ├── playlists/
    │   ├── <sanitised_name>.json
    │   └── …
    ├── liked_songs.json
    ├── saved_albums.json
    └── followed_artists.json
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from common import config
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

log = get_logger(__name__)


def _sanitise_filename(name: str) -> str:
    """Turn a playlist name into a safe, readable filename stem."""
    name = unicodedata.normalize("NFC", name)
    # strip emoji and other symbol characters
    name = re.sub(r"[^\w\s\-]", "", name, flags=re.UNICODE)
    name = name.strip().replace(" ", "_")
    return name or "unnamed"


def _service_dir(service: str) -> Path:
    return config.output_dir() / service


def _dt_to_str(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _dt_from_str(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


# ── Serialisation helpers ────────────────────────────────────────────────────

def _artist_to_dict(a: Artist) -> dict:
    return asdict(a)


def _album_to_dict(a: Album) -> dict:
    d = {
        "name": a.name,
        "artists": [_artist_to_dict(ar) for ar in a.artists],
        "release_date": a.release_date,
        "total_tracks": a.total_tracks,
        "tracks": [_track_to_dict(t) for t in a.tracks],
        "service_id": a.service_id,
        "service_url": a.service_url,
        "service": a.service,
    }
    return d


def _track_to_dict(t: Track) -> dict:
    return {
        "name": t.name,
        "artists": [_artist_to_dict(a) for a in t.artists],
        "album": _album_to_dict(t.album) if t.album else None,
        "duration_ms": t.duration_ms,
        "isrc": t.isrc,
        "service_id": t.service_id,
        "service_url": t.service_url,
        "service": t.service,
    }


def _playlist_track_to_dict(pt: PlaylistTrack) -> dict:
    return {
        "track": _track_to_dict(pt.track),
        "position": pt.position,
        "added_at": _dt_to_str(pt.added_at),
        "added_by": pt.added_by,
    }


def _playlist_to_dict(p: Playlist) -> dict:
    return {
        "name": p.name,
        "description": p.description,
        "owner": p.owner,
        "service_id": p.service_id,
        "service_url": p.service_url,
        "service": p.service,
        "track_count": p.track_count,
        "tracks": [_playlist_track_to_dict(pt) for pt in p.tracks],
    }


def _saved_album_to_dict(sa: SavedAlbum) -> dict:
    return {
        "album": _album_to_dict(sa.album),
        "saved_at": _dt_to_str(sa.saved_at),
    }


def _followed_artist_to_dict(fa: FollowedArtist) -> dict:
    return {
        "artist": _artist_to_dict(fa.artist),
        "followed_at": _dt_to_str(fa.followed_at),
    }


# ── Deserialisation helpers ──────────────────────────────────────────────────

def _artist_from_dict(d: dict) -> Artist:
    return Artist(
        name=d["name"],
        genres=d.get("genres", []),
        service_id=d.get("service_id"),
        service_url=d.get("service_url"),
        service=d.get("service"),
    )


def _album_from_dict(d: dict) -> Album:
    return Album(
        name=d["name"],
        artists=[_artist_from_dict(a) for a in d.get("artists", [])],
        release_date=d.get("release_date"),
        total_tracks=d.get("total_tracks"),
        tracks=[_track_from_dict(t) for t in d.get("tracks", [])],
        service_id=d.get("service_id"),
        service_url=d.get("service_url"),
        service=d.get("service"),
    )


def _track_from_dict(d: dict) -> Track:
    return Track(
        name=d["name"],
        artists=[_artist_from_dict(a) for a in d.get("artists", [])],
        album=_album_from_dict(d["album"]) if d.get("album") else None,
        duration_ms=d.get("duration_ms"),
        isrc=d.get("isrc"),
        service_id=d.get("service_id"),
        service_url=d.get("service_url"),
        service=d.get("service"),
    )


def _playlist_track_from_dict(d: dict) -> PlaylistTrack:
    return PlaylistTrack(
        track=_track_from_dict(d["track"]),
        position=d.get("position"),
        added_at=_dt_from_str(d.get("added_at")),
        added_by=d.get("added_by"),
    )


def _playlist_from_dict(d: dict) -> Playlist:
    return Playlist(
        name=d["name"],
        description=d.get("description"),
        owner=d.get("owner"),
        tracks=[_playlist_track_from_dict(pt) for pt in d.get("tracks", [])],
        service_id=d.get("service_id"),
        service_url=d.get("service_url"),
        service=d.get("service"),
    )


def _saved_album_from_dict(d: dict) -> SavedAlbum:
    return SavedAlbum(
        album=_album_from_dict(d["album"]),
        saved_at=_dt_from_str(d.get("saved_at")),
    )


def _followed_artist_from_dict(d: dict) -> FollowedArtist:
    return FollowedArtist(
        artist=_artist_from_dict(d["artist"]),
        followed_at=_dt_from_str(d.get("followed_at")),
    )


# ── Write ────────────────────────────────────────────────────────────────────

def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Wrote %s", path)


def save_library(library: Library) -> Path:
    """Persist an entire Library to disk. Returns the service directory."""
    sdir = _service_dir(library.service)

    # playlists — one file each
    pl_dir = sdir / "playlists"
    for pl in library.playlists:
        fname = _sanitise_filename(pl.name) + ".json"
        _write_json(pl_dir / fname, _playlist_to_dict(pl))

    # liked songs
    if library.liked_songs:
        _write_json(
            sdir / "liked_songs.json",
            [_playlist_track_to_dict(pt) for pt in library.liked_songs],
        )

    # saved albums
    if library.saved_albums:
        _write_json(
            sdir / "saved_albums.json",
            [_saved_album_to_dict(sa) for sa in library.saved_albums],
        )

    # followed artists
    if library.followed_artists:
        _write_json(
            sdir / "followed_artists.json",
            [_followed_artist_to_dict(fa) for fa in library.followed_artists],
        )

    # metadata
    _write_json(sdir / "export_meta.json", {
        "service": library.service,
        "exported_at": _dt_to_str(library.exported_at),
        "playlist_count": len(library.playlists),
        "liked_song_count": len(library.liked_songs),
        "saved_album_count": len(library.saved_albums),
        "followed_artist_count": len(library.followed_artists),
    })

    log.info(
        "Library saved: %d playlists, %d liked songs, %d albums, %d artists → %s",
        len(library.playlists),
        len(library.liked_songs),
        len(library.saved_albums),
        len(library.followed_artists),
        sdir,
    )
    return sdir


# ── Read ─────────────────────────────────────────────────────────────────────

def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_library(service: str) -> Library:
    """Load a previously exported library from disk."""
    sdir = _service_dir(service)
    if not sdir.exists():
        raise FileNotFoundError(f"No exported data found at {sdir}")

    # playlists
    playlists: list[Playlist] = []
    pl_dir = sdir / "playlists"
    if pl_dir.exists():
        for f in sorted(pl_dir.glob("*.json")):
            playlists.append(_playlist_from_dict(_read_json(f)))

    # liked songs
    liked: list[PlaylistTrack] = []
    ls_path = sdir / "liked_songs.json"
    if ls_path.exists():
        liked = [_playlist_track_from_dict(d) for d in _read_json(ls_path)]

    # saved albums
    albums: list[SavedAlbum] = []
    sa_path = sdir / "saved_albums.json"
    if sa_path.exists():
        albums = [_saved_album_from_dict(d) for d in _read_json(sa_path)]

    # followed artists
    artists: list[FollowedArtist] = []
    fa_path = sdir / "followed_artists.json"
    if fa_path.exists():
        artists = [_followed_artist_from_dict(d) for d in _read_json(fa_path)]

    # metadata
    meta_path = sdir / "export_meta.json"
    exported_at = None
    if meta_path.exists():
        meta = _read_json(meta_path)
        exported_at = _dt_from_str(meta.get("exported_at"))

    log.info(
        "Library loaded: %d playlists, %d liked songs, %d albums, %d artists ← %s",
        len(playlists), len(liked), len(albums), len(artists), sdir,
    )
    return Library(
        service=service,
        exported_at=exported_at,
        playlists=playlists,
        liked_songs=liked,
        saved_albums=albums,
        followed_artists=artists,
    )
