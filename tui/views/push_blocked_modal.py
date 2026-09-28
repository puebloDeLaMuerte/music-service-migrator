"""Explain why Push Now is blocked and send the user to Inspect Push Plan."""

from __future__ import annotations

from typing import ClassVar

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Static

from common.push.decisions import push_blocked_guidance


class PushBlockedModal(ModalScreen[bool]):
    """Dismisses with True when the user chooses to open Inspect Push Plan."""

    BINDINGS: ClassVar = [
        Binding("escape", "dismiss(False)", "Close", show=True),
        Binding("enter", "dismiss(True)", "Inspect", show=True),
        Binding("y", "dismiss(True)", "Inspect", show=False),
        Binding("n", "dismiss(False)", "Close", show=False),
    ]

    CSS = """
    PushBlockedModal { align: center middle; }
    #pb-box {
        width: 72;
        max-height: 80%;
        border: thick $warning;
        background: $surface;
        padding: 1 2;
    }
    #pb-title { text-style: bold; padding-bottom: 1; }
    #pb-body { height: auto; max-height: 1fr; }
    #pb-keys { color: $text-muted; padding-top: 1; }
    """

    def __init__(self, plan: dict, *, workspace_root=None) -> None:
        super().__init__()
        self._plan = plan
        self._root = workspace_root

    def compose(self) -> ComposeResult:
        with Vertical(id="pb-box"):
            yield Static("Push blocked — picks still needed", id="pb-title")
            yield Static(
                escape(push_blocked_guidance(self._plan, workspace_root=self._root)),
                id="pb-body",
            )
            yield Static(
                "[bold]Enter[/] or [bold]y[/] → open Inspect Push Plan   "
                "[bold]Esc[/] or [bold]n[/] → stay here",
                id="pb-keys",
                markup=True,
            )

    def action_dismiss(self, open_inspect: bool = False) -> None:
        self.dismiss(bool(open_inspect))
