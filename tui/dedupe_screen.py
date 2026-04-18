"""TUI screen for 'data dedupe'."""

from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult
from textual.widgets import DataTable, Footer, Header, RichLog, Static

from tui.app import APP_TITLE


class DedupeApp(App):
    BINDINGS = [
        ("q", "quit", "Quit"),
    ]

    CSS = """
    #status {
        dock: bottom;
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    #table {
        height: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="table")
        yield Static("Loading…", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.title = APP_TITLE
        self.sub_title = "dedupe"

        table = self.query_one("#table", DataTable)
        table.add_columns("Track", "Artists", "Playlists", "Positions")
        table.cursor_type = "row"

        self.run_worker(self._do_task(), exclusive=True)

    async def _do_task(self) -> None:
        from common.store import load_library
        from spotify.dedupe import find_duplicates_across

        library = await asyncio.to_thread(load_library, "spotify")

        if not library.playlists:
            self.query_one("#status", Static).update(
                "No playlists found. Run 'spotify pull' first."
            )
            return

        dupes = await asyncio.to_thread(find_duplicates_across, library.playlists)

        table = self.query_one("#table", DataTable)

        if not dupes:
            self.query_one("#status", Static).update(
                "No cross-playlist duplicates found."
            )
            return

        for d in dupes:
            pl_names = ", ".join(sorted({name for name, _ in d.occurrences}))
            positions = ", ".join(f"{name} #{pos}" for name, pos in d.occurrences)
            table.add_row(d.track_name, d.artists, pl_names, positions)

        self.query_one("#status", Static).update(
            f"{len(dupes)} duplicate(s) found  ·  ↑↓ navigate  ·  q quit"
        )
