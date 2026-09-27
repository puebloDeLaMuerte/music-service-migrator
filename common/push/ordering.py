"""Final track order for a remote playlist that already exists."""

from __future__ import annotations

from collections import Counter


def _occurrences(seq: list[str]) -> list[tuple[str, int]]:
    seen: Counter[str] = Counter()
    out = []
    for x in seq:
        out.append((x, seen[x]))
        seen[x] += 1
    return out


def merge_order(local: list[str], remote: list[str], *, drop: set[str] | None = None) -> list[str]:
    """Local items in local order; remote-only items kept next to their neighbours.

    Repeated ids are matched occurrence by occurrence, so a track listed twice
    locally appears twice. Each remote-only item stays directly after the
    nearest item before it on the remote side that is also local (or at the
    head when there is none). Remote-only ids in ``drop`` are removed.
    """
    drop = drop or set()
    loc = _occurrences(local)
    local_set = set(loc)
    after: dict[tuple[str, int] | None, list[tuple[str, int]]] = {}
    anchor: tuple[str, int] | None = None
    for item in _occurrences(remote):
        if item in local_set:
            anchor = item
            continue
        if item[0] in drop:
            continue
        after.setdefault(anchor, []).append(item)
    out = list(after.get(None, []))
    for item in loc:
        out.append(item)
        out.extend(after.get(item, []))
    return [x for x, _ in out]
