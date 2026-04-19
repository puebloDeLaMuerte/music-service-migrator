"""Backward compatibility: duplicate detection lives in :mod:`common.duplicate_groups`."""

from common.duplicate_groups import (
    Duplicate,
    duplicate_fingerprint,
    find_duplicates_across,
    find_duplicates_within,
    playlist_track_key,
)

__all__ = [
    "Duplicate",
    "duplicate_fingerprint",
    "find_duplicates_across",
    "find_duplicates_within",
    "playlist_track_key",
]
