"""Browse saved albums, followed artists, or liked songs from the local export; remove entries."""

from __future__ import annotations

import asyncio
from typing import ClassVar, Literal

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Label, ListItem, ListView, Static

from common.models import Library
from common.store import load_library, save_library_auxiliary_data
from tui.transient_status import TransientStatus
from tui.views.base import BaseView
from tui.views.p2a_view import ConfirmModal

ListKind = Literal["albums", "artists", "songs"]

_SERVICE = "spotify"

_KIND_META: dict[ListKind, dict] = {
    "albums": {
        "menu_title": "Saved albums",
        "table_title": "Albums",
        "columns": ("Album", "Artists"),
        "empty": "No saved albums in the export. Run Spotify pull first.",
        "attr": "saved_albums",
        "label_fn": lambda sa: sa.album.name,
        "confirm_prefix": "Remove album",
        "rows": lambda lib: [
            (
                sa.album.name,
                _fmt_artists(sa.album.artists),
            )
            for sa in lib.saved_albums
        ],
    },
    "artists": {
        "menu_title": "Saved artists",
        "table_title": "Artists",
        "columns": ("Artist",),
        "empty": "No followed artists in the export. Run Spotify pull first.",
        "attr": "followed_artists",
        "label_fn": lambda fa: fa.artist.name,
        "confirm_prefix": "Remove artist",
        "rows": lambda lib: [(fa.artist.name,) for fa in lib.followed_artists],
    },
    "songs": {
        "menu_title": "Saved songs",
        "table_title": "Songs",
        "columns": ("Track", "Artists", "Album"),
        "empty": "No liked songs in the export. Run Spotify pull first.",
        "attr": "liked_songs",
        "label_fn": lambda pt: pt.track.name,
        "confirm_prefix": "Remove track",
        "rows": lambda lib: [
            (
                pt.track.name,
                _fmt_artists(pt.track.artists),
                pt.track.album.name if pt.track.album else "",
            )
            for pt in lib.liked_songs
        ],
    },
}


def _fmt_artists(artists) -> str:
    return ", ".join(a.name for a in artists) if artists else ""


