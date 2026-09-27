"""Name-based identity keys for local entities (never provider ids).

Keys are what a user would recognise — title and artists — so the same song
resolves once no matter which playlists it appears in.
"""

from __future__ import annotations

import re

from common.models import Album, Artist, Track


def _clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().casefold())


def _artists_part(artists: list[Artist]) -> str:
    return ", ".join(sorted(_clean(a.name) for a in artists))


def track_key(track: Track) -> str:
    return f"{_clean(track.name)}|{_artists_part(track.artists)}"


def album_key(album: Album) -> str:
    return f"{_clean(album.name)}|{_artists_part(album.artists)}"


def artist_key(artist: Artist) -> str:
    return _clean(artist.name)


def playlist_key(name: str) -> str:
    return _clean(name)


def artists_label(artists: list[Artist] | list[str]) -> str:
    names = [a if isinstance(a, str) else a.name for a in artists]
    return ", ".join(n for n in names if n)


def track_label(track: Track) -> str:
    who = artists_label(track.artists)
    return f"{track.name} — {who}" if who else track.name


def album_label(album: Album) -> str:
    who = artists_label(album.artists)
    return f"{album.name} — {who}" if who else album.name
