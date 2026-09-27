"""Local library backups under ``<project>/backups/<source>/<timestamp>/``.

``source`` is ``local`` for copies of the work folder, or the provider id for
Backup runs from a service view. Only folders holding a saved library
(``workspace_meta.json``) count as backups.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from common import config
from common.log import get_logger

log = get_logger(__name__)

STAMP_FORMAT = "%Y-%m-%d-%H-%M"
LOCAL_SOURCE = "local"

LIBRARY_FILES = ("liked_songs.json", "saved_albums.json", "followed_artists.json", "workspace_meta.json")
LIBRARY_DIR = "playlists"
CREDENTIAL_FILES = ("spotify_token.json", "tidal_session.json")


@dataclass
class BackupInfo:
    path: Path
    source: str
    created: datetime | None
    playlists: int
    liked_songs: int
    saved_albums: int
    followed_artists: int
    last_pull_provider: str | None

    @property
    def when(self) -> str:
        return self.created.strftime("%Y-%m-%d %H:%M") if self.created else self.path.name


def backups_root() -> Path:
    return config.project_root() / "backups"


def _read_info(path: Path, source: str) -> BackupInfo | None:
    meta_path = path / "workspace_meta.json"
    if not meta_path.is_file():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        meta = {}
    try:
        created = datetime.strptime(path.name[:16], STAMP_FORMAT)
    except ValueError:
        created = None
    return BackupInfo(
        path=path,
        source=source,
        created=created,
        playlists=int(meta.get("playlist_count") or 0),
        liked_songs=int(meta.get("liked_song_count") or 0),
        saved_albums=int(meta.get("saved_album_count") or 0),
        followed_artists=int(meta.get("followed_artist_count") or 0),
        last_pull_provider=meta.get("last_pull_provider"),
    )


def list_backups(root: Path | None = None) -> list[BackupInfo]:
    """All backups, newest first."""
    base = root or backups_root()
    if not base.is_dir():
        return []
    out: list[BackupInfo] = []
    for source_dir in base.iterdir():
        if not source_dir.is_dir():
            continue
        for d in source_dir.iterdir():
            if d.is_dir():
                info = _read_info(d, source_dir.name)
                if info is not None:
                    out.append(info)
    out.sort(key=lambda b: (b.created or datetime.min, b.path.name), reverse=True)
    return out


def _free_dir(parent: Path, stamp: str) -> Path:
    dest = parent / stamp
    n = 2
    while dest.exists():
        dest = parent / f"{stamp}-{n}"
        n += 1
    return dest


def create_local_backup(*, work: Path | None = None, root: Path | None = None) -> Path:
    """Copy the work folder into ``backups/local/<timestamp>/`` (login tokens excluded)."""
    src = work or config.work_dir()
    dest = _free_dir((root or backups_root()) / LOCAL_SOURCE, datetime.now().strftime(STAMP_FORMAT))
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns(*CREDENTIAL_FILES))
    log.info("Local backup created → %s", dest)
    return dest


def load_backup(backup: Path, *, work: Path | None = None) -> None:
    """Replace the library in the work folder with the one in ``backup``.

    Only library files change; ``meta/`` (logins, push plans, decisions,
    removal records, caches) stays as it is.
    """
    dst = work or config.work_dir()
    if not (backup / "workspace_meta.json").is_file():
        raise ValueError(f"{backup} is not a saved library.")
    pl_dst = dst / LIBRARY_DIR
    if pl_dst.exists():
        shutil.rmtree(pl_dst)
    pl_src = backup / LIBRARY_DIR
    if pl_src.is_dir():
        shutil.copytree(pl_src, pl_dst)
    else:
        pl_dst.mkdir(parents=True)
    for name in LIBRARY_FILES:
        src = backup / name
        target = dst / name
        if src.is_file():
            shutil.copy2(src, target)
        elif target.exists():
            target.unlink()
    log.info("Loaded library from %s → %s", backup, dst)
