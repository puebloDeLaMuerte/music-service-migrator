"""Column order for the dedupe view (cross-playlist duplicate groups).

Order is read from ``.env`` key :data:`ENV_KEY`. Values are comma-separated
**column ids** (lowercase); any permutation of the canonical set is allowed.
"""

from __future__ import annotations

from common.config import get

CANONICAL_COLUMNS: tuple[tuple[str, str], ...] = (
    ("playlists", "Playlists"),
    ("track", "Track"),
    ("artists", "Artists"),
    ("positions", "Positions"),
)

ENV_KEY = "LOCAL_LIST_COLUMNS_DEDUPE"


def default_column_order() -> tuple[str, ...]:
    return tuple(cid for cid, _ in CANONICAL_COLUMNS)


def default_column_order_csv() -> str:
    return ",".join(default_column_order())


def parse_column_order(raw: str | None) -> tuple[str, ...] | None:
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None
    allowed = {cid for cid, _ in CANONICAL_COLUMNS}
    parts = [p.strip().lower() for p in s.split(",") if p.strip()]
    if len(parts) != len(allowed):
        return None
    if set(parts) != allowed:
        return None
    if len(parts) != len(set(parts)):
        return None
    return tuple(parts)


def validate_column_order_text(text: str) -> str | None:
    t = text.strip()
    if not t:
        return None
    if parse_column_order(t) is None:
        allowed = ", ".join(sorted(cid for cid, _ in CANONICAL_COLUMNS))
        return f"Use each id once, comma-separated: {allowed}"
    return None


def dedupe_column_order() -> tuple[str, ...]:
    raw = get(ENV_KEY, "") or ""
    parsed = parse_column_order(raw)
    if parsed is not None:
        return parsed
    return default_column_order()


def dedupe_column_headers() -> tuple[str, ...]:
    order = dedupe_column_order()
    id_to_header = dict(CANONICAL_COLUMNS)
    return tuple(id_to_header[i] for i in order)


def permute_dedupe_row(row: tuple[str, ...]) -> tuple[str, ...]:
    """Map a row in canonical id order to the configured display order."""
    canon_ids = tuple(cid for cid, _ in CANONICAL_COLUMNS)
    if len(row) != len(canon_ids):
        raise ValueError(
            f"row length {len(row)} != canonical {len(canon_ids)} for dedupe table"
        )
    order = dedupe_column_order()
    canon_map = dict(zip(canon_ids, row))
    return tuple(canon_map[i] for i in order)
