"""Configurable name matching between local entities and target catalog entries.

Rules live in ``<work_dir>/meta/push_matching.json`` (created with defaults on
first use):

- ``ignore_patterns`` — regexes stripped before comparing, so e.g. a local
  "Song" and a catalog "Song (2009 Remaster)" count as the same.
- ``prompt_patterns`` — regexes whose presence must agree on both sides; a
  "Song" vs "Song - Live" pair is never auto-accepted and becomes a decision
  item for the user instead.
- ``thresholds`` — ``accept`` (auto-resolve), ``candidate_floor`` (worth
  showing the user), ``ambiguity_margin`` (how far the best match must lead).
"""

from __future__ import annotations

import copy
import json
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Literal

from common.models import Album, Track
from common.push.models import Candidate, CatalogAlbum, CatalogArtist, CatalogTrack
from common.store import meta_dir

MATCHING_SCHEMA_VERSION = 1

DEFAULT_MATCHING: dict[str, Any] = {
    "schema_version": MATCHING_SCHEMA_VERSION,
    "thresholds": {
        "accept": 0.88,
        "candidate_floor": 0.6,
        "ambiguity_margin": 0.06,
    },
    "duration_tolerance_seconds": 3,
    "weights": {"title": 0.5, "artist": 0.35, "album": 0.1, "duration": 0.05},
    "ignore_patterns": [
        r"\s*[\(\[][^\)\]]*\bremaster(ed)?\b[^\)\]]*[\)\]]",
        r"\s+-\s+(\d{4}\s+)?(digital(ly)?\s+)?remaster(ed)?(\s+\d{4})?(\s+version)?\s*$",
        r"\s*[\(\[](feat\.?|ft\.?|featuring|with)\s[^\)\]]*[\)\]]",
        r"\s*[\(\[][^\)\]]*\b(deluxe|expanded|anniversary|bonus track)\b[^\)\]]*[\)\]]",
        r"\s+-\s+(single|ep)\s*$",
    ],
    "prompt_patterns": [
        r"\blive\b",
        r"\bremix(ed)?\b",
        r"\bacoustic\b",
        r"\binstrumental\b",
        r"\bdemo\b",
        r"\bkaraoke\b",
        r"\bradio edit\b",
        r"\bextended\b",
    ],
}


def matching_config_path(workspace_root: Path | None = None) -> Path:
    if workspace_root is not None:
        return Path(workspace_root) / "meta" / "push_matching.json"
    return meta_dir() / "push_matching.json"


def _merge_defaults(data: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(DEFAULT_MATCHING)
    for key, val in data.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key].update(val)
        else:
            out[key] = val
    return out


def load_matching_config(*, workspace_root: Path | None = None) -> dict[str, Any]:
    """Load rules, writing the defaults to disk if the file does not exist yet."""
    path = matching_config_path(workspace_root)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(DEFAULT_MATCHING, indent=2), encoding="utf-8")
        return copy.deepcopy(DEFAULT_MATCHING)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return copy.deepcopy(DEFAULT_MATCHING)
    return _merge_defaults(data if isinstance(data, dict) else {})


