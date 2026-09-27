"""Apply a push plan step by step, resumable after a failure.

Completed steps are recorded in a progress file next to the plan; running the
same plan again skips them. A playlist that changed on the service since the
dry-run is not overwritten — the step fails and a fresh dry-run is needed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from common.log import get_logger
from common.push.backend import PushBackend
from common.push.errors import PushError, PushErrorCode
from common.push.plan_store import load_progress, save_progress

log = get_logger(__name__)

ProgressFn = Callable[[int, int, str], None]

_SET_OPS = {
    "add_liked": "add_liked",
    "remove_liked": "remove_liked",
    "save_albums": "save_albums",
    "unsave_albums": "unsave_albums",
    "follow_artists": "follow_artists",
    "unfollow_artists": "unfollow_artists",
}

_SET_TEXT = {
    "add_liked": "Like {n} song(s)",
    "remove_liked": "Unlike {n} song(s)",
    "save_albums": "Save {n} album(s)",
    "unsave_albums": "Remove {n} saved album(s)",
    "follow_artists": "Follow {n} artist(s)",
    "unfollow_artists": "Unfollow {n} artist(s)",
}


def describe_op(op: dict[str, Any]) -> str:
    kind = op["op"]
    if kind in _SET_TEXT:
        return _SET_TEXT[kind].format(n=len(op.get("ids") or []))
    if kind == "delete_playlist":
        return f'{"Delete" if op.get("owned") else "Unfollow"} playlist "{op["name"]}"'
    if kind == "ensure_playlist":
        return f'Create playlist "{op["name"]}"'
    if kind == "set_playlist_tracks":
        return f'Write {len(op["track_ids"])} track(s) to "{op["name"]}"'
    return kind


def _run(backend: PushBackend, op: dict[str, Any], refs: dict[str, str]) -> None:
    kind = op["op"]
    if kind in _SET_OPS:
        getattr(backend, _SET_OPS[kind])(list(op["ids"]))
    elif kind == "delete_playlist":
        backend.delete_playlist(op["playlist_id"], owned=bool(op.get("owned")))
    elif kind == "ensure_playlist":
        existing = backend.find_editable_playlists(op["name"])
        refs[op["ref"]] = existing[0] if existing else backend.create_playlist(
            op["name"], op.get("description") or ""
        )
    elif kind == "set_playlist_tracks":
        pid = op.get("playlist_id") or refs.get(op.get("playlist_ref") or "")
        if not pid:
            raise PushError(PushErrorCode.REMOTE_ERROR, f'Playlist "{op["name"]}" was not created.')
        expected = op.get("expected_version")
        if expected and backend.playlist_version(pid) != expected:
            raise PushError(
                PushErrorCode.PLAN_STALE,
                f'Playlist "{op["name"]}" changed on the service since the dry-run — '
                "run Push (dry run) again.",
            )
        backend.replace_playlist_tracks(pid, list(op["track_ids"]))
    else:
        raise PushError(PushErrorCode.NOT_SUPPORTED, f"Unknown step {kind!r}", recoverable=False)


def execute_plan(
    backend: PushBackend,
    plan: dict[str, Any],
    *,
    workspace_root: Path | None = None,
    on_progress: ProgressFn | None = None,
) -> dict[str, Any]:
    """Run all remaining steps of ``plan``. Returns the final progress record."""
    provider, kind = plan["provider"], plan["kind"]
    ops: list[dict[str, Any]] = plan.get("operations") or []
    progress = load_progress(provider, kind, workspace_root=workspace_root)
    if not progress or progress.get("plan_hash") != plan.get("plan_hash"):
        progress = {"plan_hash": plan.get("plan_hash"), "done": [], "refs": {}, "status": "running"}
    done: set[int] = set(progress["done"])
    refs: dict[str, str] = progress["refs"]
    if done:
        log.info("Resuming push: %d of %d step(s) already done", len(done), len(ops))
    progress["status"] = "running"
    for idx, op in enumerate(ops):
        if idx in done:
            continue
        text = describe_op(op)
        if on_progress:
            on_progress(idx + 1, len(ops), text)
        try:
            _run(backend, op, refs)
        except PushError as exc:
            progress.update(status="failed", error=str(exc), failed_step=idx)
            save_progress(provider, kind, progress, workspace_root=workspace_root)
            raise
        except Exception as exc:  # noqa: BLE001 — provider errors vary per SDK
            progress.update(status="failed", error=str(exc), failed_step=idx)
            save_progress(provider, kind, progress, workspace_root=workspace_root)
            raise PushError(PushErrorCode.REMOTE_ERROR, f"{text} failed: {exc}") from exc
        done.add(idx)
        progress["done"] = sorted(done)
        save_progress(provider, kind, progress, workspace_root=workspace_root)
    progress.update(status="complete", finished_at=datetime.now(timezone.utc).isoformat())
    progress.pop("error", None)
    progress.pop("failed_step", None)
    save_progress(provider, kind, progress, workspace_root=workspace_root)
    return progress
