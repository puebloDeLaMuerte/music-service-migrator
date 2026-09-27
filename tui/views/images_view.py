"""Playlist artwork — inspect cached files on disk and download on demand."""

from __future__ import annotations

import asyncio
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Label, ListItem, ListView, RichLog, Static

from common.store import load_workspace
from data.images import download_all_artwork, existing_artwork_path
from tui.app import app_rich_log
from tui.transient_status import TransientStatus
from tui.views.base import BaseView


def _fmt_size(path) -> str:
    try:
        n = path.stat().st_size
    except OSError:
        return ""
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n // 1024} KB"
    return f"{n / (1024 * 1024):.1f} MB"


class ImagesView(BaseView):
    BINDINGS: ClassVar = [
        Binding("r", "refresh", show=False, priority=True),
        Binding("d", "download_artwork", show=False, priority=True),
    ]

    DEFAULT_CSS = """
    ImagesView { height: 1fr; width: 1fr; }
    #img-main { height: 1fr; }
    #img-main > Vertical { height: 1fr; }
    .img-col-title {
        padding: 0 1;
        height: 1;
        text-style: bold;
        color: $text;
        background: $background;
    }
    .img-col-gap { height: 1; background: $background; }
    #img-col-actions {
        width: 28;
        border-right: solid $primary-background-lighten-2;
    }
    #img-col-actions #img-actions { height: 1fr; }
    #img-col-main { width: 1fr; }
    #img-intro {
        padding: 0 2 1 2;
        height: auto;
    }
    #img-pane-scroll {
        height: 1fr;
    }
    #img-table { height: 1fr; }
    #img-log {
        display: none;
        height: 1fr;
        min-height: 8;
    }
    #img-log.visible {
        display: block;
    }
    #img-detail-stack {
        height: 1fr;
    }
    #img-detail-stack.hidden {
        display: none;
    }
    #img-status {
        dock: bottom;
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="img-main"):
            with Vertical(id="img-col-actions"):
                yield Static("Actions", classes="img-col-title")
                yield Static("", classes="img-col-gap")
                yield ListView(
                    ListItem(Label(r"  \[r] Refresh list")),
                    ListItem(Label(r"  \[d] Download artwork")),
                    id="img-actions",
                )
            with Vertical(id="img-col-main"):
                yield Static("Playlist artwork", classes="img-col-title")
                yield Static("", classes="img-col-gap")
                with Vertical(id="img-pane-scroll"):
                    with Vertical(id="img-detail-stack"):
                        yield Static("", id="img-intro", markup=True)
                        yield DataTable(id="img-table", zebra_stripes=True)
                    yield app_rich_log(id="img-log")
        yield Static("", id="img-status", markup=True)

    def on_mount(self) -> None:
        self._busy = False
        self._status = TransientStatus(self.query_one("#img-status", Static))
        table = self.query_one("#img-table", DataTable)
        table.cursor_type = "row"
        table.add_column("Playlist")
        table.add_column("Cached")
        table.add_column("Size")
        self._set_intro_text()
        self._status.set_baseline("  Loading…")
        self.run_worker(self._load_library(), group="img-load")

    def _set_intro_text(self) -> None:
        from common import config

        root = config.work_dir()
        self.query_one("#img-intro", Static).update(
            "[bold]Playlist cover images[/]\n\n"
            f"Saved under [dim]{root}/playlists/<name>_data/artwork.*[/]\n\n"
            "[dim]Refresh[/] rescans the folder on disk (no network). "
            "[dim]Download artwork[/] hits the service for every playlist — run it when "
            "you are ready; large libraries can take a while."
        )

    async def _load_library(self) -> None:
        try:
            lib = await asyncio.to_thread(load_workspace)
        except Exception as exc:
            self._status.set_baseline(f"  [yellow]Error loading workspace: {exc}[/]")
            return
        self._fill_table(lib)
        self._status.set_baseline(
            r"  ↑↓ select action  ·  \[r] refresh  ·  \[d] download  ·  ← actions"
        )

        def _focus_menu() -> None:
            self.query_one("#img-actions", ListView).focus()

        self.call_after_refresh(_focus_menu)

    def _fill_table(self, lib) -> None:
        table = self.query_one("#img-table", DataTable)
        table.clear()
        if not lib.playlists:
            return
        for pl in lib.playlists:
            path = existing_artwork_path(pl)
            if path is not None:
                table.add_row(pl.name, "yes", _fmt_size(path))
            else:
                table.add_row(pl.name, "—", "")

    def _show_detail_pane(self) -> None:
        self.query_one("#img-detail-stack", Vertical).remove_class("hidden")
        self.query_one("#img-log", RichLog).remove_class("visible")

    def _show_log_pane(self) -> None:
        self.query_one("#img-detail-stack", Vertical).add_class("hidden")
        self.query_one("#img-log", RichLog).add_class("visible")

    def zone_left(self) -> None:
        fid = getattr(self.app.focused, "id", None)
        if fid in ("img-table", "img-log"):
            self.query_one("#img-actions", ListView).focus()
        else:
            self.app._focus_sidebar()

    def zone_right(self) -> None:
        fid = getattr(self.app.focused, "id", None)
        if fid == "img-actions":
            if self._busy:
                self.query_one("#img-log", RichLog).focus()
            else:
                self.query_one("#img-table", DataTable).focus()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id != "img-actions" or self._busy:
            return
        idx = event.list_view.index
        if idx == 0:
            self._status.flash(
                r"  [yellow]\[r] Refresh: rescan artwork files on disk (no network).[/]"
            )
        elif idx == 1:
            self._status.flash(
                r"  [yellow]\[d] Download: fetch artwork from the service for each "
                r"playlist (network; can be slow).[/]"
            )
        event.stop()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id != "img-actions" or self._busy:
            event.stop()
            return
        idx = event.list_view.index
        if idx == 0:
            self.action_refresh()
        elif idx == 1:
            self.action_download_artwork()
        event.stop()

    def action_refresh(self) -> None:
        if self._busy:
            return
        self.run_worker(self._do_refresh(), group="img-refresh")

    def action_download_artwork(self) -> None:
        if self._busy:
            self._status.flash("  [yellow]Already running…[/]")
            return
        self.run_worker(self._do_download(), group="img-download")

    async def _do_refresh(self) -> None:
        try:
            lib = await asyncio.to_thread(load_workspace)
        except Exception as exc:
            self._status.flash(f"  [yellow]{exc}[/]")
            return
        self._fill_table(lib)

    async def _do_download(self) -> None:
        self._busy = True
        self._show_log_pane()
        log_w = self.query_one("#img-log", RichLog)
        log_w.clear()
        log_w.write("[bold]Downloading playlist artwork…[/]")
        self.call_after_refresh(log_w.focus)

        try:
            lib = await asyncio.to_thread(load_workspace)
        except Exception as exc:
            log_w.write(f"[red]Error loading workspace: {exc}[/]")
            self._finish_download_session()
            return

        if not lib.playlists:
            log_w.write("[yellow]No playlists in the workspace — run a catalog pull first.[/]")
            self._finish_download_session()
            return

        log_w.write(
            f"Processing [bold]{len(lib.playlists)}[/] playlist(s)…\n"
        )

        def work():
            return download_all_artwork(lib)

        try:
            downloaded, skipped = await asyncio.to_thread(work)
        except Exception as exc:
            log_w.write(f"[bold red]Error: {exc}[/]")
            self._finish_download_session()
            return

        log_w.write("")
        log_w.write(
            f"[bold green]{downloaded}[/] downloaded, "
            f"[yellow]{skipped}[/] skipped (no artwork in export)."
        )
        self._fill_table(lib)
        self._finish_download_session()
        self._status.flash("  Finished. Table shows cached files.")

    def _finish_download_session(self) -> None:
        self._busy = False
        self._show_detail_pane()

        def _focus_menu() -> None:
            self.query_one("#img-actions", ListView).focus()

        self.call_after_refresh(_focus_menu)