@dataclass
class Matcher:
    """Compiled matching rules."""

    accept: float
    floor: float
    margin: float
    duration_tolerance_ms: int
    weights: dict[str, float]
    ignore: list[re.Pattern[str]]
    prompt: list[re.Pattern[str]]

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "Matcher":
        th = cfg.get("thresholds", {})
        return cls(
            accept=float(th.get("accept", 0.88)),
            floor=float(th.get("candidate_floor", 0.6)),
            margin=float(th.get("ambiguity_margin", 0.06)),
            duration_tolerance_ms=int(float(cfg.get("duration_tolerance_seconds", 3)) * 1000),
            weights={k: float(v) for k, v in (cfg.get("weights") or {}).items()},
            ignore=[re.compile(p, re.IGNORECASE) for p in cfg.get("ignore_patterns", [])],
            prompt=[re.compile(p, re.IGNORECASE) for p in cfg.get("prompt_patterns", [])],
        )

    # ── Normalisation ──────────────────────────────────────────────

    def norm(self, s: str | None) -> str:
        text = s or ""
        for pat in self.ignore:
            text = pat.sub("", text)
        text = unicodedata.normalize("NFKD", text)
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        text = text.casefold().replace("&", " and ")
        text = re.sub(r"[^\w\s]", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    def prompt_conflict(self, local_text: str, cand_text: str) -> bool:
        return any(
            bool(p.search(local_text or "")) != bool(p.search(cand_text or ""))
            for p in self.prompt
        )

    @staticmethod
    def _sim(a: str, b: str) -> float:
        if not a or not b:
            return 0.0
        if a == b:
            return 1.0
        return SequenceMatcher(None, a, b).ratio()

    def _artist_sim(self, local: list[str], cand: list[str]) -> float | None:
        if not local or not cand:
            return None
        primary = self.norm(local[0])
        return max(self._sim(primary, self.norm(c)) for c in cand)

    def _duration_sim(self, a: int | None, b: int | None) -> float | None:
        if not a or not b:
            return None
        delta = abs(a - b)
        if delta <= self.duration_tolerance_ms:
            return 1.0
        return max(0.0, 1.0 - (delta - self.duration_tolerance_ms) / 30000)

    def _weighted(self, parts: dict[str, float | None]) -> float:
        num = den = 0.0
        for name, val in parts.items():
            if val is None:
                continue
            w = self.weights.get(name, 0.0)
            num += w * val
            den += w
        return num / den if den else 0.0

    # ── Scoring ────────────────────────────────────────────────────

    def score_track(self, local: Track, cand: CatalogTrack) -> tuple[float, bool]:
        local_album = local.album.name if local.album else None
        score = self._weighted(
            {
                "title": self._sim(self.norm(local.name), self.norm(cand.title)),
                "artist": self._artist_sim([a.name for a in local.artists], cand.artists),
                "album": (
                    self._sim(self.norm(local_album), self.norm(cand.album))
                    if local_album and cand.album
                    else None
                ),
                "duration": self._duration_sim(local.duration_ms, cand.duration_ms),
            }
        )
        conflict = self.prompt_conflict(
            f"{local.name} {local_album or ''}", f"{cand.title} {cand.album or ''}"
        )
        return score, conflict

    def score_album(self, local: Album, cand: CatalogAlbum) -> tuple[float, bool]:
        score = self._weighted(
            {
                "title": self._sim(self.norm(local.name), self.norm(cand.title)),
                "artist": self._artist_sim([a.name for a in local.artists], cand.artists),
            }
        )
        return score, self.prompt_conflict(local.name, cand.title)

    def score_artist(self, local_name: str, cand: CatalogArtist) -> tuple[float, bool]:
        return self._sim(self.norm(local_name), self.norm(cand.name)), False

    def track_identity(self, title: str, artists: list[str]) -> str:
        primary = self.norm(artists[0]) if artists else ""
        return f"{self.norm(title)}|{primary}"


DecisionStatus = Literal["resolved", "ambiguous", "none"]


@dataclass
class Scored:
    ref: str
    display: str
    score: float
    conflict: bool
    identity: str


@dataclass
class Decision:
    status: DecisionStatus
    pick: Scored | None = None
    candidates: list[Candidate] | None = None


def decide(m: Matcher, scored: list[Scored], *, trust_all: bool = False) -> Decision:
    """Turn scored candidates into resolved / ambiguous / none.

    ``trust_all`` is for lookups that already guarantee the same recording
    (ISRC): the best acceptable candidate wins without an ambiguity check.
    """
    if not scored:
        return Decision("none")
    ranked = sorted(scored, key=lambda s: s.score, reverse=True)
    if trust_all and ranked[0].score >= m.floor:
        return Decision("resolved", pick=ranked[0])
    clean = [s for s in ranked if not s.conflict]
    if clean and clean[0].score >= m.accept:
        best = clean[0]
        rivals = [
            s
            for s in clean[1:]
            if s.score > best.score - m.margin and s.identity != best.identity
        ]
        if not rivals:
            return Decision("resolved", pick=best)
    viable = [s for s in ranked if s.score >= m.floor][:6]
    if viable:
        return Decision(
            "ambiguous",
            candidates=[Candidate(ref=s.ref, display=s.display, score=s.score) for s in viable],
        )
    return Decision("none")


def _fmt_duration(ms: int | None) -> str:
    if not ms:
        return ""
    sec = ms // 1000
    return f"{sec // 60}:{sec % 60:02d}"


def display_track(c: CatalogTrack) -> str:
    parts = [f"{c.title} — {', '.join(c.artists)}" if c.artists else c.title]
    if c.album:
        parts.append(c.album)
    dur = _fmt_duration(c.duration_ms)
    if dur:
        parts.append(dur)
    return " · ".join(parts)


def display_album(c: CatalogAlbum) -> str:
    parts = [f"{c.title} — {', '.join(c.artists)}" if c.artists else c.title]
    if c.year:
        parts.append(str(c.year)[:4])
    if c.total_tracks:
        parts.append(f"{c.total_tracks} tracks")
    return " · ".join(parts)
