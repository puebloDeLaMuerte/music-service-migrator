"""Local Files backups: create, list, load."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from common.local_backups import create_local_backup, list_backups, load_backup


def _library(root: Path, playlists: list[str], liked: int) -> None:
    (root / "playlists").mkdir(parents=True)
    for name in playlists:
        (root / "playlists" / f"{name}.json").write_text("{}", encoding="utf-8")
    (root / "liked_songs.json").write_text(json.dumps([{}] * liked), encoding="utf-8")
    (root / "workspace_meta.json").write_text(
        json.dumps({"playlist_count": len(playlists), "liked_song_count": liked}), encoding="utf-8"
    )


class LocalBackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.work, self.backups = base / "work", base / "backups"
        _library(self.work, ["A", "B"], 3)
        (self.work / "meta").mkdir()
        (self.work / "meta" / "spotify_token.json").write_text("secret", encoding="utf-8")
        (self.work / "meta" / "push_decisions.json").write_text("{}", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_create_copies_work_without_tokens(self) -> None:
        dest = create_local_backup(work=self.work, root=self.backups)
        self.assertTrue((dest / "playlists" / "A.json").is_file())
        self.assertTrue((dest / "meta" / "push_decisions.json").is_file())
        self.assertFalse((dest / "meta" / "spotify_token.json").exists())
        second = create_local_backup(work=self.work, root=self.backups)
        self.assertNotEqual(dest, second)

    def test_list_only_shows_saved_libraries(self) -> None:
        create_local_backup(work=self.work, root=self.backups)
        (self.backups / "spotify" / "junk").mkdir(parents=True)
        (self.backups / "spotify" / "__init__.py").write_text("", encoding="utf-8")
        found = list_backups(self.backups)
        self.assertEqual([(b.source, b.playlists, b.liked_songs) for b in found], [("local", 2, 3)])

    def test_load_replaces_library_and_keeps_meta(self) -> None:
        other = self.backups / "tidal" / "2026-01-01-10-00"
        _library(other, ["C"], 1)
        load_backup(other, work=self.work)
        self.assertEqual(sorted(p.name for p in (self.work / "playlists").iterdir()), ["C.json"])
        self.assertFalse((self.work / "saved_albums.json").exists())
        self.assertTrue((self.work / "meta" / "spotify_token.json").is_file())


if __name__ == "__main__":
    unittest.main()
