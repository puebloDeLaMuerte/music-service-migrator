"""Shared logging setup.

Call ``get_logger(__name__)`` from any module to get a consistently configured
logger that writes to both stderr and a rotating log file.
"""

from __future__ import annotations

import logging
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
    root.addHandler(console)
    root.addHandler(file_handler)

    _initialised = True


def get_logger(name: str) -> logging.Logger:
    _init()
    return logging.getLogger(name)
