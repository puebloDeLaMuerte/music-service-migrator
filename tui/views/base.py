"""Base view classes for the unified TUI."""

from __future__ import annotations

import logging

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import RichLog

from tui.app import LogBridge


class BaseView(Container):
    """Base class for all content views mounted into MigratorApp."""

    DEFAULT_CSS = """
    BaseView { height: 1fr; width: 1fr; }
    """


class LogView(BaseView):
    """View with a RichLog that runs an async task with log bridging.

    Subclasses call ``_start_task()`` to begin.  This is NOT called
    automatically on mount so that views can show a confirmation first.
    """

    DEFAULT_CSS = """
    LogView { height: 1fr; width: 1fr; }
    #view-log { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield RichLog(highlight=True, markup=True, id="view-log")

    def _start_task(self) -> None:
        self.run_worker(self._do_task(), group="log-task")

    async def _do_task(self) -> None:
        log_widget = self.query_one("#view-log", RichLog)
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

    async def run_task(self, log_widget: RichLog) -> None:
        raise NotImplementedError
