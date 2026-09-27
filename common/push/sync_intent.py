"""Local removal records (tombstones) consumed by Push-delete.

A removal is local library maintenance and is never tied to a provider: it
records "this is no longer in the local library". Only at push time is it
interpreted against the one target provider being pushed to. Stored in
``<work_dir>/meta/sync_intent.json``.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from common.models import Album, Artist, Track
from common.push.identity import (
    album_key,
    album_label,
    artist_key,
    playlist_key,
    track_key,
    track_label,
)
from common.store import meta_dir

SYNC_INTENT_SCHEMA_VERSION = 2

EntityKind = Literal[
    "liked_track",
    "playlist_track",
    "saved_album",
    "followed_artist",
    "playlist",
]


def sync_intent_path(workspace_root: Path | None = None) -> Path:
    if workspace_root is not None:
        return Path(workspace_root) / "meta" / "sync_intent.json"
    return meta_dir() / "sync_intent.json"


def _empty() -> dict[str, Any]:
    return {"schema_version": SYNC_INTENT_SCHEMA_VERSION, "intents": []}


def _migrate(data: dict[str, Any]) -> dict[str, Any]:
    intents = []
    for row in data.get("intents", []):
        if not isinstance(row, dict):
            continue
        row = dict(row)
        row.pop("target_provider", None)
        if "key" not in row and "fingerprint" in row:
            row["key"] = row.pop("fingerprint")
        row.setdefault("detail", {})
        row.setdefault("playlist", row.pop("playlist_name", None))
        intents.append(row)
    return {"schema_version": SYNC_INTENT_SCHEMA_VERSION, "intents": intents}


def load_sync_intents(*, workspace_root: Path | None = None) -> dict[str, Any]:
    path = sync_intent_path(workspace_root)
    if not path.exists():
        return _empty()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    return _migrate(data)


def save_sync_intents(doc: dict[str, Any], *, workspace_root: Path | None = None) -> None:
    path = sync_intent_path(workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def _record(
    entries: list[tuple[EntityKind, str, str, dict[str, Any], str | None]],
    *,
    workspace_root: Path | None = None,
) -> None:
    if not entries:
        return
    doc = load_sync_intents(workspace_root=workspace_root)
    now = datetime.now(timezone.utc).isoformat()
    index = {(i["entity_kind"], i["key"], i.get("playlist")): i for i in doc["intents"]}
    for kind, key, label, detail, playlist in entries:
        existing = index.get((kind, key, playlist))
        if existing is not None:
            existing["created_at"] = now
            continue
        row = {
            "id": str(uuid.uuid4()),
            "entity_kind": kind,
            "action": "remove",
            "key": key,
            "label": label,
            "playlist": playlist,
            "detail": detail,
            "created_at": now,
        }
        doc["intents"].append(row)
        index[(kind, key, playlist)] = row
    save_sync_intents(doc, workspace_root=workspace_root)


def track_detail(track: Track) -> dict[str, Any]:
    return {
        "title": track.name,
        "artists": [a.name for a in track.artists],
        "album": track.album.name if track.album else None,
        "duration_ms": track.duration_ms,
        "isrc": track.isrc,
    }


def record_liked_removed(tracks: list[Track], *, workspace_root: Path | None = None) -> None:
    _record(
        [("liked_track", track_key(t), track_label(t), track_detail(t), None) for t in tracks],
        workspace_root=workspace_root,
    )


def record_playlist_tracks_removed(
    playlist_name: str, tracks: list[Track], *, workspace_root: Path | None = None
) -> None:
    _record(
        [
            ("playlist_track", track_key(t), track_label(t), track_detail(t), playlist_name)
            for t in tracks
        ],
        workspace_root=workspace_root,
    )


def record_album_removed(album: Album, *, workspace_root: Path | None = None) -> None:
    detail = {"title": album.name, "artists": [a.name for a in album.artists]}
    _record(
        [("saved_album", album_key(album), album_label(album), detail, None)],
        workspace_root=workspace_root,
    )


def record_artist_removed(artist: Artist, *, workspace_root: Path | None = None) -> None:
    _record(
        [("followed_artist", artist_key(artist), artist.name, {"name": artist.name}, None)],
        workspace_root=workspace_root,
    )


def record_playlist_removed(playlist_name: str, *, workspace_root: Path | None = None) -> None:
    _record(
        [("playlist", playlist_key(playlist_name), playlist_name, {"name": playlist_name}, None)],
        workspace_root=workspace_root,
    )
