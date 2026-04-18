"""Extract albums embedded in playlists.

Business logic for the interactive playlist-to-album workflow.  The CLI layer
(cli.py) handles prompts; this module owns the data transformations and disk
writes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from common import config
from common.log import get_logger
from common.models import Album, Playlist, PlaylistTrack, SavedAlbum
from common.store import (
    append_saved_albums,
    delete_playlist,
    sanitise_filename,
    save_playlist,
)
from spotify.album_detect import AlbumGroup, PlaylistAnalysis

log = get_logger(__name__)


@dataclass
class Action:
    """One queued change for a single playlist."""

    playlist: Playlist
    analysis: PlaylistAnalysis
    album_groups: list[AlbumGroup]
    keep_leftovers: bool = True
    flag_missing: bool = False

    @property
    def playlist_name(self) -> str:
        return self.playlist.name

    @property
    def albums_to_extract(self) -> int:
        return len(self.album_groups)

    @property
    def tracks_to_remove(self) -> int:
        ids = set()
        for ag in self.album_groups:
            ids |= ag.present_track_ids
        return len(ids)

    @property
    def tracks_remaining(self) -> int:
        return self.playlist.track_count - self.tracks_to_remove


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


def apply_actions(actions: list[Action], service: str) -> dict:
    """Execute all queued actions against stored data on disk.

    Returns a summary dict suitable for writing as a log file.
    """
    now = datetime.now(timezone.utc)
    log_entries: list[dict] = []
    total_albums_added = 0
    total_playlists_modified = 0
    total_playlists_deleted = 0

    for action in actions:
        albums_to_save: list[SavedAlbum] = []
        missing_flags: list[dict] = []

        for ag in action.album_groups:
            album = _album_from_playlist_tracks(action.playlist, ag)
            albums_to_save.append(SavedAlbum(album=album, saved_at=now))

            if action.flag_missing and ag.missing_tracks:
                missing_flags.append({
                    "album": ag.album_name,
                    "album_id": ag.album_id,
                    "missing": ag.missing_tracks,
                })

        added = append_saved_albums(albums_to_save, service)
        total_albums_added += added

        if action.keep_leftovers and action.tracks_remaining > 0:
            trimmed = build_trimmed_playlist(action.playlist, action.album_groups)
            save_playlist(trimmed, service)
            total_playlists_modified += 1
            playlist_outcome = f"trimmed to {trimmed.track_count} tracks"
        else:
            delete_playlist(action.playlist.name, service)
            total_playlists_deleted += 1
            playlist_outcome = "deleted"

        entry = {
            "playlist": action.playlist_name,
            "albums_extracted": [ag.album_name for ag in action.album_groups],
            "albums_added_to_library": added,
            "playlist_outcome": playlist_outcome,
        }
        if missing_flags:
            entry["missing_tracks_flagged"] = missing_flags
        log_entries.append(entry)

    summary = {
        "applied_at": now.isoformat(),
        "actions_count": len(actions),
        "albums_added": total_albums_added,
        "playlists_modified": total_playlists_modified,
        "playlists_deleted": total_playlists_deleted,
        "details": log_entries,
    }

    log_path = config.output_dir() / service / "playlist2album_log.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    log.info("Action log written to %s", log_path)

    return summary
