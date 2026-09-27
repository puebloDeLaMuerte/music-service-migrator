"""Local Files — create backups of Local Data and load saved libraries back.

Layout: action menu (backup + list of saved libraries) | detail pane.
"""

from __future__ import annotations

import asyncio

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import ListView, Static

from common.local_backups import LOCAL_SOURCE, BackupInfo, backups_root, create_local_backup, list_backups, load_backup
from tui.views.base import BaseView
from tui.views.p2a_view import ConfirmModal
from tui.views.service_view import SvcMenuItem


def _source_text(b: BackupInfo) -> str:
    if b.source == LOCAL_SOURCE:
        return "Copy of Local Data"
    return f"Downloaded from {b.source.capitalize()}"


class LocalFilesView(BaseView):
    DEFAULT_CSS = """
    LocalFilesView { height: 1fr; width: 1fr; }
    #lf-main { height: 1fr; }
    #lf-main > Vertical { height: 1fr; }
    .lf-col-title {
        padding: 0 1;
        height: 1;
        text-style: bold;
        color: $text;
        background: $background;
    }
    .lf-col-gap { height: 1; background: $background; }
    #lf-col-menu {
        width: 30;
        border-right: solid $primary-background-lighten-2;
    }
    #lf-col-menu #lf-menu { height: 1fr; }
    #lf-col-right { width: 1fr; }
    #lf-detail { padding: 1 2; overflow-y: auto; height: 1fr; }
    #lf-status {
        dock: bottom;
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._backups: list[BackupInfo] = []
        self._busy = False

    def compose(self) -> ComposeResult:
        with Horizontal(id="lf-main"):
            with Vertical(id="lf-col-menu"):
                yield Static("Actions", classes="lf-col-title")
                yield Static("", classes="lf-col-gap")
                yield ListView(id="lf-menu")
            with Vertical(id="lf-col-right"):
                yield Static("Details", classes="lf-col-title")
                yield Static("", classes="lf-col-gap")
                yield Static("", id="lf-detail", markup=True)
        yield Static("  ↑↓ select  ·  Enter to confirm", id="lf-status")

    def on_mount(self) -> None:
        self._show_create_details()
        self.run_worker(self._reload_menu(), group="lf-menu", exclusive=True)

    async def _reload_menu(self, *, highlight: str | None = None) -> None:
        self._backups = await asyncio.to_thread(list_backups)
        items = [
            SvcMenuItem("hdr_backup", "  [bold dim]— local backup —[/]", disabled=True),
            SvcMenuItem("create", "  Create"),
            SvcMenuItem("sep_load", " ", disabled=True),
            SvcMenuItem("hdr_load", "  [bold dim]— load local library —[/]", disabled=True),
        ]
        for i, b in enumerate(self._backups):
            items.append(SvcMenuItem(f"backup:{i}", f"  {b.when} [dim]{escape(b.source)}[/]"))
        if not self._backups:
            items.append(SvcMenuItem("none", "  [dim](no backups yet)[/]", disabled=True))
        menu = self.query_one("#lf-menu", ListView)
        await menu.clear()
        await menu.extend(items)
        target = next((n for n, it in enumerate(items) if it.action_id == highlight), 1)
        menu.index = target

    # ── Column navigation (called by MigratorApp) ─────────────────

    def zone_left(self) -> None:
        self.app._focus_sidebar()

    def zone_right(self) -> None:
        pass

    # ── Details ─────────────────────────────────────────────────────

    def _detail(self, text: str) -> None:
        self.query_one("#lf-detail", Static).update(text)

    def _status(self, text: str) -> None:
        self.query_one("#lf-status", Static).update(f"  {text}")

    def _show_create_details(self) -> None:
        self._detail(
            "[bold]Local Files — Create backup[/]\n\n"
            "Copies everything in your work folder — the library Local Data shows, "
            "plus push plans, decisions and removal records — to:\n\n"
            f"  [dim]{backups_root() / LOCAL_SOURCE}/<date-time>[/]\n\n"
            "Login tokens are not copied.\n\n"
            "Press [bold]Enter[/] to create it."
        )

    def _backup_for(self, aid: str) -> BackupInfo | None:
        if not aid.startswith("backup:"):
            return None
        idx = int(aid.split(":", 1)[1])
        return self._backups[idx] if idx < len(self._backups) else None

    def _show_backup_details(self, b: BackupInfo) -> None:
        self._detail(
            f"[bold]Local Files — Library from {b.when}[/]\n\n"
            f"{_source_text(b)}\n\n"
            f"  {b.playlists} playlists\n"
            f"  {b.liked_songs} liked songs\n"
            f"  {b.saved_albums} saved albums\n"
            f"  {b.followed_artists} followed artists\n\n"
            f"[dim]{b.path}[/]\n\n"
            "Press [bold]Enter[/] to load it into Local Data.\n\n"
            "[yellow]Loading replaces what Local Data shows now.[/] Logins, push plans, "
            "your push decisions and recorded removals stay as they are. Create a "
            "backup first if you want to keep the current state."
        )

    # ── Events ──────────────────────────────────────────────────────

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        item = event.item
        if event.list_view.id != "lf-menu" or not isinstance(item, SvcMenuItem) or self._busy:
            return
        if item.action_id == "create":
            self._show_create_details()
        elif (b := self._backup_for(item.action_id)) is not None:
            self._show_backup_details(b)
        event.stop()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        event.stop()
        if event.list_view.id != "lf-menu" or not isinstance(item, SvcMenuItem) or self._busy:
            return
        if item.action_id == "create":
            self._busy = True
            self.run_worker(self._do_create(), group="lf-op")
        elif (b := self._backup_for(item.action_id)) is not None:
            body = (
                f"[bold]Load library from {b.when}?[/]\n\n"
                f"{_source_text(b)}: {b.playlists} playlists, "
                f"{b.liked_songs} liked songs, {b.saved_albums} saved albums, "
                f"{b.followed_artists} followed artists.\n\n"
                "This replaces what Local Data shows now."
            )
            self.app.push_screen(ConfirmModal(body), lambda ok: self._after_load_confirm(ok, b))

    # ── Operations ──────────────────────────────────────────────────

    async def _do_create(self) -> None:
        self._status("Creating backup…")
        try:
            dest = await asyncio.to_thread(create_local_backup)
        except Exception as exc:
            self._detail(f"[bold red]Backup failed[/]\n\n{escape(str(exc))}")
            self._status("Backup failed.")
            return
        finally:
            self._busy = False
        await self._reload_menu(highlight="create")
        self._detail(f"[bold green]Backup created.[/]\n\n[dim]{dest}[/]\n\nIt is now listed under Load local library.")
        self._status("Backup created.")

    def _after_load_confirm(self, ok: bool | None, b: BackupInfo) -> None:
        if not ok:
            self._status("Cancelled.")
            return
        self._busy = True
        self.run_worker(self._do_load(b), group="lf-op")

    async def _do_load(self, b: BackupInfo) -> None:
        self._status("Loading library…")
        try:
            await asyncio.to_thread(load_backup, b.path)
        except Exception as exc:
            self._detail(f"[bold red]Loading failed[/]\n\n{escape(str(exc))}")
            self._status("Loading failed.")
            return
        finally:
            self._busy = False
        self._detail(
            f"[bold green]Loaded the library from {b.when}.[/]\n\n"
            "Local Data now shows this library."
        )
        self._status("Library loaded.")
