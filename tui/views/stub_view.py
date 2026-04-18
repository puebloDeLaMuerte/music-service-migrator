"""Stub view — placeholder for unimplemented features."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Static

from tui.views.base import BaseView


class StubView(BaseView):
    DEFAULT_CSS = """
    StubView { height: 1fr; width: 1fr; }
    #stub-msg {
        content-align: center middle;
        height: 1fr;
        color: $text-muted;
    }
    """

    def __init__(self, view_id: str) -> None:
        super().__init__()
        self._view_id = view_id

    def compose(self) -> ComposeResult:
        yield Static(
            f"[bold]{self._view_id}[/]\n\nNot yet implemented.",
            id="stub-msg",
            markup=True,
        )
