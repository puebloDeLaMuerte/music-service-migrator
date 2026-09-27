"""Stable hash of everything a push plan depends on locally.

Covers Local Data, removal records, your plan decisions and the matching
config; when any of them changes, the stored plan is stale and Push Now
re-plans.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from common.models import Library
from common.push.matching import load_matching_config
from common.push.resolution_cache import load_decisions
from common.push.sync_intent import load_sync_intents


def _track(t) -> dict:
    return {
        "name": t.name,
        "artists": [a.name for a in t.artists],
        "album": t.album.name if t.album else None,
        "service": t.service,
        "service_id": t.service_id,
        "isrc": t.isrc,
    }


def _library_payload(library: Library) -> dict:
    playlists = [
        {
            "name": pl.name,
            "description": pl.description,
            "service": pl.service,
            "service_id": pl.service_id,
            "tracks": [_track(pt.track) for pt in pl.tracks],
        }
        for pl in sorted(library.playlists, key=lambda p: p.name.lower())
    ]
    return {
        "playlists": playlists,
        "liked_songs": [_track(pt.track) for pt in library.liked_songs],
        "saved_albums": [
            {
                "name": sa.album.name,
                "artists": [a.name for a in sa.album.artists],
                "service": sa.album.service,
                "service_id": sa.album.service_id,
                "upc": sa.album.upc,
            }
            for sa in library.saved_albums
        ],
        "followed_artists": [
            {"name": fa.artist.name, "service": fa.artist.service, "service_id": fa.artist.service_id}
            for fa in library.followed_artists
        ],
    }


def _hash(payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def local_fingerprint(library: Library, *, workspace_root: Path | None = None) -> str:
    """Local Data, removal records and matching rules — everything except your decisions."""
    intents = load_sync_intents(workspace_root=workspace_root)
    return _hash(
        {
            "library": _library_payload(library),
            "sync_intents": [
                {k: i.get(k) for k in ("entity_kind", "key", "playlist")} for i in intents["intents"]
            ],
            "matching": load_matching_config(workspace_root=workspace_root),
        }
    )


def library_fingerprint(library: Library, *, workspace_root: Path | None = None) -> str:
    """:func:`local_fingerprint` plus decisions. ``workspace_root`` is the work directory."""
    return _hash(
        {
            "local": local_fingerprint(library, workspace_root=workspace_root),
            "decisions": load_decisions(workspace_root=workspace_root),
        }
    )
