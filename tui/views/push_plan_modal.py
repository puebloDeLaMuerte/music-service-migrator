"""Inspect Push Plan — read the plan and settle ambiguous matches.

Three sections: a summary of what the plan would do, the full report (the same
text the dry run printed, kept so it can be re-read any time), and the items
that need a decision. Picking a candidate or excluding an item writes
``push_decisions.json``; the next dry run — or Push Now, which re-plans
automatically — uses it.

``←→`` moves between the matches of one item; the selected one shows its link
and can be opened in a browser (``o``) or copied (``c``). The app captures the
mouse, so a printed URL is otherwise neither clickable nor selectable.
"""

from __future__ import annotations

import shutil
import subprocess
import webbrowser
from typing import Any, ClassVar, NamedTuple
from urllib.parse import urlparse

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, ListItem, ListView, Static

from common.push.report import (
    conflict_context,
    format_plan_details,
    plan_created,
    plan_title,
    plan_verdict,
    summary_rows,
)
from common.push.resolution_cache import EXCLUDE, decision_for, load_decisions, set_decision


_CLIPBOARD_TOOLS = (
    ["pbcopy"],
    ["wl-copy"],
    ["xclip", "-selection", "clipboard"],
    ["xsel", "--clipboard", "--input"],
)


def _to_clipboard(text: str, app: Any) -> bool:
    """Put *text* on the system clipboard. Returns False if no route worked.

    A local clipboard tool is tried first because Textual's escape-sequence
    route is silently ignored by some terminals (macOS Terminal among them).
    """
    for cmd in _CLIPBOARD_TOOLS:
        if shutil.which(cmd[0]) is None:
            continue
        try:
            subprocess.run(cmd, input=text.encode(), check=True, timeout=5)
            return True
        except (OSError, subprocess.SubprocessError):
            continue
    try:
        app.copy_to_clipboard(text)
        return True
    except Exception:
        return False


class InspectResult(NamedTuple):
    """What the user did in the modal: settled matches, and/or asked to push."""

    changed: bool
    push: bool = False


