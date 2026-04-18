"""Base Textual app and utilities shared across all TUI screens."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, RichLog

if TYPE_CHECKING:
    pass

APP_TITLE = "music-service-migrator"


class LogBridge(logging.Handler):
    """Logging handler that forwards records to a Textual RichLog widget.

    Attach this to the root logger (or any parent) before running a worker so
    that log.info / log.warning etc. appear live in the TUI.
    """

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


class LogScreen(App):
    """Generic app with a full-screen RichLog, header and footer.

    Subclass this for commands that stream log output (pull, images).
    Override ``run_task()`` to do the actual work.
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
    ]

    def __init__(self, title: str = "", subtitle: str = "") -> None:
        super().__init__()
        self._screen_title = title
        self._screen_subtitle = subtitle

    def compose(self) -> ComposeResult:
        yield Header()
        yield RichLog(highlight=True, markup=True, id="log")
        yield Footer()

    def on_mount(self) -> None:
        self.title = APP_TITLE
        self.sub_title = self._screen_title
        self.run_worker(self._do_task(), exclusive=True)

    async def _do_task(self) -> None:
        log_widget = self.query_one("#log", RichLog)
        bridge = LogBridge(log_widget)
        bridge.setFormatter(logging.Formatter("%(message)s"))
        root = logging.getLogger()
        root.addHandler(bridge)
        try:
            await self.run_task(log_widget)
        except Exception as exc:
            log_widget.write(f"[bold red]Error: {exc}[/]")
        finally:
            root.removeHandler(bridge)
            self.sub_title = f"{self._screen_title} — done"

    async def run_task(self, log_widget: RichLog) -> None:
        raise NotImplementedError
