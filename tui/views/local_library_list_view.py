"""Browse saved albums, followed artists, or liked songs from the local export; remove entries."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Label, ListItem, ListView, Static

from common.local_list_columns import (
    ListKind,
    display_semantic_at,
    local_list_column_headers,
    permute_canonical_row_to_display,
)
from common.models import Library
from common.store import load_workspace, save_workspace, save_workspace_auxiliary
from tui.transient_status import TransientStatus
from tui.views.base import BaseView
from tui.views.p2a_view import ConfirmModal

_KIND_META: dict[ListKind, dict] = {
    "albums": {
        "menu_title": "Saved albums",
        "table_title": "Albums",
        "empty": "No saved albums in the workspace. Run Spotify → Pull first.",
        "attr": "saved_albums",
        "label_fn": lambda sa: sa.album.name,
        "confirm_prefix": "Remove album",
        "rows": lambda lib: [
            (
                sa.album.name,
                _fmt_artists(sa.album.artists),
                _fmt_added(sa.saved_at),
            )
            for sa in lib.saved_albums
        ],
    },
    "artists": {
        "menu_title": "Saved artists",
        "table_title": "Artists",
        "empty": "No followed artists in the workspace. Run Spotify → Pull first.",
        "attr": "followed_artists",
        "label_fn": lambda fa: fa.artist.name,
        "confirm_prefix": "Remove artist",
        "rows": lambda lib: [
            (fa.artist.name, _fmt_added(_followed_artist_added(fa)))
            for fa in lib.followed_artists
        ],
    },
    "songs": {
        "menu_title": "Saved songs",
        "table_title": "Songs",
        "empty": "No liked songs in the workspace. Run Spotify → Pull first.",
        "attr": "liked_songs",
        "label_fn": lambda pt: pt.track.name,
        "confirm_prefix": "Remove track",
        "rows": lambda lib: [
            (
                pt.track.name,
                _fmt_artists(pt.track.artists),
                pt.track.album.name if pt.track.album else "",
                _fmt_added(pt.added_at),
            )
            for pt in lib.liked_songs
        ],
    },
    "playlists": {
        "menu_title": "Playlists",
        "table_title": "Playlists",
        "empty": "No playlists in the workspace. Run Spotify → Pull first.",
        "attr": "playlists",
        "label_fn": lambda pl: pl.name,
        "confirm_prefix": "Remove playlist",
        # Added column: Spotify does not expose per-playlist library date (see export).
        "rows": lambda lib: [
            (pl.name, pl.owner or "", str(pl.track_count), _fmt_added(None))
            for pl in lib.playlists
        ],
    },
}


def _fmt_artists(artists) -> str:
    return ", ".join(a.name for a in artists) if artists else ""


def _fmt_added(dt: datetime | None) -> str:
    """ISO date (YYYY-MM-DD) for stable display and lexicographic sort."""
    if dt is None:
        return ""
    return dt.date().isoformat()


def _followed_artist_added(fa) -> datetime | None:
    """Follow date only if we stored it (Spotify does not send it on followed-artists)."""
    return fa.followed_at


def _cell_sort_key(row: tuple, col: int, kind: ListKind) -> tuple:
    """Key for stable sort (second pass); numeric tracks; ISO dates for Added."""
    cell = row[col] if col < len(row) else ""
    sem = display_semantic_at(kind, col)
    if sem == "added":
        if not (cell or "").strip():
            return (2, "")
        return (0, cell.casefold())
    if kind == "playlists" and sem == "tracks":
        try:
            return (0, int(cell))
        except ValueError:
            return (1, cell.casefold())
    return (0, cell.casefold())


class LocalLibraryListView(BaseView):
    """One of: saved albums, followed artists, liked songs — read from local JSON."""

    BINDINGS: ClassVar = [
        Binding("r", "remove", show=False, priority=True),
        Binding("s", "sort", show=False, priority=True),
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
        width: 24;
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
        # 0 = file order; 1..2n = cycle col (k-1)//2 asc/desc by (k-1)%2
        self._sort_phase: int = 0
        self._row_to_lib_index: list[int] = []

    def compose(self) -> ComposeResult:
        with Horizontal(id="local-main"):
            with Vertical(id="local-col-actions"):
                yield Static("Actions", classes="local-col-title")
                yield Static("", classes="local-col-gap")
                yield ListView(
                    ListItem(Label(r"  \[r] Remove")),
                    ListItem(Label(r"  \[s] Sort")),
                    id="local-actions",
                )
            with Vertical(id="local-col-table"):
                yield Static(self._meta["table_title"], classes="local-col-title")
                yield Static("", classes="local-col-gap")
                yield DataTable(id="local-table")
        yield Static("", id="local-status", markup=True)

    def on_mount(self) -> None:
        self._lib: Library | None = None
        self._cached_table_headers: tuple[str, ...] | None = None
        self._status = TransientStatus(self.query_one("#local-status", Static))
        self._status.set_baseline("Loading…")
        table = self.query_one("#local-table", DataTable)
        self._sync_table_columns(table)
        table.cursor_type = "cell"
        self.run_worker(self._load_task(), group="local-list-load")

    def _rows_for_table(self, lib: Library) -> list[tuple]:
        canonical = list(self._meta["rows"](lib))
        return [permute_canonical_row_to_display(tuple(r), self._kind) for r in canonical]

    def _sync_table_columns(self, table: DataTable) -> None:
        headers = local_list_column_headers(self._kind)
        if self._cached_table_headers == headers:
            return
        table.clear(columns=True)
        for h in headers:
            table.add_column(h)
        self._cached_table_headers = headers

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
            lib = await asyncio.to_thread(load_workspace)
        except Exception as exc:
            self._status.set_baseline(f"Error: {exc}")
            return

        self._sort_phase = 0
        self._lib = lib
        self._fill_table(lib)

    def _sort_status_fragment(self) -> str:
        if self._sort_phase == 0:
            return "file order"
        k = self._sort_phase - 1
        col = k // 2
        desc = (k % 2) == 1
        headers = local_list_column_headers(self._kind)
        name = headers[col]
        arrow = "↓" if desc else "↑"
        return f"{name} {arrow}"

    def _fill_table(self, lib: Library) -> None:
        table = self.query_one("#local-table", DataTable)
        prev_row = int(table.cursor_row)
        prev_col = int(table.cursor_column)
        n_cols = len(table.ordered_columns)
        table.clear()
        raw_rows = self._rows_for_table(lib)
        n = len(raw_rows)
        if n == 0:
            self._row_to_lib_index = []
            self._status.set_baseline(f"  {self._meta['empty']}")
            return

        if self._sort_phase > 0:
            k = self._sort_phase - 1
            col = k // 2
            desc = (k % 2) == 1
            paired = list(zip(raw_rows, range(n)))
            paired.sort(key=lambda p: p[1])
            paired.sort(
                key=lambda p: _cell_sort_key(p[0], col, self._kind),
                reverse=desc,
            )
            rows = [p[0] for p in paired]
            self._row_to_lib_index = [p[1] for p in paired]
        else:
            rows = raw_rows
            self._row_to_lib_index = list(range(n))

        for row in rows:
            table.add_row(*row)
        sort_hint = self._sort_status_fragment()
        self._status.set_baseline(
            f"  {n} row(s)  ·  {sort_hint}  ·  "
            + r"\[r] remove  ·  \[s] sort  ·  ↑↓ ←→  ·  ← actions"
        )
        target_row = min(max(0, prev_row), n - 1) if prev_row >= 0 else 0
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
        if r >= len(self._row_to_lib_index):
            return None
        return self._row_to_lib_index[r]

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
            idx = event.list_view.index
            if idx == 0:
                self._status.flash(
                    r"  [yellow]\[r] Remove: drop this row from the saved export on disk "
                    r"(Spotify is unchanged until you push).[/]"
                )
            elif idx == 1:
                self._status.flash(
                    r"  [yellow]\[s] Sort: cycle each column A→Z / Z→A, then back to file order.[/]"
                )
            event.stop()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id != "local-actions":
            return
        idx = event.list_view.index
        if idx == 0:
            self.action_remove()
        elif idx == 1:
            self.action_sort()
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

    def action_sort(self) -> None:
        if self._lib is None:
            self._status.flash("  [yellow]Still loading…[/]")
            return
        n = self._list_len(self._lib)
        if n == 0:
            return
        n_cols = len(local_list_column_headers(self._kind))
        self._sort_phase = (self._sort_phase + 1) % (2 * n_cols + 1)
        self._fill_table(self._lib)

    def _on_remove_ok(self, ok: bool) -> None:
        if not ok or self._lib is None:
            return
        idx = self._current_index()
        if idx is None:
            return
        self.run_worker(self._wk_remove(idx), group="local-list-remove")

    async def _wk_remove(self, index: int) -> None:
        def work() -> Library:
            lib = load_workspace()
            if not (0 <= index < self._list_len(lib)):
                raise IndexError("Row no longer valid; reload the view.")
            self._pop_at(lib, index)
            if self._kind == "playlists":
                save_workspace(lib)
            else:
                save_workspace_auxiliary(lib)
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


def saved_playlists_view() -> LocalLibraryListView:
    return LocalLibraryListView("playlists")