def decision_rows(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Ambiguous items first, then items settled by an earlier decision."""
    items = plan.get("items") or []
    pending = [i for i in items if i["status"] == "ambiguous"]
    settled = [i for i in items if i["status"] == "excluded" or i.get("method") == "your_choice"]
    return pending + settled


class _Static(ListItem):
    """Non-selectable row: section header or placeholder."""

    def __init__(self, label: str) -> None:
        super().__init__(Label(label, markup=True), disabled=True)


class _PageRow(ListItem):
    def __init__(self, page: str, label: str, *, disabled: bool = False) -> None:
        self.page = page
        super().__init__(Label(f"  {label}", markup=True), disabled=disabled)

    def relabel(self, label: str, *, disabled: bool) -> None:
        self.disabled = disabled
        self.query_one(Label).update(f"  {label}")


class _Row(ListItem):
    def __init__(self, item: dict[str, Any], mark: str) -> None:
        self.item = item
        super().__init__(Label(self._text(mark), markup=True))

    def _text(self, mark: str) -> str:
        return f" {mark} [dim]{self.item['kind']}[/]  {escape(self.item['label'])}"

    def set_mark(self, mark: str) -> None:
        self.query_one(Label).update(self._text(mark))


class PushPlanModal(ModalScreen[InspectResult]):
    """Returns what the user settled here, and whether they asked to push."""

    BINDINGS: ClassVar = [
        *(Binding(str(n), f"pick({n})", show=False) for n in range(1, 10)),
        Binding("right", "candidate(1)", "Next match", show=False),
        Binding("left", "candidate(-1)", "Previous match", show=False),
        Binding("o", "open_link", "Open in browser", show=True),
        Binding("c", "copy_link", "Copy link", show=True),
        Binding("x", "exclude", "Exclude", show=True),
        Binding("u", "clear", "Undo decision", show=True),
        Binding("pagedown", "scroll(1)", "Scroll", show=True, priority=True),
        Binding("pageup", "scroll(-1)", "Scroll", show=False, priority=True),
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
    #pp-list {
        width: 34%; min-width: 24; max-width: 46; height: 1fr;
        border-right: solid $primary-background-lighten-2;
    }
    #pp-list > ListItem:disabled Label { color: $text-disabled; }
    #pp-scroll { width: 1fr; height: 1fr; padding: 1 2; }
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
        self._cursor = 0
        self._flash: str | None = None

    # ── Layout ─────────────────────────────────────────────────────

    def _pending(self) -> int:
        """Ambiguous items you have not settled yet — the live count, not the plan's."""
        return sum(
            1 for r in self._rows if r["status"] == "ambiguous" and not self._choice(r)
        )

    def _settled_by_you(self) -> int:
        """Conflicts already pinned: earlier picks, exclusions, or a pick just now."""
        n = 0
        for r in self._rows:
            if r["status"] == "ambiguous":
                if self._choice(r):
                    n += 1
            elif r["status"] == "excluded" or r.get("method") == "your_choice":
                n += 1
        return n

    def _push_label(self, pending: int) -> str:
        return "Push now" if pending else "[bold green]Push now[/]"

    def _menu_items(self) -> list[ListItem]:
        pending = self._pending()
        self._push_row = _PageRow(
            "push", self._push_label(pending), disabled=bool(pending)
        )
        self._decisions_header = _Static(self._decisions_label(pending))
        items: list[ListItem] = [
            _Static("  [bold dim]— plan —[/]"),
            _PageRow("summary", "Summary"),
            _PageRow("report", "Full report"),
            self._push_row,
            _Static(" "),
            self._decisions_header,
        ]
        if self._rows:
            items += [_Row(r, self._mark(r)) for r in self._rows]
        else:
            items.append(_Static("  [dim](nothing to decide)[/]"))
        return items

    @staticmethod
    def _decisions_label(pending: int) -> str:
        state = f"{pending} open" if pending else "all settled"
        return f"  [bold dim]— decisions ({state}) —[/]"

    def _refresh_state(self) -> None:
        """Keep the Push now row, the section header and the summary in step."""
        pending = self._pending()
        self._push_row.relabel(self._push_label(pending), disabled=bool(pending))
        self._decisions_header.query_one(Label).update(self._decisions_label(pending))

    def compose(self) -> ComposeResult:
        built = plan_created(self._plan)
        title = f"Push plan — {plan_title(self._plan)}"
        if built:
            title += f" · built {built}"
        with Vertical(id="pp-box"):
            yield Static(title, id="pp-title")
            with Horizontal(id="pp-body"):
                yield ListView(*self._menu_items(), id="pp-list")
                with VerticalScroll(id="pp-scroll"):
                    yield Static("", id="pp-detail", markup=True)
            yield Static(
                r"↑↓ item  ·  ←→ match  ·  Enter pick  ·  \[o] open  ·  \[c] copy  "
                r"·  \[x] exclude  ·  \[u] undo  ·  ESC close",
                id="pp-keys",
                markup=True,
            )

    def on_mount(self) -> None:
        lv = self.query_one("#pp-list", ListView)
        lv.index = 1
        lv.focus()
        self._show_page("summary")

    # ── Pages ──────────────────────────────────────────────────────

    def _write(self, markup: str) -> None:
        self.query_one("#pp-detail", Static).update(markup)
        self.query_one("#pp-scroll", VerticalScroll).scroll_home(animate=False)

    def _verdict_lines(self, pending: int, by_you: int) -> list[str]:
        """The plan's verdict, plus how many conflicts your past picks already settled."""
        lines = [escape(s) for s in conflict_context(pending, by_you)]
        if lines:
            if pending:
                lines[1] = f"[bold yellow]{lines[1]}[/]"
            else:
                lines[0] = f"[bold green]{lines[0]}[/]"
            lines.append("")
        if pending:
            lines.append(
                f"[bold yellow]Blocked: {pending} item(s) need your decision — "
                "listed below.[/]"
            )
            return lines
        if by_you:
            lines += [
                "[bold green]Ready to push.[/]",
                "",
                "[dim]The numbers above are from the dry run. [bold]Push now[/] (left, "
                "under [italic]plan[/]) plans again with your picks, then asks you to "
                "confirm before anything is written.[/]",
            ]
            return lines
        verdict = plan_verdict(self._plan)
        colour = "green" if (self._plan.get("summary") or {}).get("can_apply") else "bold yellow"
        lines.append(f"[{colour}]{escape(verdict)}[/]")
        return lines

    def _summary_markup(self) -> str:
        provider = self._provider.capitalize()
        pending = self._pending()
        by_you = self._settled_by_you()
        built = plan_created(self._plan)
        lines = [f"[bold]Push plan — {plan_title(self._plan)}[/]", ""]
        when = f", {built}" if built else ""
        lines.append(f"Pushes Local Data to [bold]{provider}[/]")
        lines.append(f"[dim]as Local Data was when the plan was built{when}.[/]")
        lines.append("")
        for label, value in summary_rows(self._plan):
            accent = "bold"
            if label == "Need your decision":
                value = str(pending)
                accent = "bold yellow" if pending else "bold"
            elif label == "Settled by you":
                value = str(by_you)
                accent = "bold green" if by_you else "bold"
            lines.append(f"  [dim]{label:<22}[/][{accent}]{escape(value)}[/]")
        lines.append("")
        lines += self._verdict_lines(pending, by_you)
        lines.append("")
        lines.append(
            "[dim]Full report — every playlist, match and warning — is on the next page. "
            "Items needing a decision are listed below it.[/]"
        )
        return "\n".join(lines)

    def _report_markup(self) -> str:
        return (
            "[bold]Full report[/]\n"
            "[dim]Same text the dry run printed; kept with the plan.[/]\n\n"
            f"{escape(format_plan_details(self._plan))}"
        )

    def _show_page(self, page: str) -> None:
        self._write(self._summary_markup() if page == "summary" else self._report_markup())

    # ── Decisions ──────────────────────────────────────────────────

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
        row = self.query_one("#pp-list", ListView).highlighted_child
        return (row, row.item) if isinstance(row, _Row) else None

    def _show_item(self, item: dict[str, Any]) -> None:
        choice = self._choice(item)
        cands = item.get("candidates") or []
        self._cursor = max(0, min(self._cursor, len(cands) - 1))
        lines = [f"[bold]{escape(item['label'])}[/]", f"[dim]{item['kind']}[/]", ""]
        if item.get("message"):
            lines += [escape(item["message"]), ""]
        if cands:
            lines.append("Possible matches:")
            for n, c in enumerate(cands, 1):
                here = n - 1 == self._cursor
                picked = " [green]← your pick[/]" if choice == c["ref"] else ""
                name = escape(c["display"])
                lines.append(
                    f"  {'[reverse]' if here else ''}[bold]{n}[/]) {name}"
                    f"{'[/reverse]' if here else ''}  [dim]{round(c['score'] * 100)}%[/]{picked}"
                )
                if c.get("detail"):
                    lines.append(f"     [dim]{escape(c['detail'])}[/]")
                if here and c.get("url"):
                    # Only for the selected match, so o / c have one clear target.
                    # Quoted because Textual markup would choke on the "https:" colon.
                    url = escape(c["url"])
                    lines.append(f'     [link="{url}"]{url}[/link]')
                    lines.append("     [dim]\\[o] open in browser · \\[c] copy link[/]")
                lines.append("")
        if choice == EXCLUDE:
            lines.append("[dim]Excluded — this item is skipped when pushing.[/]")
        elif choice and not cands:
            lines.append("[green]Settled by your earlier pick.[/] Press [bold]u[/] to undo it.")
        elif not choice:
            lines.append(
                "[yellow][bold]Enter[/] picks the selected match · "
                "[bold]x[/] excludes this item.[/]"
            )
        if self._flash:
            lines += ["", self._flash]
        self._write("\n".join(lines))

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
        self._refresh_state()
        self._show_item(item)

    # ── Events / actions ───────────────────────────────────────────

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        item = event.item
        self._cursor = 0
        self._flash = None
        if isinstance(item, _PageRow):
            self._show_page(item.page)
        elif isinstance(item, _Row):
            self._show_item(item.item)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Enter picks the selected match, or starts the push from the plan section."""
        if isinstance(event.item, _Row):
            self.action_pick(self._cursor + 1)
        elif isinstance(event.item, _PageRow) and event.item.page == "push":
            self.dismiss(InspectResult(changed=self._changed, push=True))

    def action_pick(self, n: int) -> None:
        cur = self._current()
        if cur is None:
            return
        cands = cur[1].get("candidates") or []
        if 1 <= n <= len(cands):
            self._cursor = n - 1
            self._set(cands[n - 1]["ref"], cands[n - 1]["display"])

    def action_candidate(self, step: int) -> None:
        cur = self._current()
        if cur is None:
            return
        cands = cur[1].get("candidates") or []
        if len(cands) > 1:
            self._cursor = (self._cursor + step) % len(cands)
            self._flash = None
            self._show_item(cur[1])

    def _selected_candidate(self) -> dict[str, Any] | None:
        cur = self._current()
        if cur is None:
            return None
        cands = cur[1].get("candidates") or []
        return cands[self._cursor] if 0 <= self._cursor < len(cands) else None

    def action_open_link(self) -> None:
        cand = self._selected_candidate()
        if cand is None:
            return
        url = cand.get("url") or ""
        if urlparse(url).scheme in ("http", "https"):
            webbrowser.open(url)
            self._flash = f"[green]Opened {escape(cand['display'])} in your browser.[/]"
        else:
            self._flash = "[yellow]This match has no link.[/]"
        self._show_item(self._current()[1])
        self.query_one("#pp-list", ListView).focus()

    def action_copy_link(self) -> None:
        cand = self._selected_candidate()
        if cand is None:
            return
        text = cand.get("url") or cand.get("display") or ""
        what = "Link" if cand.get("url") else "Name"
        if not text:
            return
        if _to_clipboard(text, self.app):
            self._flash = f"[green]{what} copied:[/] [dim]{escape(text)}[/]"
        else:
            self._flash = (
                "[yellow]Could not reach the clipboard. Hold [bold]⌥ Option[/] while "
                "selecting to copy with the mouse instead.[/]"
            )
        self._show_item(self._current()[1])

    def action_exclude(self) -> None:
        self._set(EXCLUDE)

    def action_clear(self) -> None:
        self._set(None)

    def action_scroll(self, direction: int) -> None:
        pane = self.query_one("#pp-scroll", VerticalScroll)
        if direction > 0:
            pane.scroll_page_down(animate=False)
        else:
            pane.scroll_page_up(animate=False)

    def action_close(self) -> None:
        self.dismiss(InspectResult(changed=self._changed))
