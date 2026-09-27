"""Human-readable dry-run report for the log panel."""

from __future__ import annotations

from typing import Any

from common.push.models import REMOTE_WIPE_KIND, PushMode

MODE_TITLES = {
    PushMode.ADD.value: "Push-add",
    PushMode.DELETE.value: "Push-delete",
    PushMode.WIPE.value: "Wipe-push",
    REMOTE_WIPE_KIND: "Wipe remote library",
}

_LIST_LIMIT = 40


def _clip(lines: list[str], limit: int = _LIST_LIMIT) -> list[str]:
    if len(lines) <= limit:
        return lines
    return lines[:limit] + [f"    … and {len(lines) - limit} more (full list in the plan file)"]


def _op_counts(plan: dict[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for op in plan.get("operations") or []:
        n = len(op.get("ids") or []) or 1
        out[op["op"]] = out.get(op["op"], 0) + n
    return out


def format_plan_report(plan: dict[str, Any]) -> str:
    provider = str(plan.get("provider", "")).capitalize()
    kind = plan.get("kind", "")
    lines = [f"Push plan — {provider} · {MODE_TITLES.get(kind, kind)}"]
    if kind == REMOTE_WIPE_KIND:
        return "\n".join(lines + _wipe_body(plan))

    items = plan.get("items") or []
    ambiguous = [i for i in items if i["status"] == "ambiguous"]
    if ambiguous:
        lines += ["", f"!! NEEDS YOUR DECISION ({len(ambiguous)}) — Push Now is blocked until resolved"]
        body = []
        for it in ambiguous:
            body.append(f"  ? [{it['kind']}] {it['label']}")
            for n, c in enumerate(it.get("candidates") or [], 1):
                body.append(f"      {n}) {c['display']}  ({round(c['score'] * 100)}%)")
        lines += _clip(body, 60)
        lines.append('  → Open "Inspect Push Plan" to pick a match or exclude each item.')

    lines += ["", "Changes"]
    pls = plan.get("playlists") or []
    ops = plan.get("operations") or []
    deletes = [o for o in ops if o["op"] == "delete_playlist"]
    by_action: dict[str, int] = {}
    for p in pls:
        by_action[p["action"]] = by_action.get(p["action"], 0) + 1
    lines.append(
        "  Playlists: "
        f"{by_action.get('create', 0)} new, {by_action.get('update', 0)} changed, "
        f"{by_action.get('unchanged', 0)} unchanged, {len(deletes)} removed"
    )
    detail = []
    for p in pls:
        if p["action"] == "create":
            detail.append(f"    + {p['name']} (new, {p['tracks']} tracks)")
        elif p["action"] == "update":
            detail.append(f"    ~ {p['name']} (+{p['added']} −{p['removed']})")
        elif p["action"] == "excluded":
            detail.append(f"    · {p['name']} (excluded by you)")
    for o in deletes:
        verb = "delete" if o.get("owned") else "unfollow"
        detail.append(f"    − {o['name']} ({verb})")
    lines += _clip(detail)

    c = _op_counts(plan)
    lines.append(f"  Liked songs: +{c.get('add_liked', 0)} −{c.get('remove_liked', 0)}")
    lines.append(f"  Saved albums: +{c.get('save_albums', 0)} −{c.get('unsave_albums', 0)}")
    lines.append(f"  Followed artists: +{c.get('follow_artists', 0)} −{c.get('unfollow_artists', 0)}")

    missing = [i for i in items if i["status"] in ("unavailable", "unsupported")]
    if missing:
        lines += ["", f"Can't be pushed ({len(missing)})"]
        lines += _clip([f"  ✗ [{i['kind']}] {i['label']} — {i.get('message') or i['status']}" for i in missing])
    excluded = [i for i in items if i["status"] == "excluded"]
    if excluded:
        lines.append(f"  Excluded by you: {len(excluded)}")

    warnings = plan.get("warnings") or []
    if warnings:
        lines += ["", "Warnings"] + _clip([f"  ! {w}" for w in warnings])

    summary = plan.get("summary") or {}
    lines.append("")
    if summary.get("can_apply"):
        n = summary.get("operations", 0)
        lines.append(f"Ready to apply: {n} write step(s)." if n else "Nothing to change.")
    else:
        lines.append(f"Blocked: {summary.get('blocking_reason')}")
    return "\n".join(lines)


def confirm_summary(plan: dict[str, Any]) -> str:
    """Few-line summary for the Push Now confirmation dialog (plain text)."""
    c = _op_counts(plan)
    pls = plan.get("playlists") or []
    new = sum(1 for p in pls if p["action"] == "create")
    changed = sum(1 for p in pls if p["action"] == "update")
    lines = [
        f"Playlists: {new} new, {changed} changed, {c.get('delete_playlist', 0)} removed",
        f"Liked songs: +{c.get('add_liked', 0)} −{c.get('remove_liked', 0)}",
        f"Saved albums: +{c.get('save_albums', 0)} −{c.get('unsave_albums', 0)}",
        f"Followed artists: +{c.get('follow_artists', 0)} −{c.get('unfollow_artists', 0)}",
    ]
    missing = sum(1 for i in plan.get("items") or [] if i["status"] in ("unavailable", "unsupported"))
    if missing:
        lines.append(f"{missing} item(s) can't be pushed and will be skipped.")
    return "\n".join(lines)


def _wipe_body(plan: dict[str, Any]) -> list[str]:
    rc = plan.get("removal_counts") or {}
    lines = [
        "",
        "Will remove from the service:",
        f"  {rc.get('playlists', 0)} playlists, {rc.get('liked_songs', 0)} liked songs, "
        f"{rc.get('saved_albums', 0)} saved albums, {rc.get('followed_artists', 0)} followed artists",
    ]
    seed = [o for o in plan.get("operations") or [] if o["op"] == "add_liked"]
    if seed:
        lines.append(f"Then like: {seed[-1]['labels'][0]}")
    for w in plan.get("warnings") or []:
        lines.append(f"  ! {w}")
    lines.append("Local Data is not touched.")
    return lines
