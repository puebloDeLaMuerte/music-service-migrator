"""Apply results of a remote catalog pull into the local workspace."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from common.models import Library
from common.store import save_workspace


class PullMode(Enum):
    """How a pull is merged into disk. Only ``FULL`` is implemented today."""

    FULL = "full"
    # Future: NEW_ONLY, ALBUMS_ONLY, NON_CONFLICTING, …


def apply_pull_result(
    provider: str,
    library: Library,
    mode: PullMode = PullMode.FULL,
    *,
    workspace_root: Path | None = None,
) -> Path:
    """Persist ``library`` from a pull of ``provider``.

    Today: full mirror — ``save_workspace`` overwrites lists and removes orphan
    playlist files. Other ``PullMode`` values will replace this behaviour later.

    Pass ``workspace_root`` to write somewhere other than the normal work directory
    (e.g. a backup folder).
    """
    if mode is not PullMode.FULL:
        raise NotImplementedError(f"Pull mode {mode!r} is not implemented yet")
    library.last_pull_provider = provider
    return save_workspace(library, workspace_root=workspace_root)
