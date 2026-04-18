"""Apply duplicate resolutions to the on-disk Spotify library and persist ignore list."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from common import config
from common.log import get_logger
from common.models import Library, Playlist, PlaylistTrack
from common.store import load_library, save_playlist
from spotify.dedupe import Duplicate, duplicate_fingerprint, find_duplicates_across, playlist_track_key

log = get_logger(__name__)

SERVICE = "spotify"


def _dt_sort_key(dt: datetime | None) -> float:
    """Monotonic sort key for optional timestamps (naive treated as UTC)."""
    if dt is None:
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _ignored_path() -> Path:
    p = config.output_dir() / SERVICE / "dedupe_ignored.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load_ignored_keys() -> set[str]:
    path = _ignored_path()
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        keys = data.get("ignored_keys", [])
        return set(keys) if isinstance(keys, list) else set()
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        log.warning("Could not read dedupe ignore file: %s", exc)
        return set()


def add_ignored_key(key: str) -> None:
    keys = load_ignored_keys()
    keys.add(key)
    path = _ignored_path()
    path.write_text(
        json.dumps({"ignored_keys": sorted(keys)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("Recorded ignored duplicate fingerprint")


def filter_dupes(dupes: list[Duplicate], ignored: set[str]) -> list[Duplicate]:
    return [d for d in dupes if duplicate_fingerprint(d) not in ignored]


def _find_playlist(library: Library, name: str) -> Playlist | None:
    for pl in library.playlists:
        if pl.name == name:
            return pl
    return None


def _find_track_at_position(pl: Playlist, position: int) -> PlaylistTrack | None:
    pos = int(position) if position is not None else 0
    for pt in pl.tracks:
        if (pt.position or 0) == pos:
            return pt
    return None


def _find_track_by_fingerprint(pl: Playlist, fp: str, prefer_pos: int | None) -> PlaylistTrack | None:
    if prefer_pos is not None:
        pt = _find_track_at_position(pl, int(prefer_pos))
        if pt and playlist_track_key(pt) == fp:
            return pt
    for pt in pl.tracks:
        if playlist_track_key(pt) == fp:
            return pt
    return None


def _reindex_positions(pl: Playlist) -> None:
    for i, pt in enumerate(pl.tracks):
        pt.position = i


def _remove_matching_tracks(pl: Playlist, fp: str) -> bool:
    """Drop tracks matching ``fp``; return True if something was removed."""
    before = len(pl.tracks)
    pl.tracks = [pt for pt in pl.tracks if playlist_track_key(pt) != fp]
    if len(pl.tracks) != before:
        _reindex_positions(pl)
        return True
    return False


def apply_keep_only_in_playlist(
    library: Library, d: Duplicate, keep_playlist_name: str
) -> list[str]:
    """Keep the track only in ``keep_playlist_name``; remove from every other playlist."""
    fp = duplicate_fingerprint(d)
    changed: list[str] = []
    for pl in library.playlists:
        if pl.name == keep_playlist_name:
            continue
        if _remove_matching_tracks(pl, fp):
            changed.append(pl.name)
    return changed


def apply_remove_from_playlist(
    library: Library, d: Duplicate, remove_playlist_name: str
) -> list[str]:
    """Remove the track from ``remove_playlist_name`` only."""
    fp = duplicate_fingerprint(d)
    pl = _find_playlist(library, remove_playlist_name)
    if not pl:
        return []
    if _remove_matching_tracks(pl, fp):
        return [pl.name]
    return []


def _occurrence_meta(
    library: Library, d: Duplicate
) -> list[tuple[str, int, datetime | None]]:
    fp = duplicate_fingerprint(d)
    out: list[tuple[str, int, datetime | None]] = []
    for pl_name, pos in d.occurrences:
        pl = _find_playlist(library, pl_name)
        if not pl:
            continue
        pt = _find_track_by_fingerprint(pl, fp, pos)
        if not pt:
            continue
        out.append((pl_name, int(pos), pt.added_at))
    return out


def describe_keep_older(library: Library, d: Duplicate) -> tuple[str, str]:
    """Return (confirm body markup, playlist name to keep)."""
    meta = _occurrence_meta(library, d)
    if not meta:
        raise ValueError("Could not resolve this duplicate in the loaded library.")
    dated = [m for m in meta if m[2] is not None]
    if dated:
        winner = min(dated, key=lambda m: _dt_sort_key(m[2]))
        blurb = (
            "[bold]Keep older[/]\n\n"
            f"The track will stay only in [bold]{winner[0]}[/] (earliest [bold]added-at[/] "
            "in your export). It will be removed from the other playlist(s).\n\n"
            "Confirm?"
        )
        return blurb, winner[0]
    winner = min(meta, key=lambda m: (m[0], m[1]))
    blurb = (
        "[bold]Keep older[/]\n\n"
        "Your export has no [bold]added-at[/] times, so the app cannot tell which copy "
        "is older. It will keep the track only in [bold]"
        f"{winner[0]}[/] using a stable tie-break (name / position).\n\n"
        "Confirm?"
    )
    return blurb, winner[0]


def describe_keep_newer(library: Library, d: Duplicate) -> tuple[str, str]:
    """Return (confirm body markup, playlist name to keep)."""
    meta = _occurrence_meta(library, d)
    if not meta:
        raise ValueError("Could not resolve this duplicate in the loaded library.")
    dated = [m for m in meta if m[2] is not None]
    if dated:
        winner = max(dated, key=lambda m: _dt_sort_key(m[2]))
        blurb = (
            "[bold]Keep newer[/]\n\n"
            f"The track will stay only in [bold]{winner[0]}[/] (latest [bold]added-at[/]). "
            "It will be removed from the other playlist(s).\n\n"
            "Confirm?"
        )
        return blurb, winner[0]
    winner = max(meta, key=lambda m: (m[0], m[1]))
    blurb = (
        "[bold]Keep newer[/]\n\n"
        "No [bold]added-at[/] timestamps; keeping the track only in [bold]"
        f"{winner[0]}[/] using a tie-break (name / position).\n\n"
        "Confirm?"
    )
    return blurb, winner[0]


def finalize_keep_only_in(
    library: Library, d: Duplicate, keep_playlist_name: str
) -> str:
    """Remove the duplicate from all playlists except ``keep_playlist_name`` and save JSON."""
    changed = apply_keep_only_in_playlist(library, d, keep_playlist_name)
    persist_playlists(library, changed)
    return (
        f"Kept only in {keep_playlist_name}. "
        f"Removed from: {', '.join(changed) or '—'}"
    )


def persist_playlists(library: Library, names: list[str]) -> None:
    for name in names:
        pl = _find_playlist(library, name)
        if pl:
            save_playlist(pl, SERVICE)


def reload_and_find_dupes() -> tuple[Library, list[Duplicate]]:
    library = load_library(SERVICE)
    dupes = find_duplicates_across(library.playlists)
    dupes = filter_dupes(dupes, load_ignored_keys())
    return library, dupes
