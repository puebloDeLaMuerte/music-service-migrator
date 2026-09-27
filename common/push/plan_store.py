"""Persist push plans and apply progress under ``work/meta/push_plans/``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from common.store import meta_dir


def push_plans_dir(workspace_root: Path | None = None) -> Path:
    root = Path(workspace_root) / "meta" if workspace_root is not None else meta_dir()
    d = root / "push_plans"
    d.mkdir(parents=True, exist_ok=True)
    return d


def latest_plan_path(provider: str, kind: str, *, workspace_root: Path | None = None) -> Path:
    return push_plans_dir(workspace_root) / f"{provider}_{kind}_latest.json"


def progress_path(provider: str, kind: str, *, workspace_root: Path | None = None) -> Path:
    return push_plans_dir(workspace_root) / f"{provider}_{kind}_progress.json"


def save_plan(plan: dict[str, Any], *, workspace_root: Path | None = None) -> Path:
    path = latest_plan_path(plan["provider"], plan["kind"], workspace_root=workspace_root)
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _read(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def load_latest_plan(
    provider: str, kind: str, *, workspace_root: Path | None = None
) -> dict[str, Any] | None:
    return _read(latest_plan_path(provider, kind, workspace_root=workspace_root))


def load_progress(
    provider: str, kind: str, *, workspace_root: Path | None = None
) -> dict[str, Any] | None:
    return _read(progress_path(provider, kind, workspace_root=workspace_root))


def save_progress(
    provider: str, kind: str, progress: dict[str, Any], *, workspace_root: Path | None = None
) -> None:
    path = progress_path(provider, kind, workspace_root=workspace_root)
    path.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")
