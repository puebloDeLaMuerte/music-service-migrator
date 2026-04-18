"""Read and write workspace library data to disk as JSON.

Layout under :func:`common.config.work_dir`::

    playlists/
        <sanitised_name>.json
    liked_songs.json
    saved_albums.json
    followed_artists.json
    workspace_meta.json
    meta/
        dedupe_ignored.json
        playlist2album_log.json
        …
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
    Provenance,
    RecordMeta,
    SavedAlbum,
    Track,
)

log = get_logger(__name__)

WORKSPACE_SCHEMA_VERSION = 1


def sanitise_filename(name: str) -> str:
    """Turn a playlist name into a safe, readable filename stem."""
    name = unicodedata.normalize("NFC", name)
    name = re.sub(r"[^\w\s\-]", "", name, flags=re.UNICODE)
    name = name.strip().replace(" ", "_")
    return name or "unnamed"


def meta_dir() -> Path:
    """``<work_dir>/meta`` — dedupe ignore list, P2A logs, artwork, …."""
    p = config.work_dir() / "meta"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _dt_to_str(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _dt_from_str(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _provenance_to_dict(p: Provenance) -> dict:
    return {
        "provider": p.provider,
        "origin": p.origin,
        "pulled_at": _dt_to_str(p.pulled_at),
        "updated_at": _dt_to_str(p.updated_at),
    }


def _provenance_from_dict(d: dict) -> Provenance:
    return Provenance(
        provider=d["provider"],
        origin=d["origin"],
        pulled_at=_dt_from_str(d.get("pulled_at")),
        updated_at=_dt_from_str(d.get("updated_at")),
    )


def _record_meta_to_dict(rm: RecordMeta) -> dict:
    return {"provenance": _provenance_to_dict(rm.provenance)}


def _record_meta_from_dict(d: dict) -> RecordMeta:
    return RecordMeta(provenance=_provenance_from_dict(d["provenance"]))


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
        "record_meta": _record_meta_to_dict(pt.record_meta),
        "position": pt.position,
        "added_at": _dt_to_str(pt.added_at),
        "added_by": pt.added_by,
    }


def _playlist_to_dict(p: Playlist) -> dict:
    return {
        "name": p.name,
        "record_meta": _record_meta_to_dict(p.record_meta),
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
        "record_meta": _record_meta_to_dict(sa.record_meta),
        "saved_at": _dt_to_str(sa.saved_at),
    }


def _followed_artist_to_dict(fa: FollowedArtist) -> dict:
    return {
        "artist": _artist_to_dict(fa.artist),
        "record_meta": _record_meta_to_dict(fa.record_meta),
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
        record_meta=_record_meta_from_dict(d["record_meta"]),
        position=d.get("position"),
        added_at=_dt_from_str(d.get("added_at")),
        added_by=d.get("added_by"),
    )


def _playlist_from_dict(d: dict) -> Playlist:
    return Playlist(
        name=d["name"],
        record_meta=_record_meta_from_dict(d["record_meta"]),
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
        record_meta=_record_meta_from_dict(d["record_meta"]),
        saved_at=_dt_from_str(d.get("saved_at")),
    )


def _followed_artist_from_dict(d: dict) -> FollowedArtist:
    return FollowedArtist(
        artist=_artist_from_dict(d["artist"]),
        record_meta=_record_meta_from_dict(d["record_meta"]),
        followed_at=_dt_from_str(d.get("followed_at")),
    )


# ── Write / read helpers ─────────────────────────────────────────────────────


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Wrote %s", path)


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _workspace_root() -> Path:
    return config.work_dir()


def _playlist_filename(pl: Playlist) -> str:
    return sanitise_filename(pl.name) + ".json"


def _workspace_meta_payload(library: Library) -> dict:
    return {
        "schema_version": WORKSPACE_SCHEMA_VERSION,
        "exported_at": _dt_to_str(library.exported_at),
        "last_pull_provider": library.last_pull_provider,
        "playlist_count": len(library.playlists),
        "liked_song_count": len(library.liked_songs),
        "saved_album_count": len(library.saved_albums),
        "followed_artist_count": len(library.followed_artists),
    }


def save_workspace(library: Library, *, delete_orphan_playlists: bool = True) -> Path:
    """Write the full library to disk; optionally remove playlist files not in ``library``.

    Returns the workspace root path.
    """
    root = _workspace_root()
    pl_dir = root / "playlists"
    pl_dir.mkdir(parents=True, exist_ok=True)

    wanted = {_playlist_filename(p) for p in library.playlists}
    if delete_orphan_playlists:
        for path in pl_dir.glob("*.json"):
            if path.name not in wanted:
                path.unlink()
                log.info("Removed orphan playlist file %s", path)

    for pl in library.playlists:
        _write_json(pl_dir / _playlist_filename(pl), _playlist_to_dict(pl))

    _write_json(
        root / "liked_songs.json",
        [_playlist_track_to_dict(pt) for pt in library.liked_songs],
    )
    _write_json(
        root / "saved_albums.json",
        [_saved_album_to_dict(sa) for sa in library.saved_albums],
    )
    _write_json(
        root / "followed_artists.json",
        [_followed_artist_to_dict(fa) for fa in library.followed_artists],
    )
    _write_json(root / "workspace_meta.json", _workspace_meta_payload(library))

    log.info(
        "Workspace saved: %d playlists, %d liked, %d albums, %d artists → %s",
        len(library.playlists),
        len(library.liked_songs),
        len(library.saved_albums),
        len(library.followed_artists),
        root,
    )
    return root


def save_workspace_auxiliary(library: Library) -> None:
    """Write liked songs, saved albums, followed artists, and workspace_meta only.

    Does not create or update playlist files. Use after mutating auxiliary lists
    in memory (e.g. TUI remove on liked/saved lists).
    """
    root = _workspace_root()
    _write_json(
        root / "liked_songs.json",
        [_playlist_track_to_dict(pt) for pt in library.liked_songs],
    )
    _write_json(
        root / "saved_albums.json",
        [_saved_album_to_dict(sa) for sa in library.saved_albums],
    )
    _write_json(
        root / "followed_artists.json",
        [_followed_artist_to_dict(fa) for fa in library.followed_artists],
    )
    _write_json(root / "workspace_meta.json", _workspace_meta_payload(library))
    log.info(
        "Updated auxiliary workspace data: %d liked, %d albums, %d artists → %s",
        len(library.liked_songs),
        len(library.saved_albums),
        len(library.followed_artists),
        root,
    )


def save_playlist(playlist: Playlist) -> Path:
    """Write (or overwrite) a single playlist JSON on disk."""
    root = _workspace_root()
    pl_dir = root / "playlists"
    path = pl_dir / _playlist_filename(playlist)
    _write_json(path, _playlist_to_dict(playlist))
    return path


def delete_playlist(playlist_name: str) -> bool:
    """Delete a playlist JSON from disk. Returns True if file existed."""
    root = _workspace_root()
    path = root / "playlists" / (sanitise_filename(playlist_name) + ".json")
    if path.exists():
        path.unlink()
        log.info("Deleted %s", path)
        return True
    log.warning("Playlist file not found for deletion: %s", path)
    return False


def append_saved_albums(albums: list[SavedAlbum]) -> int:
    """Merge new albums into saved_albums.json, skipping duplicates by album service_id.

    Returns the number of newly added albums.
    """
    root = _workspace_root()
    sa_path = root / "saved_albums.json"

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


def load_workspace() -> Library:
    """Load the workspace from disk. Missing files yield empty lists."""
    root = _workspace_root()

    playlists: list[Playlist] = []
    pl_dir = root / "playlists"
    if pl_dir.exists():
        for f in sorted(pl_dir.glob("*.json")):
            playlists.append(_playlist_from_dict(_read_json(f)))

    liked: list[PlaylistTrack] = []
    ls_path = root / "liked_songs.json"
    if ls_path.exists():
        liked = [_playlist_track_from_dict(d) for d in _read_json(ls_path)]

    albums: list[SavedAlbum] = []
    sa_path = root / "saved_albums.json"
    if sa_path.exists():
        albums = [_saved_album_from_dict(d) for d in _read_json(sa_path)]

    artists: list[FollowedArtist] = []
    fa_path = root / "followed_artists.json"
    if fa_path.exists():
        artists = [_followed_artist_from_dict(d) for d in _read_json(fa_path)]

    meta_path = root / "workspace_meta.json"
    exported_at = None
    last_pull_provider = None
    if meta_path.exists():
        meta = _read_json(meta_path)
        exported_at = _dt_from_str(meta.get("exported_at"))
        last_pull_provider = meta.get("last_pull_provider")

    log.info(
        "Workspace loaded: %d playlists, %d liked songs, %d albums, %d artists ← %s",
        len(playlists), len(liked), len(albums), len(artists), root,
    )
    return Library(
        last_pull_provider=last_pull_provider,
        exported_at=exported_at,
        playlists=playlists,
        liked_songs=liked,
        saved_albums=albums,
        followed_artists=artists,
    )
