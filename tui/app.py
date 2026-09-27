"""Base Textual utilities shared across all TUI components."""

from __future__ import annotations

import logging
import re

from rich.highlighter import Highlighter
from rich.style import Style
from rich.text import Text
from textual.widgets import RichLog, Static

APP_TITLE = "music-service-migrator"
APP_THEME = "tokyo-night"

_BLUE = "#7AA2F7"
_CYAN = "#7DCFFF"
_GREEN = "#9ECE6A"
_PURPLE = "#BB9AF7"
_ORANGE = "#FF9E64"
_BG = "#1A1B26"

LOGO_MARKUP = (
    f"[{_BLUE}]        ~ ~ ~ ~ ~         [{_ORANGE}]((( ((( ((([/][/]\n"
    f"[bold {_PURPLE}]          p M i g r a t o r[/]\n"
    f"[{_BLUE}]        ~ ~ ~ ~ ~         [{_ORANGE}]((( ((( ((([/][/]\n"
    f"[{_BLUE}]           ~ ~ ~             [{_ORANGE}]((( ((([/][/]\n"
    f"[{_BLUE}]            ~ ~               [{_ORANGE}]((( ([/][/]"
)


class AppBanner(Static):
    """Custom header banner with the pMigrator logo.

    Content is passed to Static.__init__ so the very first paint is correct
    (fixes the ghost-characters-until-mouseover bug).
    """

    DEFAULT_CSS = f"""
    AppBanner {{
        dock: top;
        width: 100%;
        height: 8;
        padding: 1 2 1 2;
        background: {_BG};
        content-align: center middle;
    }}
    """

    def __init__(self, subtitle: str = "") -> None:
        self._subtitle = subtitle
        super().__init__(self._build(), markup=True)

    def set_subtitle(self, subtitle: str) -> None:
        self._subtitle = subtitle
        self.update(self._build())

    def _build(self) -> str:
        content = LOGO_MARKUP
        if self._subtitle:
            content += f"\n[dim]{' ' * 40}{self._subtitle}[/]"
        return content


class LogHighlighter(Highlighter):
    """Highlight paths, URLs and quoted names in log output.

    Replaces Rich's ``ReprHighlighter``, whose magenta paths resolve to a red
    tone in this theme; red is reserved for errors. Styles are concrete colours
    rather than theme style names so they cannot be remapped by the ANSI theme.
    """

    _HIGHLIGHTS: tuple[tuple[re.Pattern[str], Style], ...] = (
        (re.compile(r"'[^'\n]*'|\"[^\"\n]*\""), Style(color=_GREEN)),
        (re.compile(r"(?:(?:~|\.{1,2})?/|\b[-\w.+@]+/)[-\w.+@/]*"), Style(color=_BLUE)),
        (re.compile(r"https?://[^\s<>\"']+"), Style(color=_CYAN, underline=True)),
    )

    def highlight(self, text: Text) -> None:
        plain = text.plain
        for pattern, style in self._HIGHLIGHTS:
            for match in pattern.finditer(plain):
                text.stylize(style, match.start(), match.end())


def app_rich_log(**kwargs) -> RichLog:
    """RichLog wired to :class:`LogHighlighter` (markup + highlighting on)."""
    kwargs.setdefault("markup", True)
    log = RichLog(highlight=True, **kwargs)
    log.highlighter = LogHighlighter()
    return log


class LogBridge(logging.Handler):
    """Logging handler that forwards records to a Textual RichLog widget."""

    def __init__(self, rich_log: RichLog) -> None:
        super().__init__()
        self._log = rich_log

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            markup = _log_level_markup(record.levelno, msg)
            self._log.write(markup)
        except Exception:
            self.handleError(record)


def _log_level_markup(levelno: int, msg: str) -> str:
    if levelno >= logging.ERROR:
        return f"[bold red]{msg}[/]"
    if levelno >= logging.WARNING:
        return f"[yellow]{msg}[/]"
    if levelno >= logging.INFO:
        return f"[dim]{msg}[/]"
    return f"[dim italic]{msg}[/]"
