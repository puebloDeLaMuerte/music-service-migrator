"""Placeholder TUI screen for unimplemented commands."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Static

from tui.app import APP_TITLE


class StubApp(App):
    BINDINGS = [
        ("q", "quit", "Quit"),
    ]

    CSS = """
    #msg {
        content-align: center middle;
        height: 1fr;
        color: $text-muted;
    }
    """

    def __init__(self, command_name: str) -> None:
        super().__init__()
        self._command_name = command_name

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            f"[bold]{self._command_name}[/]\n\nNot yet implemented.",
            id="msg",
            markup=True,
        )
        yield Footer()

    def on_mount(self) -> None:
        self.title = APP_TITLE
        self.sub_title = self._command_name
