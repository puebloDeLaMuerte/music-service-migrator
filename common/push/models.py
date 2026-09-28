"""Push modes, catalog records returned by provider backends, and plan items."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from common.models import Library

PUSH_PLAN_SCHEMA_VERSION = 2


class PushMode(str, Enum):
    """How local library state is reconciled onto one target provider."""

    ADD = "push_add"
    DELETE = "push_delete"
    WIPE = "wipe_push"


REMOTE_WIPE_KIND = "remote_wipe"
"""Plan kind for the standalone remote wipe action (not a push mode)."""


@dataclass
class CatalogTrack:
    id: str
    title: str
    artists: list[str] = field(default_factory=list)
    artist_ids: list[str] = field(default_factory=list)
    album: str | None = None
    duration_ms: int | None = None
    isrc: str | None = None


@dataclass
class CatalogAlbum:
    id: str
    title: str
    artists: list[str] = field(default_factory=list)
    artist_ids: list[str] = field(default_factory=list)
    year: str | None = None
    total_tracks: int | None = None


@dataclass
class CatalogArtist:
    id: str
    name: str
    albums: list[str] = field(default_factory=list)
    """A few releases ("Title (2023)"), filled only when telling namesakes apart."""
    url: str | None = None
    """Public web page, so the user can look the artist up."""


@dataclass
class RemoteSnapshot:
    """Current library on the push target (read before planning).

    ``library`` uses common models whose ``service_id`` values are target ids.
    ``editable_playlist_ids`` holds playlists the account may modify (owned or
    collaborative); everything else in ``library.playlists`` is followed only.
    """

    library: Library
    editable_playlist_ids: set[str] = field(default_factory=set)


ItemKind = Literal["track", "album", "artist", "playlist"]

ItemStatus = Literal[
    "resolved",
    "ambiguous",
    "unavailable",
    "unsupported",
    "excluded",
]


@dataclass
class Candidate:
    """One possible catalog match. The user sees ``display``, ``detail`` and ``url``."""

    ref: str
    display: str
    score: float
    detail: str | None = None
    """Facts that tell this candidate apart from the others (e.g. its releases)."""
    url: str | None = None


@dataclass
class PlanItem:
    """Resolution outcome for one local entity against the push target."""

    kind: ItemKind
    key: str
    label: str
    status: ItemStatus
    target_id: str | None = None
    method: str | None = None
    confidence: float | None = None
    candidates: list[Candidate] = field(default_factory=list)
    message: str | None = None

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "key": self.key,
            "label": self.label,
            "status": self.status,
            "target_id": self.target_id,
            "method": self.method,
            "confidence": self.confidence,
            "candidates": [
                {
                    "ref": c.ref,
                    "display": c.display,
                    "score": round(c.score, 3),
                    "detail": c.detail,
                    "url": c.url,
                }
                for c in self.candidates
            ],
            "message": self.message,
        }
