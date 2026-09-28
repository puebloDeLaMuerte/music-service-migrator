"""Build push plans (dry-run) from Local Data and the target's current library.

A plan is a JSON document with every resolution outcome (``items``), a
per-playlist summary, human-readable warnings and the ordered ``operations``
Push Now executes. Planning only reads from the provider.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common.log import get_logger
from common.models import Album, Artist, Library, Track
from common.push.backend import PushBackend
from common.push.errors import PushError, PushErrorCode
from common.push.fingerprint import library_fingerprint, local_fingerprint
from common.push.identity import album_key, artist_key, playlist_key, track_key
from common.push.matching import Matcher, load_matching_config
from common.push.models import (
    PUSH_PLAN_SCHEMA_VERSION,
    REMOTE_WIPE_KIND,
    Candidate,
    CatalogTrack,
    PlanItem,
    PushMode,
    RemoteSnapshot,
)
from common.push.ordering import merge_order
from common.push.plan_store import load_latest_plan, save_plan
from common.push.resolution_cache import EXCLUDE, ResolutionCache, decision_for, load_decisions
from common.push.resolver import Resolver, _catalog_album_from_local
from common.push.sync_intent import load_sync_intents

log = get_logger(__name__)

SEED_TRACK = ("Resist", "Wipers")
"""Added to the liked songs after a standalone remote wipe."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _plan_hash(provider: str, kind: str, operations: list[dict]) -> str:
    blob = json.dumps([provider, kind, operations], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _track_from_detail(detail: dict) -> Track:
    return Track(
        name=detail.get("title") or "",
        artists=[Artist(name=n) for n in detail.get("artists") or []],
        album=Album(name=detail["album"]) if detail.get("album") else None,
        duration_ms=detail.get("duration_ms"),
        isrc=detail.get("isrc"),
    )


def _catalog(t: Track) -> CatalogTrack:
    return CatalogTrack(
        id=t.service_id or "",
        title=t.name,
        artists=[a.name for a in t.artists],
        album=t.album.name if t.album else None,
        duration_ms=t.duration_ms,
    )


class _PlanBuilder:
    def __init__(
        self,
        library: Library,
        backend: PushBackend,
        snapshot: RemoteSnapshot,
        matcher: Matcher,
        *,
        workspace_root: Path | None,
    ) -> None:
        self.library = library
        self.backend = backend
        self.provider = backend.provider_id
        self.title = self.provider.capitalize()
        self.snap = snapshot
        self.m = matcher
        self.root = workspace_root
        self.decisions = load_decisions(workspace_root=workspace_root)
        self.cache = ResolutionCache(self.provider, workspace_root=workspace_root)
        self.resolver = Resolver(backend, matcher, snapshot, self.cache, self.decisions)
        self.items: dict[tuple[str, str], PlanItem] = {}
        self.ops: list[dict[str, Any]] = []
        self.warnings: list[str] = []
        self.playlists: list[dict[str, Any]] = []

    # ── Resolution ─────────────────────────────────────────────────

    def resolve_local(self) -> None:
        tracks = [pt.track for pl in self.library.playlists for pt in pl.tracks]
        tracks += [pt.track for pt in self.library.liked_songs]
        for key, item in self.resolver.resolve_tracks(tracks).items():
            self.items[("track", key)] = item
        albums = [sa.album for sa in self.library.saved_albums]
        for key, item in self.resolver.resolve_albums(albums).items():
            self.items[("album", key)] = item
        artists = [fa.artist for fa in self.library.followed_artists]
        for key, item in self.resolver.resolve_artists(artists).items():
            self.items[("artist", key)] = item
        self.cache.save()

    def _target(self, kind: str, key: str) -> str | None:
        item = self.items.get((kind, key))
        return item.target_id if item and item.status == "resolved" else None

    # ── Remote matching for removals ───────────────────────────────

    def _match_remote_track(self, local: Track, remote: list[Track]) -> str | None:
        best_id, best_score = None, 0.0
        for rt in remote:
            if not rt.service_id:
                continue
            score, conflict = self.m.score_track(local, _catalog(rt))
            if not conflict and score >= self.m.accept and score > best_score:
                best_id, best_score = rt.service_id, score
        return best_id

    def _intents(self, kind: str) -> list[dict]:
        doc = load_sync_intents(workspace_root=self.root)
        return [i for i in doc["intents"] if i.get("entity_kind") == kind]

    # ── Playlists ──────────────────────────────────────────────────

    def _remote_playlists_by_key(self) -> dict[str, list]:
        out: dict[str, list] = {}
        for pl in self.snap.library.playlists:
            out.setdefault(playlist_key(pl.name), []).append(pl)
        return out

    def _pick_remote(self, local_pl, candidates: list) -> tuple[Any | None, bool]:
        """Return (remote playlist or None, blocked_by_decision)."""
        key = playlist_key(local_pl.name)
        editable = [p for p in candidates if p.service_id in self.snap.editable_playlist_ids]
        choice = decision_for(self.decisions, self.provider, "playlist", key)
        if choice and choice != EXCLUDE:
            for p in editable:
                if p.service_id == choice:
                    self.items[("playlist", key)] = PlanItem(
                        "playlist", key, local_pl.name, "resolved", p.service_id, "your_choice", 1.0,
                        message=f"Your pick: {p.name} — {len(p.tracks)} tracks",
                    )
                    return p, False
        if local_pl.service == self.provider and local_pl.service_id:
            for p in editable:
                if p.service_id == local_pl.service_id:
                    return p, False
        if len(editable) == 1:
            return editable[0], False
        if len(editable) > 1:
            self.items[("playlist", key)] = PlanItem(
                "playlist", key, local_pl.name, "ambiguous",
                candidates=[
                    Candidate(ref=p.service_id, display=f"{p.name} — {len(p.tracks)} tracks", score=1.0)
                    for p in editable
                ],
                message=f"{len(editable)} playlists with this name on {self.title} — pick the one to update.",
            )
            return None, True
        if candidates:
            self.warnings.append(
                f'Playlist "{local_pl.name}" exists on {self.title} but is not yours to edit — '
                "a copy you own will be created."
            )
        return None, False

    def plan_playlists(self, mode: PushMode) -> None:
        remote_by_key = self._remote_playlists_by_key()
        local_keys: set[str] = set()
        removed_tracks: dict[str, list[dict]] = {}
        if mode == PushMode.DELETE:
            for i in self._intents("playlist_track"):
                if i.get("playlist"):
                    removed_tracks.setdefault(playlist_key(i["playlist"]), []).append(i)

        for local_pl in self.library.playlists:
            key = playlist_key(local_pl.name)
            if key in local_keys:
                self.warnings.append(
                    f'Two local playlists share the name "{local_pl.name}" — only the first is pushed.'
                )
                continue
            local_keys.add(key)
            if decision_for(self.decisions, self.provider, "playlist", key) == EXCLUDE:
                self.items[("playlist", key)] = PlanItem(
                    "playlist", key, local_pl.name, "excluded", message="Excluded by you."
                )
                self.playlists.append({"name": local_pl.name, "action": "excluded"})
                continue

            wanted: list[str] = []
            skipped = 0
            for pt in local_pl.tracks:
                tid = self._target("track", track_key(pt.track))
                if tid:
                    wanted.append(tid)
                else:
                    skipped += 1

            remote, blocked = self._pick_remote(local_pl, remote_by_key.get(key, []))
            if blocked:
                self.playlists.append({"name": local_pl.name, "action": "needs_decision"})
                continue

            summary = {"name": local_pl.name, "tracks": len(wanted), "not_pushable": skipped}
            if remote is None:
                ref = f"pl:{key}"
                self.ops.append(
                    {
                        "op": "ensure_playlist",
                        "ref": ref,
                        "name": local_pl.name,
                        "description": local_pl.description or "",
                    }
                )
                self.ops.append(
                    {"op": "set_playlist_tracks", "name": local_pl.name, "playlist_ref": ref,
                     "track_ids": wanted, "added": len(wanted), "removed": 0}
                )
                self.playlists.append({**summary, "action": "create", "added": len(wanted), "removed": 0})
                continue

            current = [pt.track.service_id for pt in remote.tracks if pt.track.service_id]
            if mode == PushMode.WIPE:
                final = list(wanted)
            else:
                drop: set[str] = set()
                present = {track_key(pt.track) for pt in local_pl.tracks}
                for intent in removed_tracks.get(key, []):
                    if intent["key"] in present:
                        continue
                    rid = self._match_remote_track(
                        _track_from_detail(intent.get("detail") or {}),
                        [pt.track for pt in remote.tracks],
                    )
                    if rid:
                        drop.add(rid)
                final = merge_order(wanted, current, drop=drop)
            if final == current:
                self.playlists.append({**summary, "action": "unchanged", "added": 0, "removed": 0})
                continue
            added = sum((Counter(final) - Counter(current)).values())
            removed = sum((Counter(current) - Counter(final)).values())
            self.ops.append(
                {
                    "op": "set_playlist_tracks",
                    "name": local_pl.name,
                    "playlist_id": remote.service_id,
                    "expected_version": remote.snapshot_id,
                    "track_ids": final,
                    "added": added,
                    "removed": removed,
                }
            )
            self.playlists.append({**summary, "action": "update", "added": added, "removed": removed})

        self._plan_playlist_removals(mode, remote_by_key, local_keys)

    def _plan_playlist_removals(self, mode: PushMode, remote_by_key: dict, local_keys: set[str]) -> None:
        deletes: list[dict] = []
        if mode == PushMode.WIPE:
            for key, remotes in remote_by_key.items():
                if key in local_keys:
                    continue
                for p in remotes:
                    deletes.append(self._delete_op(p))
        elif mode == PushMode.DELETE:
            for intent in self._intents("playlist"):
                key = intent["key"]
                if key in local_keys:
                    continue
                remotes = remote_by_key.get(key, [])
                if len(remotes) == 1:
                    deletes.append(self._delete_op(remotes[0]))
                elif len(remotes) > 1:
                    self.warnings.append(
                        f'Not removing "{intent["label"]}": {len(remotes)} playlists with that '
                        f"name on {self.title}."
                    )
        self.ops[:0] = deletes

    def _delete_op(self, p) -> dict:
        return {
            "op": "delete_playlist",
            "playlist_id": p.service_id,
            "name": p.name,
            "owned": p.service_id in self.snap.editable_playlist_ids,
        }

    # ── Liked songs, albums, artists ───────────────────────────────

    def _set_ops(
        self,
        mode: PushMode,
        *,
        wanted: dict[str, str],
        remote: dict[str, str],
        removal_ids: dict[str, str],
        add_op: str,
        remove_op: str,
    ) -> None:
        """``wanted``/``remote``/``removal_ids`` map target id → label."""
        to_add = {i: lbl for i, lbl in wanted.items() if i not in remote}
        to_remove: dict[str, str] = {}
        if mode == PushMode.WIPE:
            to_remove = {i: lbl for i, lbl in remote.items() if i not in wanted}
        elif mode == PushMode.DELETE:
            to_remove = {i: lbl for i, lbl in removal_ids.items() if i in remote and i not in wanted}
        if to_remove:
            self.ops.append({"op": remove_op, "ids": list(to_remove), "labels": list(to_remove.values())})
        if to_add:
            self.ops.append({"op": add_op, "ids": list(to_add), "labels": list(to_add.values())})

    def plan_library(self, mode: PushMode) -> None:
        lib, rlib = self.library, self.snap.library

        wanted_liked: dict[str, str] = {}
        for pt in lib.liked_songs:
            tid = self._target("track", track_key(pt.track))
            if tid:
                wanted_liked.setdefault(tid, self.items[("track", track_key(pt.track))].label)
        remote_liked = {pt.track.service_id: pt.track.name for pt in rlib.liked_songs if pt.track.service_id}
        removal: dict[str, str] = {}
        if mode == PushMode.DELETE:
            present = {track_key(pt.track) for pt in lib.liked_songs}
            remote_tracks = [pt.track for pt in rlib.liked_songs]
            for intent in self._intents("liked_track"):
                if intent["key"] in present:
                    continue
                rid = self._match_remote_track(_track_from_detail(intent.get("detail") or {}), remote_tracks)
                if rid:
                    removal[rid] = intent["label"]
        self._set_ops(mode, wanted=wanted_liked, remote=remote_liked, removal_ids=removal,
                      add_op="add_liked", remove_op="remove_liked")

        wanted_albums: dict[str, str] = {}
        for sa in lib.saved_albums:
            aid = self._target("album", album_key(sa.album))
            if aid:
                wanted_albums.setdefault(aid, self.items[("album", album_key(sa.album))].label)
        remote_albums = {sa.album.service_id: sa.album.name for sa in rlib.saved_albums if sa.album.service_id}
        removal = {}
        if mode == PushMode.DELETE:
            present = {album_key(sa.album) for sa in lib.saved_albums}
            for intent in self._intents("saved_album"):
                if intent["key"] in present:
                    continue
                detail = intent.get("detail") or {}
                probe = Album(name=detail.get("title") or "", artists=[Artist(name=n) for n in detail.get("artists") or []])
                for sa in rlib.saved_albums:
                    if not sa.album.service_id:
                        continue
                    score, conflict = self.m.score_album(probe, _catalog_album_from_local(sa.album))
                    if not conflict and score >= self.m.accept:
                        removal[sa.album.service_id] = intent["label"]
                        break
        self._set_ops(mode, wanted=wanted_albums, remote=remote_albums, removal_ids=removal,
                      add_op="save_albums", remove_op="unsave_albums")

        wanted_artists: dict[str, str] = {}
        for fa in lib.followed_artists:
            aid = self._target("artist", artist_key(fa.artist))
            if aid:
                wanted_artists.setdefault(aid, fa.artist.name)
        remote_artists = {fa.artist.service_id: fa.artist.name for fa in rlib.followed_artists if fa.artist.service_id}
        removal = {}
        if mode == PushMode.DELETE:
            present = {artist_key(fa.artist) for fa in lib.followed_artists}
            by_name = {self.m.norm(fa.artist.name): fa.artist.service_id for fa in rlib.followed_artists}
            for intent in self._intents("followed_artist"):
                if intent["key"] in present:
                    continue
                rid = by_name.get(self.m.norm((intent.get("detail") or {}).get("name") or intent["label"]))
                if rid:
                    removal[rid] = intent["label"]
        self._set_ops(mode, wanted=wanted_artists, remote=remote_artists, removal_ids=removal,
                      add_op="follow_artists", remove_op="unfollow_artists")

    # ── Assembly ───────────────────────────────────────────────────

    def document(self, kind: str, fingerprint: str | None) -> dict[str, Any]:
        items = list(self.items.values())
        counts: dict[str, int] = {}
        for it in items:
            counts[it.status] = counts.get(it.status, 0) + 1
        ambiguous = counts.get("ambiguous", 0)
        return {
            "schema_version": PUSH_PLAN_SCHEMA_VERSION,
            "kind": kind,
            "provider": self.provider,
            "created_at": _now(),
            "library_fingerprint": fingerprint,
            "plan_hash": _plan_hash(self.provider, kind, self.ops),
            "summary": {
                "counts": counts,
                "operations": len(self.ops),
                "can_apply": ambiguous == 0,
                "blocking_reason": (
                    f"{ambiguous} item(s) need your decision — open Inspect Push Plan."
                    if ambiguous
                    else None
                ),
            },
            "items": [it.to_dict() for it in items],
            "playlists": self.playlists,
            "warnings": self.warnings,
            "operations": self.ops,
        }


def build_push_plan(
    library: Library,
    backend: PushBackend,
    mode: PushMode,
    *,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    matcher = Matcher.from_config(load_matching_config(workspace_root=workspace_root))
    log.info("Reading current %s library…", backend.provider_id)
    snapshot = backend.snapshot()
    b = _PlanBuilder(library, backend, snapshot, matcher, workspace_root=workspace_root)
    log.info("Matching local items against the %s catalog…", backend.provider_id)
    b.resolve_local()
    b.plan_playlists(mode)
    b.plan_library(mode)
    fp = library_fingerprint(library, workspace_root=workspace_root)
    doc = b.document(mode.value, fp)
    doc["local_fingerprint"] = local_fingerprint(library, workspace_root=workspace_root)
    return doc


def build_remote_wipe_plan(
    backend: PushBackend, *, workspace_root: Path | None = None
) -> dict[str, Any]:
    """Remove everything from the target library, then add the seed track."""
    matcher = Matcher.from_config(load_matching_config(workspace_root=workspace_root))
    snapshot = backend.snapshot()
    b = _PlanBuilder(Library(), backend, snapshot, matcher, workspace_root=workspace_root)
    rlib = snapshot.library
    for p in rlib.playlists:
        b.ops.append(b._delete_op(p))
    liked = [pt.track.service_id for pt in rlib.liked_songs if pt.track.service_id]
    if liked:
        b.ops.append({"op": "remove_liked", "ids": liked, "labels": [pt.track.name for pt in rlib.liked_songs]})
    albums = [sa.album.service_id for sa in rlib.saved_albums if sa.album.service_id]
    if albums:
        b.ops.append({"op": "unsave_albums", "ids": albums, "labels": [sa.album.name for sa in rlib.saved_albums]})
    artists = [fa.artist.service_id for fa in rlib.followed_artists if fa.artist.service_id]
    if artists:
        b.ops.append({"op": "unfollow_artists", "ids": artists, "labels": [fa.artist.name for fa in rlib.followed_artists]})

    title, artist = SEED_TRACK
    seed = Track(name=title, artists=[Artist(name=artist)])
    item = b.resolver.resolve_tracks([seed])[track_key(seed)]
    b.cache.save()
    seed_id = item.target_id if item.status == "resolved" else None
    if seed_id is None and item.candidates:
        seed_id = item.candidates[0].ref
    if seed_id:
        b.ops.append({"op": "add_liked", "ids": [seed_id], "labels": ["1 liked song"]})
    else:
        b.warnings.append(
            f"Could not add a liked song after the wipe on {b.title}; the library may stay empty."
        )
    doc = b.document(REMOTE_WIPE_KIND, None)
    doc["items"] = []
    doc["summary"]["can_apply"] = True
    doc["summary"]["blocking_reason"] = None
    doc["removal_counts"] = {
        "playlists": len(rlib.playlists),
        "liked_songs": len(liked),
        "saved_albums": len(albums),
        "followed_artists": len(artists),
    }
    return doc


def _local_library(library: Library | None) -> Library:
    if library is not None:
        return library
    from common.store import load_workspace

    return load_workspace()


def dry_run_push(
    provider: str,
    mode: PushMode,
    *,
    backend: PushBackend | None = None,
    library: Library | None = None,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    """Build and store the plan for ``provider``/``mode``; runs to completion or raises."""
    from common.push.registry import get_push_backend

    backend = backend or get_push_backend(provider)
    plan = build_push_plan(_local_library(library), backend, mode, workspace_root=workspace_root)
    path = save_plan(plan, workspace_root=workspace_root)
    log.info("Push plan saved → %s", path)
    return plan


def prepare_push(
    provider: str,
    mode: PushMode,
    *,
    backend: PushBackend | None = None,
    library: Library | None = None,
    workspace_root: Path | None = None,
) -> tuple[dict[str, Any], str]:
    """Latest plan for Push Now; re-plans when Local Data, removals, decisions or matching changed.

    Returns ``(plan, reason)`` where ``reason`` is empty when the stored plan was
    reused, ``"new"`` when no plan existed for this mode, and ``"changed"`` when a
    stored plan was replaced because its inputs no longer match.
    """
    library = _local_library(library)
    plan = load_latest_plan(provider, mode.value, workspace_root=workspace_root)
    current = library_fingerprint(library, workspace_root=workspace_root)
    if plan is not None and plan.get("library_fingerprint") == current:
        return plan, ""
    reason = "changed" if plan is not None else "new"
    plan = dry_run_push(
        provider, mode, backend=backend, library=library, workspace_root=workspace_root
    )
    return plan, reason


def dry_run_remote_wipe(
    provider: str, *, backend: PushBackend | None = None, workspace_root: Path | None = None
) -> dict[str, Any]:
    from common.push.registry import get_push_backend

    backend = backend or get_push_backend(provider)
    plan = build_remote_wipe_plan(backend, workspace_root=workspace_root)
    save_plan(plan, workspace_root=workspace_root)
    return plan


def inspectable_plan(
    provider: str,
    mode: PushMode,
    *,
    library: Library | None = None,
    workspace_root: Path | None = None,
) -> dict[str, Any] | None:
    """Latest plan for ``provider``/``mode`` if it still matches Local Data (decisions aside)."""
    plan = load_latest_plan(provider, mode.value, workspace_root=workspace_root)
    if plan is None or not plan.get("local_fingerprint"):
        return None
    current = local_fingerprint(_local_library(library), workspace_root=workspace_root)
    return plan if plan["local_fingerprint"] == current else None


def require_applicable(plan: dict[str, Any]) -> None:
    summary = plan.get("summary") or {}
    if not summary.get("can_apply"):
        raise PushError(
            PushErrorCode.PLAN_BLOCKED,
            summary.get("blocking_reason") or "This plan can't be applied.",
        )
