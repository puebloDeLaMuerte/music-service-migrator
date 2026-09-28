"""Human-readable summaries of a push plan (log report, summary page, confirm dialog)."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
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


def plan_title(plan: dict[str, Any]) -> str:
    kind = plan.get("kind", "")
    return f"{str(plan.get('provider', '')).capitalize()} · {MODE_TITLES.get(kind, kind)}"


def plan_created(plan: dict[str, Any]) -> str:
    """``created_at`` as local ``YYYY-MM-DD HH:MM``, or an empty string."""
    raw = plan.get("created_at")
    if not raw:
        return ""
    try:
        return datetime.fromisoformat(raw).astimezone().strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return str(raw)


def plan_counts(plan: dict[str, Any]) -> dict[str, int]:
    """Headline numbers; shared so every summary agrees."""
    c = _op_counts(plan)
    actions = Counter(p["action"] for p in plan.get("playlists") or [])
    statuses = Counter(i["status"] for i in plan.get("items") or [])
    counts = {
        "operations": len(plan.get("operations") or []),
        "playlists_new": actions["create"],
        "playlists_changed": actions["update"],
        "playlists_unchanged": actions["unchanged"],
        "playlists_removed": c.get("delete_playlist", 0),
        "tracks_added": sum(p.get("added", 0) for p in plan.get("playlists") or []),
        "tracks_removed": sum(p.get("removed", 0) for p in plan.get("playlists") or []),
        "liked_added": c.get("add_liked", 0),
        "liked_removed": c.get("remove_liked", 0),
        "albums_added": c.get("save_albums", 0),
        "albums_removed": c.get("unsave_albums", 0),
        "artists_added": c.get("follow_artists", 0),
        "artists_removed": c.get("unfollow_artists", 0),
        "decisions": statuses["ambiguous"],
        "settled_by_you": sum(
            1
            for i in plan.get("items") or []
            if i.get("method") == "your_choice" or i["status"] == "excluded"
        ),
        "not_pushable": statuses["unavailable"] + statuses["unsupported"],
        "excluded": statuses["excluded"] + actions["excluded"],
        "warnings": len(plan.get("warnings") or []),
    }
    counts["deletions"] = (
        counts["playlists_removed"]
        + counts["tracks_removed"]
        + counts["liked_removed"]
        + counts["albums_removed"]
        + counts["artists_removed"]
    )
    return counts


def summary_rows(plan: dict[str, Any]) -> list[tuple[str, str]]:
    """``(label, value)`` pairs for the plan summary, in display order."""
    if plan.get("kind") == REMOTE_WIPE_KIND:
        rc = plan.get("removal_counts") or {}
        return [
            ("Write steps", str(len(plan.get("operations") or []))),
            ("Playlists", f"−{rc.get('playlists', 0)}"),
            ("Liked songs", f"−{rc.get('liked_songs', 0)}"),
            ("Saved albums", f"−{rc.get('saved_albums', 0)}"),
            ("Followed artists", f"−{rc.get('followed_artists', 0)}"),
            ("Warnings", str(len(plan.get("warnings") or []))),
        ]
    n = plan_counts(plan)
    playlists = f"{n['playlists_new']} new · {n['playlists_changed']} changed"
    if n["playlists_removed"]:
        playlists += f" · {n['playlists_removed']} removed"
    return [
        ("Write steps", str(n["operations"])),
        ("Deletions on service", str(n["deletions"])),
        ("Playlists", playlists),
        ("Playlist tracks", f"+{n['tracks_added']} · −{n['tracks_removed']}"),
        ("Liked songs", f"+{n['liked_added']} · −{n['liked_removed']}"),
        ("Saved albums", f"+{n['albums_added']} · −{n['albums_removed']}"),
        ("Followed artists", f"+{n['artists_added']} · −{n['artists_removed']}"),
        ("Need your decision", str(n["decisions"])),
        ("Settled by you", str(n["settled_by_you"])),
        ("Can't be pushed", str(n["not_pushable"])),
        ("Excluded by you", str(n["excluded"])),
        ("Warnings", str(n["warnings"])),
    ]


def conflict_context(pending: int, by_you: int) -> list[str]:
    """Two sentences: past picks vs still-open conflicts. Empty when there were none."""
    if pending == 0 and by_you == 0:
        return []

    def _n(n: int) -> str:
        return f"{n} conflict" if n == 1 else f"{n} conflicts"

    past = (
        f"{_n(by_you)} was able to be resolved by decisions you made in the past."
        if by_you == 1
        else f"{_n(by_you)} were able to be resolved by decisions you made in the past."
    )
    still = (
        f"{_n(pending)} still needs your decision."
        if pending == 1
        else f"{_n(pending)} still need your decision."
    )
    return [past, still]


def plan_verdict(plan: dict[str, Any]) -> str:
    summary = plan.get("summary") or {}
    if not summary.get("can_apply"):
        return f"Blocked: {summary.get('blocking_reason')}"
    n = summary.get("operations", 0)
    return f"Ready to apply: {n} write step(s)." if n else "Nothing to change."


def plan_overview(plan: dict[str, Any]) -> str:
    """Plain-text first-page summary: what this plan is, plus the headline numbers."""
    provider = str(plan.get("provider", "")).capitalize()
    created = plan_created(plan)
    lines = [f"Push plan — {plan_title(plan)}"]
    if plan.get("kind") == REMOTE_WIPE_KIND:
        lines.append(f"Empties your {provider} library. Local Data is not touched.")
    else:
        lines.append(f"Pushes Local Data to {provider} as it was when the plan was built.")
    if created:
        lines.append(f"Built {created}.")
    lines.append("")
    lines += [f"  {label:<22}{value}" for label, value in summary_rows(plan)]
    n = plan_counts(plan)
    context = conflict_context(n["decisions"], n["settled_by_you"])
    if context:
        lines += ["", *context]
    lines += ["", plan_verdict(plan)]
    return "\n".join(lines)


def format_plan_report(plan: dict[str, Any]) -> str:
    """Overview followed by the item-by-item detail."""
    return f"{plan_overview(plan)}\n\n{format_plan_details(plan)}"


def format_plan_details(plan: dict[str, Any]) -> str:
    """Everything the plan says, item by item (no overview header)."""
    kind = plan.get("kind", "")
    lines: list[str] = []
    if kind == REMOTE_WIPE_KIND:
        return "\n".join(_wipe_body(plan)).lstrip("\n")

    items = plan.get("items") or []
    ambiguous = [i for i in items if i["status"] == "ambiguous"]
    if ambiguous:
        lines += [f"!! NEEDS YOUR DECISION ({len(ambiguous)}) — Push Now is blocked until resolved"]
        body = []
        for it in ambiguous:
            body.append(f"  ? [{it['kind']}] {it['label']}")
            for n, c in enumerate(it.get("candidates") or [], 1):
                body.append(f"      {n}) {c['display']}  ({round(c['score'] * 100)}%)")
                if c.get("detail"):
                    body.append(f"         {c['detail']}")
        lines += _clip(body, 60)
        lines.append('  → Open "Inspect Push Plan" to pick a match or exclude each item.')
        lines.append("")

    by_you = [
        i for i in items
        if i.get("method") == "your_choice" or i["status"] == "excluded"
    ]
    if by_you:
        lines += [f"Settled by your earlier picks ({len(by_you)})"]
        body = []
        for it in by_you:
            note = it.get("message") or (
                "excluded" if it["status"] == "excluded" else "your pick"
            )
            body.append(f"  ✓ [{it['kind']}] {it['label']} — {note}")
        lines += _clip(body)
        lines.append("")

    lines += ["Changes"]
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

    return "\n".join(lines)


def confirm_summary(plan: dict[str, Any]) -> str:
    """Few-line summary for the Push Now confirmation dialog (plain text)."""
    n = plan_counts(plan)
    lines = [
        f"Write steps: {n['operations']}  ·  deletions on the service: {n['deletions']}",
        f"Playlists: {n['playlists_new']} new, {n['playlists_changed']} changed, "
        f"{n['playlists_removed']} removed",
        f"Playlist tracks: +{n['tracks_added']} −{n['tracks_removed']}",
        f"Liked songs: +{n['liked_added']} −{n['liked_removed']}",
        f"Saved albums: +{n['albums_added']} −{n['albums_removed']}",
        f"Followed artists: +{n['artists_added']} −{n['artists_removed']}",
    ]
    if n["not_pushable"]:
        lines.append(f"{n['not_pushable']} item(s) can't be pushed and will be skipped.")
    return "\n".join(lines)


def _wipe_body(plan: dict[str, Any]) -> list[str]:
    rc = plan.get("removal_counts") or {}
    lines = [
        "",
        "Will remove from the service:",
        f"  {rc.get('playlists', 0)} playlists, {rc.get('liked_songs', 0)} liked songs, "
        f"{rc.get('saved_albums', 0)} saved albums, {rc.get('followed_artists', 0)} followed artists",
    ]
    if any(o.get("op") == "add_liked" for o in plan.get("operations") or []):
        lines.append("  Then one liked song will be added.")
    for w in plan.get("warnings") or []:
        lines.append(f"  ! {w}")
    lines.append("Local Data is not touched.")
    return lines
