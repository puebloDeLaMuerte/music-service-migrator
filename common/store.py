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
from datetime import datetime
from pathlib import Path

from common import config
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

log = get_logger(__name__)


def sanitise_filename(name: str) -> str:
    """Turn a playlist name into a safe, readable filename stem."""
    name = unicodedata.normalize("NFC", name)
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


# ── Serialisation ────────────────────────────────────────────────────────────

def _image_to_dict(img: Image) -> dict:
    return {"url": img.url, "height": img.height, "width": img.width}


def _artist_to_dict(a: Artist) -> dict:
    return {
        "name": a.name,
        "genres": a.genres,
        "images": [_image_to_dict(i) for i in a.images],
        "service_id": a.service_id,
        "service_url": a.service_url,
        "uri": a.uri,
        "service": a.service,
    }


def _album_to_dict(a: Album) -> dict:
    return {
        "name": a.name,
        "artists": [_artist_to_dict(ar) for ar in a.artists],
        "album_type": a.album_type,
        "release_date": a.release_date,
        "release_date_precision": a.release_date_precision,
        "total_tracks": a.total_tracks,
        "tracks": [_track_to_dict(t) for t in a.tracks],
        "images": [_image_to_dict(i) for i in a.images],
        "genres": a.genres,
        "copyrights": a.copyrights,
        "upc": a.upc,
        "service_id": a.service_id,
        "service_url": a.service_url,
        "uri": a.uri,
        "service": a.service,
    }


