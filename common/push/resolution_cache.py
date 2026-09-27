"""Resolution cache and user decisions for push, keyed by name identity.

Both files are internal bookkeeping; the UI shows names only.

- ``resolution_cache.json`` — confident matches from earlier dry-runs, per
  provider, so repeated dry-runs do not repeat catalog searches.
- ``push_decisions.json`` — what the user picked in Inspect Push Plan for
  ambiguous items (a candidate, or ``exclude`` to skip the item).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from common.store import meta_dir

EXCLUDE = "__exclude__"


def _path(name: str, workspace_root: Path | None) -> Path:
    if workspace_root is not None:
        return Path(workspace_root) / "meta" / name
    return meta_dir() / name


def _load(path: Path, default_key: str) -> dict[str, Any]:
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get(default_key), dict):
                return data
        except (OSError, json.JSONDecodeError):
            pass
    return {"schema_version": 1, default_key: {}}


def _save(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def _slot(kind: str, key: str) -> str:
    return f"{kind}:{key}"


class ResolutionCache:
    def __init__(self, provider: str, *, workspace_root: Path | None = None) -> None:
        self.provider = provider
        self._path = _path("resolution_cache.json", workspace_root)
        self._doc = _load(self._path, "entries")
        self._dirty = False

    def get(self, kind: str, key: str) -> dict[str, Any] | None:
        row = self._doc["entries"].get(_slot(kind, key), {}).get(self.provider)
        return row if isinstance(row, dict) and row.get("target_id") else None

    def put(self, kind: str, key: str, target_id: str, method: str, confidence: float) -> None:
        self._doc["entries"].setdefault(_slot(kind, key), {})[self.provider] = {
            "target_id": target_id,
            "method": method,
            "confidence": round(confidence, 3),
        }
        self._dirty = True

    def save(self) -> None:
        if self._dirty:
            _save(self._path, self._doc)
            self._dirty = False


def decisions_path(workspace_root: Path | None = None) -> Path:
    return _path("push_decisions.json", workspace_root)


def load_decisions(*, workspace_root: Path | None = None) -> dict[str, Any]:
    return _load(decisions_path(workspace_root), "choices")


def decision_for(doc: dict[str, Any], provider: str, kind: str, key: str) -> str | None:
    val = doc["choices"].get(_slot(kind, key), {}).get(provider)
    return str(val) if val else None


def decision_display(doc: dict[str, Any], provider: str, kind: str, key: str) -> str | None:
    val = (doc.get("displays") or {}).get(_slot(kind, key), {}).get(provider)
    return str(val) if val else None


def set_decision(
    provider: str,
    kind: str,
    key: str,
    choice: str | None,
    *,
    display: str | None = None,
    workspace_root: Path | None = None,
) -> None:
    """Pin a candidate ref (or :data:`EXCLUDE`) for one item; ``None`` clears it."""
    doc = load_decisions(workspace_root=workspace_root)
    slot = _slot(kind, key)
    displays = doc.setdefault("displays", {})
    for table, value in ((doc["choices"], choice), (displays, display if choice else None)):
        row = table.setdefault(slot, {})
        if value is None:
            row.pop(provider, None)
        else:
            row[provider] = value
        if not row:
            table.pop(slot, None)
    _save(decisions_path(workspace_root), doc)
