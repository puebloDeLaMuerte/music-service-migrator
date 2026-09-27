"""Inspect Push Plan: settle ambiguous matches before Push Now.

Lists plan items that need (or already have) a decision. Picking a candidate
or excluding an item writes ``push_decisions.json``; the next dry-run — or
Push Now, which re-plans automatically — uses it.
"""

from __future__ import annotations

from typing import Any, ClassVar

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, ListItem, ListView, Static

from common.push.resolution_cache import EXCLUDE, decision_for, load_decisions, set_decision


def decision_rows(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Ambiguous items first, then items settled by an earlier decision."""
    items = plan.get("items") or []
    pending = [i for i in items if i["status"] == "ambiguous"]
    settled = [i for i in items if i["status"] == "excluded" or i.get("method") == "your_choice"]
    return pending + settled


class _Row(ListItem):
    def __init__(self, item: dict[str, Any], mark: str) -> None:
        self.item = item
        super().__init__(Label(self._text(mark), markup=True))

    def _text(self, mark: str) -> str:
        return f" {mark} [dim]{self.item['kind']}[/]  {escape(self.item['label'])}"

    def set_mark(self, mark: str) -> None:
        self.query_one(Label).update(self._text(mark))


class PushPlanModal(ModalScreen[bool]):
    """Returns True when any decision changed."""

    BINDINGS: ClassVar = [
        *(Binding(str(n), f"pick({n})", show=False) for n in range(1, 10)),
        Binding("x", "exclude", "Exclude", show=True),
        Binding("u", "clear", "Undo decision", show=True),
        Binding("escape", "close", "Close", show=True),
    ]

    CSS = """
    PushPlanModal { align: center middle; }
    #pp-box {
        width: 90%; height: 85%;
        border: thick $accent; background: $surface; padding: 0 1;
    }
    #pp-title { height: 1; text-style: bold; background: $background; padding: 0 1; }
    #pp-body { height: 1fr; }
    #pp-list { width: 45%; height: 1fr; border-right: solid $primary-background-lighten-2; }
    #pp-detail { width: 1fr; height: 1fr; padding: 1 2; overflow-y: auto; }
    #pp-keys { height: 1; color: $text-muted; padding: 0 1; }
    """

    def __init__(self, plan: dict[str, Any], *, workspace_root=None) -> None:
        super().__init__()
        self._plan = plan
        self._provider = plan["provider"]
        self._root = workspace_root
        self._rows = decision_rows(plan)
        self._decisions = load_decisions(workspace_root=workspace_root)
        self._changed = False

    # ── Layout ─────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        pending = sum(1 for r in self._rows if r["status"] == "ambiguous")
        title = f"Inspect Push Plan — {self._provider.capitalize()} · {pending} need a decision"
        with Vertical(id="pp-box"):
            yield Static(title, id="pp-title")
            with Horizontal(id="pp-body"):
                yield ListView(*(_Row(r, self._mark(r)) for r in self._rows), id="pp-list")
                yield Static("", id="pp-detail", markup=True)
            yield Static(
                r"↑↓ item  ·  \[1-9] pick match  ·  \[x] exclude  ·  \[u] undo  ·  ESC close",
                id="pp-keys",
                markup=True,
            )

    def on_mount(self) -> None:
        if not self._rows:
            self.query_one("#pp-detail", Static).update(
                "[green]Nothing needs a decision in this plan.[/]"
            )
            return
        lv = self.query_one("#pp-list", ListView)
        lv.index = 0
        lv.focus()
        self._show(self._rows[0])

    # ── State ──────────────────────────────────────────────────────

    def _choice(self, item: dict[str, Any]) -> str | None:
        return decision_for(self._decisions, self._provider, item["kind"], item["key"])

    def _mark(self, item: dict[str, Any]) -> str:
        choice = self._choice(item)
        if choice == EXCLUDE:
            return "[dim]✗[/]"
        if choice:
            return "[green]✓[/]"
        return "[bold yellow]?[/]"

    def _current(self) -> tuple[_Row, dict[str, Any]] | None:
        lv = self.query_one("#pp-list", ListView)
        row = lv.highlighted_child
        if isinstance(row, _Row):
            return row, row.item
        return None

    def _show(self, item: dict[str, Any]) -> None:
        choice = self._choice(item)
        lines = [f"[bold]{escape(item['label'])}[/]", f"[dim]{item['kind']}[/]", ""]
        if item.get("message"):
            lines += [escape(item["message"]), ""]
        cands = item.get("candidates") or []
        if cands:
            lines.append("Possible matches:")
            for n, c in enumerate(cands, 1):
                picked = " [green]← your pick[/]" if choice == c["ref"] else ""
                lines.append(f"  [bold]{n}[/]) {escape(c['display'])}  [dim]{round(c['score'] * 100)}%[/]{picked}")
            lines.append("")
        if choice == EXCLUDE:
            lines.append("[dim]Excluded — this item is skipped when pushing.[/]")
        elif choice and not cands:
            lines.append("[green]Settled by your earlier pick.[/] Press [bold]u[/] to undo it.")
        elif not choice:
            lines.append("[yellow]Pick a match with its number, or press [bold]x[/] to exclude.[/]")
        self.query_one("#pp-detail", Static).update("\n".join(lines))

    def _set(self, choice: str | None, display: str | None = None) -> None:
        cur = self._current()
        if cur is None:
            return
        row, item = cur
        set_decision(
            self._provider, item["kind"], item["key"], choice,
            display=display, workspace_root=self._root,
        )
        self._decisions = load_decisions(workspace_root=self._root)
        self._changed = True
        row.set_mark(self._mark(item))
        self._show(item)

    # ── Events / actions ───────────────────────────────────────────

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if isinstance(event.item, _Row):
            self._show(event.item.item)

    def action_pick(self, n: int) -> None:
        cur = self._current()
        if cur is None:
            return
        cands = cur[1].get("candidates") or []
        if 1 <= n <= len(cands):
            self._set(cands[n - 1]["ref"], cands[n - 1]["display"])

    def action_exclude(self) -> None:
        self._set(EXCLUDE)

    def action_clear(self) -> None:
        self._set(None)

    def action_close(self) -> None:
        self.dismiss(self._changed)
