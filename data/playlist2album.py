"""Extract albums embedded in playlists.

Applies one extract operation at a time (saved albums + optional playlist trim).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from common import config
from common.log import get_logger
from common.models import Album, Playlist, PlaylistTrack, SavedAlbum
from common.store import (
    append_saved_albums,
    delete_playlist,
    save_playlist,
)
from spotify.album_detect import AlbumGroup

log = get_logger(__name__)


def build_trimmed_playlist(playlist: Playlist, album_groups: list[AlbumGroup]) -> Playlist:
    """Return a copy of the playlist with album tracks removed."""
    remove_ids: set[str] = set()
    for ag in album_groups:
        remove_ids |= ag.present_track_ids

    kept: list[PlaylistTrack] = []
    for pt in playlist.tracks:
        if pt.track.service_id not in remove_ids:
            pt_copy = PlaylistTrack(
                track=pt.track,
                position=len(kept),
                added_at=pt.added_at,
                added_by=pt.added_by,
            )
            kept.append(pt_copy)

    return Playlist(
        name=playlist.name,
        description=playlist.description,
        owner=playlist.owner,
        collaborative=playlist.collaborative,
        public=playlist.public,
        snapshot_id=playlist.snapshot_id,
        images=playlist.images,
        tracks=kept,
        service_id=playlist.service_id,
        service_url=playlist.service_url,
        uri=playlist.uri,
        service=playlist.service,
    )


def _album_from_playlist_tracks(
    playlist: Playlist,
    ag: AlbumGroup,
) -> Album:
    """Reconstruct an Album model from the tracks present in the playlist."""
    tracks_in_album = []
    album_template: Album | None = None
    for pt in playlist.tracks:
        if pt.track.service_id in ag.present_track_ids:
            tracks_in_album.append(pt.track)
            if album_template is None and pt.track.album:
                album_template = pt.track.album

    album = Album(
        name=ag.album_name,
        artists=album_template.artists if album_template else [],
        album_type=ag.album_type or (album_template.album_type if album_template else None),
        release_date=album_template.release_date if album_template else None,
        release_date_precision=album_template.release_date_precision if album_template else None,
        total_tracks=ag.album_total_tracks,
        tracks=sorted(
            tracks_in_album,
            key=lambda t: (t.disc_number or 1, t.track_number or 0),
        ),
        images=album_template.images if album_template else [],
        genres=album_template.genres if album_template else [],
        copyrights=album_template.copyrights if album_template else [],
        upc=album_template.upc if album_template else None,
        service_id=ag.album_id,
        service_url=ag.album_url or (album_template.service_url if album_template else None),
        uri=album_template.uri if album_template else None,
        service=album_template.service if album_template else None,
    )
    return album


def _append_log(service: str, entry: dict) -> None:
    log_path = config.output_dir() / service / "playlist2album_log.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if log_path.exists():
        data = json.loads(log_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
        ops = data.get("operations")
        if not isinstance(ops, list):
            ops = []
    else:
        data = {}
        ops = []
    ops.append(entry)
    data["operations"] = ops
    data["last_updated"] = datetime.now(timezone.utc).isoformat()
    log_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("playlist2album log updated: %s", log_path)


@dataclass
class ApplyExtractResult:
    """Outcome of a single extract operation."""

    albums_added: int
    playlist_modified: bool
    playlist_deleted: bool
    detail: dict


def apply_extract_once(
    playlist: Playlist,
    album_groups: list[AlbumGroup],
    *,
    remove_from_playlist: bool,
    keep_remaining_in_playlist_file: bool = True,
    service: str = "spotify",
) -> ApplyExtractResult:
    """Save album(s) to saved_albums; optionally remove their tracks from the playlist file.

    Args:
        playlist: Current playlist model (from disk).
        album_groups: Subset (or all) of detected groups to extract.
        remove_from_playlist: If True, remove those tracks from the playlist JSON;
            if False, only append to saved_albums (extract+keep).
        keep_remaining_in_playlist_file: When True, save trimmed playlist if tracks remain;
            when False, delete the playlist file even if tracks would remain (user chose
            "discard" in leftovers flow).
        service: Output service folder name.
    """
    if not album_groups:
        raise ValueError("album_groups must not be empty")

    now = datetime.now(timezone.utc)
    albums_to_save = [
        SavedAlbum(
            album=_album_from_playlist_tracks(playlist, ag),
            saved_at=now,
        )
        for ag in album_groups
    ]
    added = append_saved_albums(albums_to_save, service)

    playlist_modified = False
    playlist_deleted = False

    if not remove_from_playlist:
        detail = {
            "playlist": playlist.name,
            "albums_extracted": [ag.album_name for ag in album_groups],
            "albums_added_to_library": added,
            "playlist_outcome": "unchanged (extract+keep)",
        }
        _append_log(service, {"at": now.isoformat(), **detail})
        return ApplyExtractResult(
            albums_added=added,
            playlist_modified=False,
            playlist_deleted=False,
            detail=detail,
        )

    trimmed = build_trimmed_playlist(playlist, album_groups)

    if trimmed.track_count == 0:
        delete_playlist(playlist.name, service)
        playlist_deleted = True
        outcome = "deleted (empty after trim)"
    elif keep_remaining_in_playlist_file:
        save_playlist(trimmed, service)
        playlist_modified = True
        outcome = f"trimmed to {trimmed.track_count} tracks"
    else:
        delete_playlist(playlist.name, service)
        playlist_deleted = True
        outcome = "deleted (discarded remaining tracks)"

    detail = {
        "playlist": playlist.name,
        "albums_extracted": [ag.album_name for ag in album_groups],
        "albums_added_to_library": added,
        "playlist_outcome": outcome,
    }
    _append_log(service, {"at": now.isoformat(), **detail})

    return ApplyExtractResult(
        albums_added=added,
        playlist_modified=playlist_modified,
        playlist_deleted=playlist_deleted,
        detail=detail,
    )