def _track_to_dict(t: Track) -> dict:
    return {
        "name": t.name,
        "artists": [_artist_to_dict(a) for a in t.artists],
        "album": _album_to_dict(t.album) if t.album else None,
        "track_number": t.track_number,
        "disc_number": t.disc_number,
        "duration_ms": t.duration_ms,
        "explicit": t.explicit,
        "is_local": t.is_local,
        "isrc": t.isrc,
        "service_id": t.service_id,
        "service_url": t.service_url,
        "uri": t.uri,
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
        "collaborative": p.collaborative,
        "public": p.public,
        "snapshot_id": p.snapshot_id,
        "images": [_image_to_dict(i) for i in p.images],
        "service_id": p.service_id,
        "service_url": p.service_url,
        "uri": p.uri,
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


# ── Deserialisation ─────────────────────────────────────────────────────────

def _image_from_dict(d: dict) -> Image:
    return Image(url=d["url"], height=d.get("height"), width=d.get("width"))


def _artist_from_dict(d: dict) -> Artist:
    return Artist(
        name=d["name"],
        genres=d.get("genres", []),
        images=[_image_from_dict(i) for i in d.get("images", [])],
        service_id=d.get("service_id"),
        service_url=d.get("service_url"),
        uri=d.get("uri"),
        service=d.get("service"),
    )


def _album_from_dict(d: dict) -> Album:
    return Album(
        name=d["name"],
        artists=[_artist_from_dict(a) for a in d.get("artists", [])],
        album_type=d.get("album_type"),
        release_date=d.get("release_date"),
        release_date_precision=d.get("release_date_precision"),
        total_tracks=d.get("total_tracks"),
        tracks=[_track_from_dict(t) for t in d.get("tracks", [])],
        images=[_image_from_dict(i) for i in d.get("images", [])],
        genres=d.get("genres", []),
        copyrights=d.get("copyrights", []),
        upc=d.get("upc"),
        service_id=d.get("service_id"),
        service_url=d.get("service_url"),
        uri=d.get("uri"),
        service=d.get("service"),
    )


def _track_from_dict(d: dict) -> Track:
    return Track(
        name=d["name"],
        artists=[_artist_from_dict(a) for a in d.get("artists", [])],
        album=_album_from_dict(d["album"]) if d.get("album") else None,
        track_number=d.get("track_number"),
        disc_number=d.get("disc_number"),
        duration_ms=d.get("duration_ms"),
        explicit=d.get("explicit"),
        is_local=d.get("is_local"),
        isrc=d.get("isrc"),
        service_id=d.get("service_id"),
        service_url=d.get("service_url"),
        uri=d.get("uri"),
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
        collaborative=d.get("collaborative"),
        public=d.get("public"),
        snapshot_id=d.get("snapshot_id"),
        images=[_image_from_dict(i) for i in d.get("images", [])],
        tracks=[_playlist_track_from_dict(pt) for pt in d.get("tracks", [])],
        service_id=d.get("service_id"),
        service_url=d.get("service_url"),
        uri=d.get("uri"),
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

    pl_dir = sdir / "playlists"
    for pl in library.playlists:
        fname = sanitise_filename(pl.name) + ".json"
        _write_json(pl_dir / fname, _playlist_to_dict(pl))

    if library.liked_songs:
        _write_json(
            sdir / "liked_songs.json",
            [_playlist_track_to_dict(pt) for pt in library.liked_songs],
        )

    if library.saved_albums:
        _write_json(
            sdir / "saved_albums.json",
            [_saved_album_to_dict(sa) for sa in library.saved_albums],
        )

    if library.followed_artists:
        _write_json(
            sdir / "followed_artists.json",
            [_followed_artist_to_dict(fa) for fa in library.followed_artists],
        )

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


def save_playlist(playlist: Playlist, service: str) -> Path:
    """Write (or overwrite) a single playlist JSON on disk."""
    sdir = _service_dir(service)
    pl_dir = sdir / "playlists"
    fname = sanitise_filename(playlist.name) + ".json"
    path = pl_dir / fname
    _write_json(path, _playlist_to_dict(playlist))
    return path


def delete_playlist(playlist_name: str, service: str) -> bool:
    """Delete a playlist JSON from disk. Returns True if file existed."""
    sdir = _service_dir(service)
    path = sdir / "playlists" / (sanitise_filename(playlist_name) + ".json")
    if path.exists():
        path.unlink()
        log.info("Deleted %s", path)
        return True
    log.warning("Playlist file not found for deletion: %s", path)
    return False


def append_saved_albums(albums: list[SavedAlbum], service: str) -> int:
    """Merge new albums into saved_albums.json, skipping duplicates.

    Returns the number of newly added albums.
    """
    sdir = _service_dir(service)
    sa_path = sdir / "saved_albums.json"

    existing: list[dict] = []
    if sa_path.exists():
        existing = _read_json(sa_path)

    existing_ids = {
        d.get("album", {}).get("service_id")
        for d in existing
        if d.get("album", {}).get("service_id")
    }

    added = 0
    for sa in albums:
        if sa.album.service_id and sa.album.service_id in existing_ids:
            log.info("Album '%s' already in saved albums, skipping", sa.album.name)
            continue
        existing.append(_saved_album_to_dict(sa))
        if sa.album.service_id:
            existing_ids.add(sa.album.service_id)
        added += 1

    _write_json(sa_path, existing)
    log.info("Appended %d new album(s) to saved_albums.json", added)
    return added


# ── Read ─────────────────────────────────────────────────────────────────────

def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_library(service: str) -> Library:
    """Load a previously exported library from disk."""
    sdir = _service_dir(service)
    if not sdir.exists():
        raise FileNotFoundError(f"No exported data found at {sdir}")

    playlists: list[Playlist] = []
    pl_dir = sdir / "playlists"
    if pl_dir.exists():
        for f in sorted(pl_dir.glob("*.json")):
            playlists.append(_playlist_from_dict(_read_json(f)))

    liked: list[PlaylistTrack] = []
    ls_path = sdir / "liked_songs.json"
    if ls_path.exists():
        liked = [_playlist_track_from_dict(d) for d in _read_json(ls_path)]

    albums: list[SavedAlbum] = []
    sa_path = sdir / "saved_albums.json"
    if sa_path.exists():
        albums = [_saved_album_from_dict(d) for d in _read_json(sa_path)]

    artists: list[FollowedArtist] = []
    fa_path = sdir / "followed_artists.json"
    if fa_path.exists():
        artists = [_followed_artist_from_dict(d) for d in _read_json(fa_path)]

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
