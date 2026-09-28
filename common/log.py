"""Shared logging setup.

Call ``get_logger(__name__)`` from any module to get a consistently configured
logger that writes to both stderr and a rotating log file.
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

from common import config

_LOG_DIR = Path(config.get("LOG_DIR", "./logs"))
_initialised = False


def _init() -> None:
    global _initialised
    if _initialised:
        return

    if not _LOG_DIR.is_absolute():
        log_dir = config._PROJECT_ROOT / _LOG_DIR
    else:
        log_dir = _LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)

    level = getattr(logging, config.log_level().upper(), logging.INFO)

    fmt = logging.Formatter(
        "%(asctime)s  %(name)-30s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(fmt)

    file_handler = logging.FileHandler(log_dir / "migrator.log", encoding="utf-8")
    file_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)
    catalog_miss = _catalog_miss_filter()
    console.addFilter(catalog_miss)
    file_handler.addFilter(catalog_miss)

    root.addHandler(console)
    root.addHandler(file_handler)

    _quiet_expected_http_errors()

    _initialised = True


def _catalog_miss_filter() -> logging.Filter:
    """Drop expected catalog miss noise (tidalapi / spotipy) from log output."""
    tidal = re.compile(
        r"^(Request resulted in exception (404|400) |Track '.*' is unavailable|"
        r"No matching tracks found for ISRC |Invalid ISRC code )"
    )
    ours = ("common.", "tui.", "tests.", "data.")

    class _Filter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            if record.name.startswith(ours):
                return True
            msg = record.getMessage()
            if tidal.match(msg) or "Must be a valid 12-character ISRC" in msg:
                return False
            return True

    return _Filter()


def _quiet_expected_http_errors() -> None:
    """Drop spotipy's own error line for statuses we handle and report ourselves.

    spotipy logs every failed request at ERROR with the full URL and params.
    For 403/404 that is expected — Spotify refuses to list some playlists, and
    catalog lookups miss — and our callers already say what was skipped, so the
    raw line is noise in the app log. Anything else still comes through.
    """

    handled = re.compile(r"^HTTP Error for .* returned (403|404) due to")

    def drop_handled(record: logging.LogRecord) -> bool:
        return not handled.match(record.getMessage())

    logging.getLogger("spotipy.client").addFilter(drop_handled)


def get_logger(name: str) -> logging.Logger:
    _init()
    return logging.getLogger(name)
