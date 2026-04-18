"""Dedupe view — cross-playlist duplicates: resolve, hide from list, trim playlists on disk."""

from __future__ import annotations

import asyncio
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Label, ListItem, ListView, Static

from data.dedupe_apply import (
    add_ignored_key,
    apply_remove_from_playlist,
    describe_keep_newer,
    describe_keep_older,
    duplicate_fingerprint,
    finalize_keep_only_in,
    persist_playlists,
    reload_and_find_dupes,
)
from spotify.dedupe import Duplicate
from tui.transient_status import TransientStatus
from tui.views.base import BaseView
from tui.views.p2a_view import ConfirmModal


class PlaylistPickModal(ModalScreen[str | None]):
    """Return the selected playlist name, or None if cancelled."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    CSS = """
    PlaylistPickModal { align: center middle; }
    #pick-box {
        width: 52;
        height: auto;
        max-height: 20;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    #pl-pick-list { height: auto; max-height: 14; }
    """

    def __init__(self, title: str, playlist_names: list[str]) -> None:
        super().__init__()
        self._title = title
        self._names = playlist_names

    def compose(self) -> ComposeResult:
        with Vertical(id="pick-box"):
            yield Static(self._title, markup=True)
            yield ListView(
                *[ListItem(Label(f"  {name}")) for name in self._names],
                id="pl-pick-list",
            )
            yield Static(
                "\n[dim]Enter = choose · ESC = cancel[/]",
                markup=True,
            )

    def on_mount(self) -> None:
        self.query_one("#pl-pick-list", ListView).focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "pl-pick-list":
            idx = event.list_view.index
            if idx is not None and 0 <= idx < len(self._names):
                self.dismiss(self._names[idx])
            event.stop()

    def action_cancel(self) -> None:
        self.dismiss(None)


_DEDUPE_ACTIONS = [
    "_act_keep_in",
    "_act_remove_from",
    "_act_keep_older",
    "_act_keep_newer",
    "_act_keep_all",
]

# Rich-escaped chord hints; matches BINDINGS: i/shift+i, o/shift+o, a.
_DEDUPE_ACTION_TOOLTIPS: tuple[str, ...] = (
    r"  [yellow]\[i] Keep in…: choose a playlist to keep the track in; "
    r"removed from other playlists in this group.[/]",
    r"  [yellow]\[I] Remove from… (Shift+i or key I): remove the track from one chosen playlist only.[/]",
    r"  [yellow]\[o] Keep older: confirm, then keep the track only where it was added earliest.[/]",
    r"  [yellow]\[O] Keep newer (Shift+o or key O): keep it only where it was added latest.[/]",
    r"  [yellow]\[a] Keep all: hide this group in the app (playlists unchanged; saved for later runs).[/]",
)


class DedupeView(BaseView):
    """Single-key shortcuts like P2A: i / I, o / O, a (see tooltips when an action row is focused)."""

    # Uppercase pairs: many terminals emit key "I"/"O", not "shift+i"/"shift+o".
    # priority=True so ListView/DataTable do not consume these before the view sees them.
    BINDINGS: ClassVar = [
        Binding("i", "dedupe_keep_in", show=False, priority=True),
        Binding("shift+i,I", "dedupe_remove_from", show=False, priority=True),
        Binding("o", "dedupe_keep_older", show=False, priority=True),
        Binding("shift+o,O", "dedupe_keep_newer", show=False, priority=True),
        Binding("a", "dedupe_keep_all", show=False, priority=True),
    ]

    DEFAULT_CSS = """
    DedupeView { height: 1fr; width: 1fr; }
    #dedupe-main { height: 1fr; }
    #dedupe-main > Vertical { height: 1fr; }
    .dedupe-col-title {
        padding: 0 1;
        height: 1;
        text-style: bold;
        color: $text;
        background: $surface;
    }
    .dedupe-col-gap {
        height: 1;
        background: $surface;
    }
    #dedupe-status {
        dock: bottom;
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    #dedupe-col-actions {
        width: 30;
        border-right: solid $primary-background-lighten-2;
    }
    #dedupe-col-actions #dedupe-actions { height: 1fr; }
    #dedupe-col-table { width: 1fr; }
    #dedupe-col-table #table { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="dedupe-main"):
            with Vertical(id="dedupe-col-actions"):
                yield Static("Actions", classes="dedupe-col-title")
                yield Static("", classes="dedupe-col-gap")
                yield ListView(
                    ListItem(Label(r"  \[i] Keep in…")),
                    ListItem(Label(r"  \[I] Remove from…")),
                    ListItem(Label(r"  \[o] Keep older")),
                    ListItem(Label(r"  \[O] Keep newer")),
                    ListItem(Label(r"  \[a] Keep all")),
                    id="dedupe-actions",
                )
            with Vertical(id="dedupe-col-table"):
                yield Static("Duplicates", classes="dedupe-col-title")
                yield Static("", classes="dedupe-col-gap")
                yield DataTable(id="table")
        yield Static("Loading…", id="dedupe-status", markup=True)

    def on_mount(self) -> None:
        self._dupes: list[Duplicate] = []
        self._status_line = TransientStatus(self.query_one("#dedupe-status", Static))
        self._status_line.set_baseline("Loading…")
        table = self.query_one("#table", DataTable)
        table.add_columns("Playlists", "Track", "Artists", "Positions")
        table.cursor_type = "cell"
        self.run_worker(self._do_task(), group="dedupe-task")

    def _selected_duplicate(self) -> Duplicate | None:
        table = self.query_one("#table", DataTable)
        row = table.cursor_row
        if row is None or row < 0 or row >= len(self._dupes):
            return None
        return self._dupes[row]

    def _playlist_choices(self, d: Duplicate) -> list[str]:
        return sorted({name for name, _ in d.occurrences})

    def _dispatch_action_at_index(self, idx: int) -> None:
        if idx < 0 or idx >= len(_DEDUPE_ACTIONS):
            return
        dup = self._selected_duplicate()
        if not dup:
            self._status_line.flash(
                "  [yellow]Select a duplicate row in the table first.[/]"
            )
            return
        method = getattr(self, _DEDUPE_ACTIONS[idx], None)
        if callable(method):
            method(dup)

    def action_dedupe_keep_in(self) -> None:
        self._dispatch_action_at_index(0)

    def action_dedupe_remove_from(self) -> None:
        self._dispatch_action_at_index(1)

    def action_dedupe_keep_older(self) -> None:
        self._dispatch_action_at_index(2)

    def action_dedupe_keep_newer(self) -> None:
        self._dispatch_action_at_index(3)

    def action_dedupe_keep_all(self) -> None:
        self._dispatch_action_at_index(4)

    # ── Column navigation (called by MigratorApp) ─────────────────

    def zone_left(self) -> None:
        focused = self.app.focused
        fid = getattr(focused, "id", None)
        if fid == "table":
            table = self.query_one("#table", DataTable)
            if table.cursor_column <= 0:
                self.query_one("#dedupe-actions").focus()
            else:
                table.action_cursor_left()
        elif fid == "dedupe-actions":
            self.app._focus_sidebar()
        else:
            self.app._focus_sidebar()

    def zone_right(self) -> None:
        focused = self.app.focused
        fid = getattr(focused, "id", None)
        if fid == "dedupe-actions":
            self.query_one("#table").focus()
        elif fid == "table":
            table = self.query_one("#table", DataTable)
            last_col = len(table.ordered_columns) - 1
            if table.cursor_column < last_col:
                table.action_cursor_right()

    # ── Events ──────────────────────────────────────────────────────

    def on_data_table_cell_selected(
        self, event: DataTable.CellSelected
    ) -> None:
        self._status_line.set_baseline(
            r"  ←→ columns  ·  \[i]/\[I] \[o]/\[O] \[a] run action on selected row  ·  "
            r"← actions list"
        )

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id == "dedupe-actions":
            idx = event.list_view.index
            if idx is not None and 0 <= idx < len(_DEDUPE_ACTION_TOOLTIPS):
                self._status_line.flash(_DEDUPE_ACTION_TOOLTIPS[idx])
            event.stop()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id != "dedupe-actions":
            return
        idx = event.list_view.index
        if idx is None or idx >= len(_DEDUPE_ACTIONS):
            event.stop()
            return
        self._dispatch_action_at_index(idx)
        event.stop()

    def _act_keep_in(self, d: Duplicate) -> None:
        names = self._playlist_choices(d)
        if len(names) < 2:
            self._status_line.flash("  [yellow]Need at least two playlists.[/]")
            return

        self.app.push_screen(
            PlaylistPickModal(
                "[bold]Keep in…[/]\n\n"
                "Choose the playlist that should [bold]keep[/] this track. "
                "It will be removed from all other playlists in this duplicate group.",
                names,
            ),
            lambda choice: self._on_keep_in_chosen(d, choice),
        )

    def _on_keep_in_chosen(self, d: Duplicate, choice: str | None) -> None:
        if not choice:
            return
        self.run_worker(self._wk_keep_in(d, choice), group="dedupe-apply")

    async def _wk_keep_in(self, d: Duplicate, keep_name: str) -> None:
        def work():
            from common.store import load_workspace

            lib = load_workspace()
            return finalize_keep_only_in(lib, d, keep_name)

        try:
            msg = await asyncio.to_thread(work)
            self._status_line.set_baseline(f"  {msg}")
        except Exception as exc:
            self._status_line.flash(f"  [yellow]Error: {exc}[/]")
            return
        await self._reload_dupes()

    def _act_remove_from(self, d: Duplicate) -> None:
        names = self._playlist_choices(d)
        self.app.push_screen(
            PlaylistPickModal(
                "[bold]Remove from…[/]\n\n"
                "Choose the playlist to [bold]remove[/] this track from. "
                "Other playlists in the group stay unchanged.",
                names,
            ),
            lambda choice: self._on_remove_from_chosen(d, choice),
        )

    def _on_remove_from_chosen(self, d: Duplicate, choice: str | None) -> None:
        if not choice:
            return
        self.run_worker(self._wk_remove_from(d, choice), group="dedupe-apply")

    async def _wk_remove_from(self, d: Duplicate, remove_name: str) -> None:
        def work():
            from common.store import load_workspace

            lib = load_workspace()
            changed = apply_remove_from_playlist(lib, d, remove_name)
            persist_playlists(lib, changed)

        try:
            await asyncio.to_thread(work)
            self._status_line.set_baseline(f"  Removed from {remove_name} only.")
        except Exception as exc:
            self._status_line.flash(f"  [yellow]Error: {exc}[/]")
            return
        await self._reload_dupes()

    def _act_keep_older(self, d: Duplicate) -> None:
        self.run_worker(self._wk_describe_older(d), group="dedupe-desc")

    async def _wk_describe_older(self, d: Duplicate) -> None:
        def desc():
            from common.store import load_workspace

            lib = load_workspace()
            return describe_keep_older(lib, d)

        try:
            body, keep_pl = await asyncio.to_thread(desc)
        except Exception as exc:
            self._status_line.flash(f"  [yellow]{exc}[/]")
            return

        self.app.push_screen(
            ConfirmModal(body),
            lambda ok: self._on_keep_age_confirmed(ok, d, keep_pl, older=True),
        )

    def _act_keep_newer(self, d: Duplicate) -> None:
        self.run_worker(self._wk_describe_newer(d), group="dedupe-desc")

    async def _wk_describe_newer(self, d: Duplicate) -> None:
        def desc():
            from common.store import load_workspace

            lib = load_workspace()
            return describe_keep_newer(lib, d)

        try:
            body, keep_pl = await asyncio.to_thread(desc)
        except Exception as exc:
            self._status_line.flash(f"  [yellow]{exc}[/]")
            return

        self.app.push_screen(
            ConfirmModal(body),
            lambda ok: self._on_keep_age_confirmed(ok, d, keep_pl, older=False),
        )

    def _on_keep_age_confirmed(
        self, ok: bool, d: Duplicate, keep_pl: str, *, older: bool
    ) -> None:
        if not ok:
            return
        self.run_worker(
            self._wk_apply_age(d, keep_pl, older=older),
            group="dedupe-apply",
        )

    async def _wk_apply_age(self, d: Duplicate, keep_pl: str, *, older: bool) -> None:
        _ = older

        def work():
            from common.store import load_workspace

            lib = load_workspace()
            return finalize_keep_only_in(lib, d, keep_pl)

        try:
            msg = await asyncio.to_thread(work)
            self._status_line.set_baseline(f"  {msg}")
        except Exception as exc:
            self._status_line.flash(f"  [yellow]Error: {exc}[/]")
            return
        await self._reload_dupes()

    def _act_keep_all(self, d: Duplicate) -> None:
        fp = duplicate_fingerprint(d)
        self.run_worker(self._wk_keep_all(fp), group="dedupe-keep-all")

    async def _wk_keep_all(self, fp: str) -> None:
        def work():
            add_ignored_key(fp)

        try:
            await asyncio.to_thread(work)
            self._status_line.set_baseline(
                "  Kept all playlists as-is; hid this row (re-shows if removed from "
                "dedupe_ignored.json)."
            )
        except Exception as exc:
            self._status_line.flash(f"  [yellow]Error: {exc}[/]")
            return
        await self._reload_dupes()

    async def _reload_dupes(self) -> None:
        def work():
            return reload_and_find_dupes()

        try:
            _, dupes = await asyncio.to_thread(work)
        except Exception as exc:
            self._status_line.flash(f"  [yellow]Reload error: {exc}[/]")
            return
        self._dupes = dupes
        table = self.query_one("#table", DataTable)
        prev_row = int(table.cursor_row)
        prev_col = int(table.cursor_column)
        n_cols = len(table.ordered_columns)
        table.clear()
        for d in dupes:
            pl_names = ", ".join(sorted({name for name, _ in d.occurrences}))
            positions = ", ".join(f"{name} #{pos}" for name, pos in d.occurrences)
            table.add_row(pl_names, d.track_name, d.artists, positions)
        if not dupes:
            self._status_line.set_baseline(
                "No cross-playlist duplicates left (or all hidden via Keep all)."
            )
        else:
            self._status_line.set_baseline(
                r"  "
                f"{len(dupes)} duplicate(s)  ·  "
                r"\[i]/\[I] keep in / remove · \[o]/\[O] older / newer · \[a] keep all · "
                r"↑↓ rows  ←→  ← actions"
            )
            target_row = min(max(0, prev_row - 1), len(dupes) - 1)
            target_col = min(max(0, prev_col), n_cols - 1) if n_cols else 0

            def _move_cursor() -> None:
                dt = self.query_one("#table", DataTable)
                dt.move_cursor(row=target_row, column=target_col, scroll=True)

            self.call_after_refresh(_move_cursor)

    async def _do_task(self) -> None:
        try:
            _, dupes = await asyncio.to_thread(reload_and_find_dupes)
        except FileNotFoundError:
            self._status_line.set_baseline(
                "No workspace on disk. Run Spotify → Pull first."
            )
            return
        except Exception as exc:
            self._status_line.set_baseline(f"Error: {exc}")
            return

        self._dupes = dupes
        table = self.query_one("#table", DataTable)

        if not dupes:
            self._status_line.set_baseline(
                "No cross-playlist duplicates found (or all hidden via Keep all)."
            )
            return

        for d in dupes:
            pl_names = ", ".join(sorted({name for name, _ in d.occurrences}))
            positions = ", ".join(f"{name} #{pos}" for name, pos in d.occurrences)
            table.add_row(pl_names, d.track_name, d.artists, positions)

        self._status_line.set_baseline(
            r"  "
            f"{len(dupes)} duplicate(s)  ·  "
            r"\[i]/\[I] keep in / remove · \[o]/\[O] older / newer · \[a] keep all · "
            r"↑↓ rows  ←→  ← actions"
        )
