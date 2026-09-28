"""Live view of which plan conflicts still need a user pick."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from common.push.resolution_cache import decision_for, load_decisions


def unsettled_decision_count(
    plan: dict[str, Any], *, workspace_root: Path | None = None
) -> int:
    """Ambiguous plan items with no saved pick for this provider yet."""
    provider = plan.get("provider", "")
    decisions = load_decisions(workspace_root=workspace_root)
    n = 0
    for item in plan.get("items") or []:
        if item.get("status") != "ambiguous":
            continue
        if not decision_for(decisions, provider, item["kind"], item["key"]):
            n += 1
    return n


def push_blocked_explanation(
    plan: dict[str, Any], *, workspace_root: Path | None = None
) -> tuple[int, int, int]:
    """``(still_need_pick, settled_by_picks, cant_push)`` for user-facing text."""
    summary = plan.get("summary") or {}
    counts = summary.get("counts") or {}
    items = plan.get("items") or []
    still = unsettled_decision_count(plan, workspace_root=workspace_root)
    cant = int(counts.get("unavailable", 0)) + int(counts.get("unsupported", 0))
    ambiguous_now = sum(1 for i in items if i.get("status") == "ambiguous")
    settled = ambiguous_now - still + sum(
        1 for i in items if i.get("method") == "your_choice"
    )
    return still, settled, cant


def push_blocked_guidance(
    plan: dict[str, Any], *, workspace_root: Path | None = None
) -> str:
    """Plain-language steps — ambiguous picks only, not the can't-push list."""
    still, settled, cant = push_blocked_explanation(plan, workspace_root=workspace_root)
    lines = [
        "Push is waiting on you — not on Tidal/Spotify errors in the log.",
        "",
        "Only items with several possible matches block a push. "
        "\"Can't be pushed\" and \"Excluded by you\" do not.",
        "",
    ]
    if settled:
        lines.append(
            f"{settled} conflict(s) already resolved by picks you made earlier."
        )
    if still:
        lines.append(
            f"{still} conflict(s) still need a match — open Inspect Push Plan, "
            "use the decisions list (not the Full report scroll), pick 1–9 or exclude."
        )
    else:
        lines.append(
            "No open picks on file — try Push (dry run) again to refresh the plan."
        )
    if cant:
        lines.append(
            f"({cant} item(s) cannot be matched on the service; they are skipped when pushing.)"
        )
    return "\n".join(lines)
