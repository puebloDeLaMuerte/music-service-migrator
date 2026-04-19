"""Column order for local library list views (albums, artists, songs, playlists).

Order is read from ``.env`` (see :data:`ENV_KEYS`). Values are comma-separated
**column ids** (lowercase); any permutation of the canonical set is allowed.
"""

from __future__ import annotations

from typing import Literal

from common.config import get

ListKind = Literal["albums", "artists", "songs", "playlists"]

# Canonical (id, header label) — row tuples from ``rows`` must follow this id order.
CANONICAL_COLUMNS: dict[ListKind, tuple[tuple[str, str], ...]] = {
    "albums": (
        ("album", "Album"),
        ("artists", "Artists"),
        ("added", "Added"),
    ),
    "artists": (("artist", "Artist"), ("added", "Added")),
    "songs": (
        ("track", "Track"),
        ("artists", "Artists"),
        ("album", "Album"),
        ("added", "Added"),
    ),
    "playlists": (
        ("playlist", "Playlist"),
        ("owner", "Owner"),
        ("tracks", "Tracks"),
        ("added", "Added"),
    ),
}

ENV_KEYS: dict[ListKind, str] = {
    "albums": "LOCAL_LIST_COLUMNS_ALBUMS",
    "artists": "LOCAL_LIST_COLUMNS_ARTISTS",
    "songs": "LOCAL_LIST_COLUMNS_SONGS",
    "playlists": "LOCAL_LIST_COLUMNS_PLAYLISTS",
}


def default_column_order(kind: ListKind) -> tuple[str, ...]:
    return tuple(cid for cid, _ in CANONICAL_COLUMNS[kind])


def default_column_order_csv(kind: ListKind) -> str:
    return ",".join(default_column_order(kind))


def parse_column_order(kind: ListKind, raw: str | None) -> tuple[str, ...] | None:
    """Return a valid order, or ``None`` if *raw* is invalid."""
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None
    allowed = {cid for cid, _ in CANONICAL_COLUMNS[kind]}
    parts = [p.strip().lower() for p in s.split(",") if p.strip()]
    if len(parts) != len(allowed):
        return None
    if set(parts) != allowed:
        return None
    if len(parts) != len(set(parts)):
        return None
    return tuple(parts)


def validate_column_order_text(kind: ListKind, text: str) -> str | None:
    """Return an error message, or ``None`` if *text* is a valid order."""
    t = text.strip()
    if not t:
        return None
    if parse_column_order(kind, t) is None:
        allowed = ", ".join(sorted(cid for cid, _ in CANONICAL_COLUMNS[kind]))
        return f"Use each id once, comma-separated: {allowed}"
    return None


def kind_for_local_list_columns_env(env_key: str) -> ListKind | None:
    for k, v in ENV_KEYS.items():
        if v == env_key:
            return k
    return None


def local_list_column_order(kind: ListKind) -> tuple[str, ...]:
    """Resolved column id order (from env or default)."""
    raw = get(ENV_KEYS[kind], "") or ""
    parsed = parse_column_order(kind, raw)
    if parsed is not None:
        return parsed
    return default_column_order(kind)


def local_list_column_headers(kind: ListKind) -> tuple[str, ...]:
    """Header labels in display order."""
    order = local_list_column_order(kind)
    id_to_header = dict(CANONICAL_COLUMNS[kind])
    return tuple(id_to_header[i] for i in order)


def permute_canonical_row_to_display(row: tuple[str, ...], kind: ListKind) -> tuple[str, ...]:
    """Map a row built in canonical id order to the configured display order."""
    canon_ids = tuple(cid for cid, _ in CANONICAL_COLUMNS[kind])
    if len(row) != len(canon_ids):
        raise ValueError(f"row length {len(row)} != canonical {len(canon_ids)} for {kind!r}")
    order = local_list_column_order(kind)
    canon_map = dict(zip(canon_ids, row))
    return tuple(canon_map[i] for i in order)


def display_semantic_at(kind: ListKind, display_col: int) -> str:
    """Semantic column id for the given display column index."""
    order = local_list_column_order(kind)
    if display_col < 0 or display_col >= len(order):
        return ""
    return order[display_col]
