"""Resolve local tracks, albums and artists to target-catalog ids.

Escalation per item, stopping at the first step that settles it:

1. user decision from Inspect Push Plan (a pick, or exclude)
2. resolution cache from earlier dry-runs
3. the local row's own id, when it came from the target provider — kept only
   if the catalog entry still matches the name; otherwise dropped silently
4. an entry already in the target library with the same title and artist
5. ISRC (tracks) / UPC (albums) lookup
6. narrow catalog search, then broad catalog search

Only when every step finds nothing is the item reported as unavailable.
"""

from __future__ import annotations

from collections import Counter
from typing import Iterable

from common.models import Album, Artist, Track
from common.push.backend import PushBackend
from common.push.identity import album_key, album_label, artist_key, track_key, track_label
from common.push.matching import (
    Decision,
    Matcher,
    Scored,
    decide,
    display_album,
    display_track,
)
from common.push.models import (
    CatalogAlbum,
    CatalogArtist,
    CatalogTrack,
    PlanItem,
    RemoteSnapshot,
)
from common.push.resolution_cache import (
    EXCLUDE,
    ResolutionCache,
    decision_display,
    decision_for,
)


def _catalog_track_from_local(t: Track) -> CatalogTrack | None:
    if not t.service_id:
        return None
    return CatalogTrack(
        id=t.service_id,
        title=t.name,
        artists=[a.name for a in t.artists],
        artist_ids=[a.service_id or "" for a in t.artists],
        album=t.album.name if t.album else None,
        duration_ms=t.duration_ms,
        isrc=t.isrc,
    )


def _catalog_album_from_local(a: Album) -> CatalogAlbum | None:
    if not a.service_id:
        return None
    return CatalogAlbum(
        id=a.service_id,
        title=a.name,
        artists=[x.name for x in a.artists],
        artist_ids=[x.service_id or "" for x in a.artists],
        year=a.release_date,
        total_tracks=a.total_tracks,
    )


def _unique_by_id(items: Iterable) -> list:
    seen: set[str] = set()
    out = []
    for c in items:
        if c.id and c.id not in seen:
            seen.add(c.id)
            out.append(c)
    return out


