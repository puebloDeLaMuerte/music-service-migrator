"""ISRC validation before catalog lookups."""

from __future__ import annotations

import re

_ISRC = re.compile(r"^[A-Z]{2}[A-Z0-9]{3}\d{7}$")


def valid_isrc(raw: str | None) -> bool:
    """True when *raw* is a 12-character ISRC (CC-XXX-YY-NNNNN without dashes)."""
    if not raw:
        return False
    return bool(_ISRC.match(raw.strip().upper().replace("-", "")))
