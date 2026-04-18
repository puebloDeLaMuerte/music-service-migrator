"""Dedupe view — shows duplicate tracks across playlists with action buttons."""

from __future__ import annotations

import asyncio

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Label, ListItem, ListView, Static

from tui.views.base import BaseView


class DedupeView(BaseView):
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
        width: 22;
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
                    ListItem(Label("  Remove older")),
                    ListItem(Label("  Keep in…")),
                    ListItem(Label("  Ignore")),
                    id="dedupe-actions",
                )
            with Vertical(id="dedupe-col-table"):
                yield Static("Duplicates", classes="dedupe-col-title")
                yield Static("", classes="dedupe-col-gap")
                yield DataTable(id="table")
        yield Static("Loading…", id="dedupe-status")

    def on_mount(self) -> None:
        table = self.query_one("#table", DataTable)
        table.add_columns("Playlists", "Track", "Artists", "Positions")
        table.cursor_type = "cell"
        self.run_worker(self._do_task(), group="dedupe-task")

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

    # ── Event handling ──────────────────────────────────────────────

    def on_data_table_cell_selected(
        self, event: DataTable.CellSelected
    ) -> None:
        self.query_one("#dedupe-status", Static).update(
            "  ←→ browse columns  ·  ← past first column for actions"
        )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "dedupe-actions":
            self.query_one("#dedupe-status", Static).update(
                "  [yellow]Coming soon — duplicate management "
                "not yet implemented.[/]"
            )
            event.stop()

    # ── Data loading ────────────────────────────────────────────────

    async def _do_task(self) -> None:
        from common.store import load_library
        from spotify.dedupe import find_duplicates_across

        library = await asyncio.to_thread(load_library, "spotify")

        if not library.playlists:
            self.query_one("#dedupe-status", Static).update(
                "No playlists found. Run 'spotify pull' first."
            )
            return

        dupes = await asyncio.to_thread(find_duplicates_across, library.playlists)
        table = self.query_one("#table", DataTable)

        if not dupes:
            self.query_one("#dedupe-status", Static).update(
                "No cross-playlist duplicates found."
            )
            return

        for d in dupes:
            pl_names = ", ".join(sorted({name for name, _ in d.occurrences}))
            positions = ", ".join(f"{name} #{pos}" for name, pos in d.occurrences)
            table.add_row(pl_names, d.track_name, d.artists, positions)

        self.query_one("#dedupe-status", Static).update(
            f"{len(dupes)} duplicate(s) found  ·  ↑↓ rows  ←→ columns  ·  "
            f"← past first column for actions"
        )