class LocalLibraryListView(BaseView):
    """One of: saved albums, followed artists, liked songs — read from local JSON."""

    BINDINGS: ClassVar = [
        Binding("r", "remove", show=False, priority=True),
    ]

    DEFAULT_CSS = """
    LocalLibraryListView { height: 1fr; width: 1fr; }
    #local-main { height: 1fr; }
    #local-main > Vertical { height: 1fr; }
    .local-col-title {
        padding: 0 1;
        height: 1;
        text-style: bold;
        color: $text;
        background: $surface;
    }
    .local-col-gap {
        height: 1;
        background: $surface;
    }
    #local-col-actions {
        width: 22;
        border-right: solid $primary-background-lighten-2;
    }
    #local-col-actions #local-actions { height: 1fr; }
    #local-col-table { width: 1fr; }
    #local-table { height: 1fr; }
    #local-status {
        dock: bottom;
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    """

    def __init__(self, kind: ListKind) -> None:
        super().__init__()
        if kind not in _KIND_META:
            raise ValueError(f"Unknown list kind: {kind!r}")
        self._kind = kind
        self._meta = _KIND_META[kind]

    def compose(self) -> ComposeResult:
        with Horizontal(id="local-main"):
            with Vertical(id="local-col-actions"):
                yield Static("Actions", classes="local-col-title")
                yield Static("", classes="local-col-gap")
                yield ListView(
                    ListItem(Label(r"  \[r] Remove")),
                    id="local-actions",
                )
            with Vertical(id="local-col-table"):
                yield Static(self._meta["table_title"], classes="local-col-title")
                yield Static("", classes="local-col-gap")
                yield DataTable(id="local-table")
        yield Static("", id="local-status", markup=True)

    def on_mount(self) -> None:
        self._lib: Library | None = None
        self._status = TransientStatus(self.query_one("#local-status", Static))
        self._status.set_baseline("Loading…")
        table = self.query_one("#local-table", DataTable)
        for c in self._meta["columns"]:
            table.add_column(c)
        table.cursor_type = "cell"
        self.run_worker(self._load_task(), group="local-list-load")

    def _rows_for_table(self, lib: Library) -> list[tuple]:
        return list(self._meta["rows"](lib))

    def _list_len(self, lib: Library) -> int:
        return len(getattr(lib, self._meta["attr"]))

    def _pop_at(self, lib: Library, index: int) -> None:
        getattr(lib, self._meta["attr"]).pop(index)

    def _describe_row(self, lib: Library, index: int) -> str:
        seq = getattr(lib, self._meta["attr"])
        item = seq[index]
        return self._meta["label_fn"](item)

    async def _load_task(self) -> None:
        try:
            lib = await asyncio.to_thread(load_library, _SERVICE)
        except FileNotFoundError:
            self._status.set_baseline(
                "No library on disk. Run Spotify pull first."
            )
            return
        except Exception as exc:
            self._status.set_baseline(f"Error: {exc}")
            return

        self._lib = lib
        self._fill_table(lib)

    def _fill_table(self, lib: Library) -> None:
        table = self.query_one("#local-table", DataTable)
        prev_row = int(table.cursor_row)
        prev_col = int(table.cursor_column)
        n_cols = len(table.ordered_columns)
        table.clear()
        rows = self._rows_for_table(lib)
        for row in rows:
            table.add_row(*row)
        n = len(rows)
        if n == 0:
            self._status.set_baseline(f"  {self._meta['empty']}")
            return
        self._status.set_baseline(
            f"  {n} row(s)  ·  "
            + r"\[r] remove  ·  ↑↓ ←→  ·  ← actions"
        )
        target_row = min(max(0, prev_row - 1), n - 1) if prev_row >= 0 else 0
        target_col = min(max(0, prev_col), n_cols - 1) if n_cols else 0

        def _move() -> None:
            t = self.query_one("#local-table", DataTable)
            t.move_cursor(row=target_row, column=target_col, scroll=True)

        self.call_after_refresh(_move)

    def _current_index(self) -> int | None:
        table = self.query_one("#local-table", DataTable)
        r = table.cursor_row
        if self._lib is None or r is None or r < 0:
            return None
        if r >= self._list_len(self._lib):
            return None
        return r

    # ── Zone navigation ────────────────────────────────────────────

    def zone_left(self) -> None:
        fid = getattr(self.app.focused, "id", None)
        if fid == "local-table":
            table = self.query_one("#local-table", DataTable)
            if table.cursor_column <= 0:
                self.query_one("#local-actions").focus()
            else:
                table.action_cursor_left()
        elif fid == "local-actions":
            self.app._focus_sidebar()
        else:
            self.app._focus_sidebar()

    def zone_right(self) -> None:
        fid = getattr(self.app.focused, "id", None)
        if fid == "local-actions":
            self.query_one("#local-table").focus()
        elif fid == "local-table":
            table = self.query_one("#local-table", DataTable)
            last_col = len(table.ordered_columns) - 1
            if table.cursor_column < last_col:
                table.action_cursor_right()

    # ── Events ─────────────────────────────────────────────────────

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id == "local-actions":
            self._status.flash(
                r"  [yellow]\[r] Remove: drop this row from the saved export on disk "
                r"(Spotify is unchanged until you push).[/]"
            )
            event.stop()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id != "local-actions":
            return
        self.action_remove()
        event.stop()

    def action_remove(self) -> None:
        if self._lib is None:
            self._status.flash("  [yellow]Still loading…[/]")
            return
        idx = self._current_index()
        if idx is None:
            self._status.flash("  [yellow]Select a row first.[/]")
            return
        label = self._describe_row(self._lib, idx)
        prefix = self._meta["confirm_prefix"]
        body = (
            f"[bold]{prefix}[/]\n\n[bold]{label}[/]\n\n"
            "This updates your local export only (not Spotify).\n\n"
            "Press [bold]y[/] to confirm or [bold]n[/] / ESC to cancel."
        )
        self.app.push_screen(ConfirmModal(body), lambda ok: self._on_remove_ok(ok))

    def _on_remove_ok(self, ok: bool) -> None:
        if not ok or self._lib is None:
            return
        idx = self._current_index()
        if idx is None:
            return
        self.run_worker(self._wk_remove(idx), group="local-list-remove")

    async def _wk_remove(self, index: int) -> None:
        def work() -> Library:
            lib = load_library(_SERVICE)
            if not (0 <= index < self._list_len(lib)):
                raise IndexError("Row no longer valid; reload the view.")
            self._pop_at(lib, index)
            save_library_auxiliary_data(lib)
            return lib

        try:
            lib = await asyncio.to_thread(work)
        except Exception as exc:
            self._status.flash(f"  [yellow]Error: {exc}[/]")
            return
        self._lib = lib
        self._fill_table(lib)


def saved_albums_view() -> LocalLibraryListView:
    return LocalLibraryListView("albums")


def saved_artists_view() -> LocalLibraryListView:
    return LocalLibraryListView("artists")


def saved_songs_view() -> LocalLibraryListView:
    return LocalLibraryListView("songs")