class Resolver:
    def __init__(
        self,
        backend: PushBackend,
        matcher: Matcher,
        snapshot: RemoteSnapshot,
        cache: ResolutionCache,
        decisions: dict,
    ) -> None:
        self.backend = backend
        self.provider = backend.provider_id
        self.m = matcher
        self.cache = cache
        self.decisions = decisions
        self._artist_hints: dict[str, Counter[str]] = {}
        self._index_snapshot(snapshot)

    # ── Snapshot indexes ───────────────────────────────────────────

    def _index_snapshot(self, snap: RemoteSnapshot) -> None:
        lib = snap.library
        self.snap_track_by_id: dict[str, CatalogTrack] = {}
        self.snap_track_by_identity: dict[str, CatalogTrack] = {}
        tracks: list[Track] = [pt.track for pt in lib.liked_songs]
        for pl in lib.playlists:
            tracks.extend(pt.track for pt in pl.tracks)
        for sa in lib.saved_albums:
            tracks.extend(sa.album.tracks)
        for t in tracks:
            ct = _catalog_track_from_local(t)
            if ct is None:
                continue
            self.snap_track_by_id.setdefault(ct.id, ct)
            self.snap_track_by_identity.setdefault(
                self.m.track_identity(ct.title, ct.artists), ct
            )
            self._hint_artists(ct.artists, ct.artist_ids)

        self.snap_album_by_id: dict[str, CatalogAlbum] = {}
        self.snap_album_by_identity: dict[str, CatalogAlbum] = {}
        for sa in lib.saved_albums:
            ca = _catalog_album_from_local(sa.album)
            if ca is None:
                continue
            self.snap_album_by_id.setdefault(ca.id, ca)
            self.snap_album_by_identity.setdefault(
                self.m.track_identity(ca.title, ca.artists), ca
            )

        self.snap_artist_by_id: dict[str, CatalogArtist] = {}
        self.snap_artist_by_name: dict[str, CatalogArtist] = {}
        for fa in lib.followed_artists:
            if not fa.artist.service_id:
                continue
            ca = CatalogArtist(id=fa.artist.service_id, name=fa.artist.name)
            self.snap_artist_by_id.setdefault(ca.id, ca)
            self.snap_artist_by_name.setdefault(self.m.norm(ca.name), ca)

    def _hint_artists(self, names: list[str], ids: list[str]) -> None:
        for name, aid in zip(names, ids):
            if name and aid:
                self._artist_hints.setdefault(self.m.norm(name), Counter())[aid] += 1

    # ── Shared helpers ─────────────────────────────────────────────

    def _pre_checks(self, kind: str, key: str, label: str) -> PlanItem | None:
        choice = decision_for(self.decisions, self.provider, kind, key)
        if choice == EXCLUDE:
            return PlanItem(kind, key, label, "excluded", message="Excluded by you.")
        if choice:
            shown = decision_display(self.decisions, self.provider, kind, key)
            return PlanItem(
                kind, key, label, "resolved", choice, "your_choice", 1.0,
                message=f"Your pick: {shown}" if shown else "Your pick.",
            )
        hit = self.cache.get(kind, key)
        if hit:
            return PlanItem(
                kind, key, label, "resolved", hit["target_id"], "cache",
                float(hit.get("confidence") or 1.0),
            )
        return None

    def _settle(
        self, kind: str, key: str, label: str, decision: Decision, method: str
    ) -> PlanItem | None:
        if decision.status == "resolved" and decision.pick:
            self.cache.put(kind, key, decision.pick.ref, method, decision.pick.score)
            return PlanItem(
                kind, key, label, "resolved", decision.pick.ref, method, decision.pick.score
            )
        if decision.status == "ambiguous":
            return PlanItem(
                kind, key, label, "ambiguous",
                candidates=decision.candidates or [],
                message="Several possible matches — pick one or exclude.",
            )
        return None

    # ── Tracks ─────────────────────────────────────────────────────

    def _scored_tracks(self, local: Track, cands: list[CatalogTrack]) -> list[Scored]:
        out = []
        for c in _unique_by_id(cands):
            score, conflict = self.m.score_track(local, c)
            out.append(
                Scored(
                    ref=c.id,
                    display=display_track(c),
                    score=score,
                    conflict=conflict,
                    identity=self.m.track_identity(c.title, c.artists),
                )
            )
        return out

    def _remember_track(self, c: CatalogTrack | None) -> None:
        if c is not None:
            self._hint_artists(c.artists, c.artist_ids)

    def resolve_tracks(self, tracks: Iterable[Track]) -> dict[str, PlanItem]:
        items: dict[str, PlanItem] = {}
        pending: list[Track] = []
        seen: set[str] = set()
        for t in tracks:
            key = track_key(t)
            if key in seen:
                continue
            seen.add(key)
            label = track_label(t)
            if t.is_local:
                items[key] = PlanItem(
                    "track", key, label, "unsupported",
                    message="Local file — streaming services can't hold it.",
                )
                continue
            if not (t.name or "").strip():
                items[key] = PlanItem("track", key, label, "unavailable", message="No title.")
                continue
            pre = self._pre_checks("track", key, label)
            if pre is not None:
                items[key] = pre
                continue
            pending.append(t)

        missing_ids = [
            t.service_id
            for t in pending
            if t.service == self.provider
            and t.service_id
            and t.service_id not in self.snap_track_by_id
        ]
        looked = self.backend.lookup_tracks(missing_ids) if missing_ids else {}

        for t in pending:
            items[track_key(t)] = self._resolve_one_track(t, looked)
        return items

    def _resolve_one_track(self, t: Track, looked: dict[str, CatalogTrack]) -> PlanItem:
        key, label = track_key(t), track_label(t)
        if t.service == self.provider and t.service_id:
            c = self.snap_track_by_id.get(t.service_id) or looked.get(t.service_id)
            if c is not None and self.m.score_track(t, c)[0] >= self.m.floor:
                self._remember_track(c)
                return PlanItem("track", key, label, "resolved", c.id, "own_id", 1.0)

        artist_names = [a.name for a in t.artists]
        c = self.snap_track_by_identity.get(self.m.track_identity(t.name, artist_names))
        if c is not None:
            return PlanItem("track", key, label, "resolved", c.id, "in_library", 1.0)

        if t.isrc:
            hits = self.backend.tracks_by_isrc(t.isrc)
            item = self._settle(
                "track", key, label, decide(self.m, self._scored_tracks(t, hits), trust_all=True),
                "isrc",
            )
            if item is not None:
                self._remember_track(next((h for h in hits if h.id == item.target_id), None))
                return item

        primary = artist_names[0] if artist_names else ""
        album = t.album.name if t.album else None
        for narrow, method in ((True, "search"), (False, "broad_search")):
            hits = self.backend.search_tracks(t.name, primary, album, narrow=narrow)
            item = self._settle("track", key, label, decide(self.m, self._scored_tracks(t, hits)), method)
            if item is not None:
                if item.status == "resolved":
                    self._remember_track(next((h for h in hits if h.id == item.target_id), None))
                return item

        return PlanItem(
            "track", key, label, "unavailable",
            message=f"No match found on {self.provider.capitalize()}.",
        )

    # ── Albums ─────────────────────────────────────────────────────

    def _scored_albums(self, local: Album, cands: list[CatalogAlbum]) -> list[Scored]:
        out = []
        for c in _unique_by_id(cands):
            score, conflict = self.m.score_album(local, c)
            out.append(
                Scored(
                    ref=c.id,
                    display=display_album(c),
                    score=score,
                    conflict=conflict,
                    identity=self.m.track_identity(c.title, c.artists),
                )
            )
        return out

    def resolve_albums(self, albums: Iterable[Album]) -> dict[str, PlanItem]:
        items: dict[str, PlanItem] = {}
        for a in albums:
            key = album_key(a)
            if key in items:
                continue
            items[key] = self._resolve_one_album(a)
        return items

    def _resolve_one_album(self, a: Album) -> PlanItem:
        key, label = album_key(a), album_label(a)
        if not (a.name or "").strip():
            return PlanItem("album", key, label, "unavailable", message="No title.")
        pre = self._pre_checks("album", key, label)
        if pre is not None:
            return pre
        if a.service == self.provider and a.service_id:
            c = self.snap_album_by_id.get(a.service_id)
            if c is None:
                c = self.backend.lookup_albums([a.service_id]).get(a.service_id)
            if c is not None and self.m.score_album(a, c)[0] >= self.m.floor:
                return PlanItem("album", key, label, "resolved", c.id, "own_id", 1.0)
        artist_names = [x.name for x in a.artists]
        c = self.snap_album_by_identity.get(self.m.track_identity(a.name, artist_names))
        if c is not None:
            return PlanItem("album", key, label, "resolved", c.id, "in_library", 1.0)
        if a.upc:
            hits = self.backend.albums_by_upc(a.upc)
            item = self._settle(
                "album", key, label, decide(self.m, self._scored_albums(a, hits), trust_all=True),
                "upc",
            )
            if item is not None:
                return item
        primary = artist_names[0] if artist_names else ""
        for narrow, method in ((True, "search"), (False, "broad_search")):
            hits = self.backend.search_albums(a.name, primary, narrow=narrow)
            item = self._settle("album", key, label, decide(self.m, self._scored_albums(a, hits)), method)
            if item is not None:
                return item
        return PlanItem(
            "album", key, label, "unavailable",
            message=f"No match found on {self.provider.capitalize()}.",
        )

    # ── Artists ────────────────────────────────────────────────────

    def resolve_artists(self, artists: Iterable[Artist]) -> dict[str, PlanItem]:
        items: dict[str, PlanItem] = {}
        for a in artists:
            key = artist_key(a)
            if key in items:
                continue
            items[key] = self._resolve_one_artist(a)
        return items

    def _resolve_one_artist(self, a: Artist) -> PlanItem:
        key, label = artist_key(a), a.name
        if not (a.name or "").strip():
            return PlanItem("artist", key, label, "unavailable", message="No name.")
        pre = self._pre_checks("artist", key, label)
        if pre is not None:
            return pre
        name = self.m.norm(a.name)
        if a.service == self.provider and a.service_id:
            c = self.snap_artist_by_id.get(a.service_id)
            if c is None:
                c = self.backend.lookup_artists([a.service_id]).get(a.service_id)
            if c is not None and self.m.score_artist(a.name, c)[0] >= self.m.floor:
                return PlanItem("artist", key, label, "resolved", c.id, "own_id", 1.0)
        c = self.snap_artist_by_name.get(name)
        if c is not None:
            return PlanItem("artist", key, label, "resolved", c.id, "in_library", 1.0)
        hint = self._artist_hints.get(name)
        if hint:
            return PlanItem("artist", key, label, "resolved", hint.most_common(1)[0][0], "via_tracks", 1.0)
        hits = _unique_by_id(self.backend.search_artists(a.name))
        scored = []
        for c in hits:
            score, conflict = self.m.score_artist(a.name, c)
            scored.append(Scored(ref=c.id, display=c.name, score=score, conflict=conflict, identity=c.id))
        item = self._settle("artist", key, label, decide(self.m, scored), "search")
        if item is not None:
            return item
        return PlanItem(
            "artist", key, label, "unavailable",
            message=f"No match found on {self.provider.capitalize()}.",
        )
