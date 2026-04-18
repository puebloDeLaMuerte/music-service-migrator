"""Service view — pull/push submenu with contextual warnings.

Layout: action menu (Pull Now, Push Now) | detail pane (warning / log output).
"""

from __future__ import annotations

import asyncio
import logging

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Label, ListItem, ListView, RichLog, Static

from tui.app import LogBridge
from tui.views.base import BaseView


class ServiceView(BaseView):
    DEFAULT_CSS = """
    ServiceView { height: 1fr; width: 1fr; }
    #svc-main { height: 1fr; }
    #svc-menu {
        width: 22;
        border-right: solid $primary-background-lighten-2;
    }
    #svc-detail {
        width: 1fr;
        padding: 1 2;
        overflow-y: auto;
    }
    #svc-log {
        width: 1fr;
        display: none;
    }
    #svc-log.visible { display: block; }
    #svc-status {
        dock: bottom;
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    """

    def __init__(self, service: str) -> None:
        super().__init__()
        self._service = service
        self._title = service.capitalize()
        self._op_active = False

    def compose(self) -> ComposeResult:
        with Horizontal(id="svc-main"):
            yield ListView(
                ListItem(Label("  Pull Now")),
                ListItem(Label("  Push Now")),
                id="svc-menu",
            )
            yield Static("", id="svc-detail", markup=True)
            yield RichLog(highlight=True, markup=True, id="svc-log")
        yield Static("", id="svc-status")

    def on_mount(self) -> None:
        self._show_pull_warning()
        self._update_status()

    # ── Column navigation (called by MigratorApp) ─────────────────

    def zone_left(self) -> None:
        focused = self.app.focused
        fid = getattr(focused, "id", None)
        if fid == "svc-log":
            self.query_one("#svc-menu").focus()
        elif fid == "svc-menu":
            self.app._focus_sidebar()
        else:
            self.app._focus_sidebar()

    def zone_right(self) -> None:
        focused = self.app.focused
        fid = getattr(focused, "id", None)
        if fid == "svc-menu" and self._op_active:
            self.query_one("#svc-log").focus()

    # ── Warnings ────────────────────────────────────────────────────

    def _show_pull_warning(self) -> None:
        text = (
            f"[bold]{self._title} — Pull[/]\n\n"
            "[yellow]⚠  Warning[/]\n"
            "[bold yellow]This will overwrite your local data on disk.[/]\n\n"
            f"Files under your saved library folder for {self._title} will be "
            "replaced by a fresh download. Anything you have only locally "
            "(without a separate backup) can be lost.\n\n"
            f"Downloaded from {self._title}:\n\n"
            "  • Playlists and their tracks\n"
            "  • Liked songs\n"
            "  • Saved albums\n"
            "  • Followed artists\n\n"
            "Press [bold]Enter[/] to start."
        )
        self.query_one("#svc-detail", Static).update(text)

    def _show_push_warning(self) -> None:
        text = (
            f"[bold]{self._title} — Push[/]\n\n"
            "[yellow]⚠  Warning[/]\n"
            "[bold yellow]This syncs your local library to "
            f"{self._title} and cannot be undone from this app.[/]\n\n"
            f"What you have stored on this machine will be sent to your "
            f"{self._title} account. Playlists and other items on the "
            "service will be created or updated to match your local data. "
            "There is no automatic rollback.\n\n"
            "Typical effects include:\n\n"
            "  • New playlists created on the service\n"
            "  • Existing playlists updated to match local files\n"
            "  • Album / library changes you applied locally reflected online\n\n"
            "Press [bold]Enter[/] to start."
        )
        self.query_one("#svc-detail", Static).update(text)

    def _update_status(self) -> None:
        if self._op_active:
            self.query_one("#svc-status", Static).update(
                f"  {self._title} operation running…"
            )
        else:
            self.query_one("#svc-status", Static).update(
                f"  ↑↓ select action  ·  Enter to confirm"
            )

    # ── Events ──────────────────────────────────────────────────────

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id != "svc-menu" or self._op_active:
            return
        idx = event.list_view.index
        if idx == 0:
            self._show_pull_warning()
        elif idx == 1:
            self._show_push_warning()
        event.stop()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id != "svc-menu" or self._op_active:
            event.stop()
            return
        idx = event.list_view.index
        if idx == 0:
            self._start_pull()
        elif idx == 1:
            self._start_push()
        event.stop()

    # ── Operations ──────────────────────────────────────────────────

    def _switch_to_log(self) -> None:
        self._op_active = True
        self.query_one("#svc-detail").styles.display = "none"
        log = self.query_one("#svc-log", RichLog)
        log.add_class("visible")
        self._update_status()

    def _start_pull(self) -> None:
        if self._service == "spotify":
            self._switch_to_log()
            self.run_worker(self._do_spotify_pull(), group="svc-op")
        else:
            self.query_one("#svc-detail", Static).update(
                f"[yellow]{self._title} pull is not yet implemented.[/]"
            )

    def _start_push(self) -> None:
        self.query_one("#svc-detail", Static).update(
            f"[yellow]{self._title} push is not yet implemented.[/]"
        )

    async def _do_spotify_pull(self) -> None:
        log_widget = self.query_one("#svc-log", RichLog)
        bridge = LogBridge(log_widget)
        bridge.setFormatter(logging.Formatter("%(message)s"))
        root = logging.getLogger()
        root.addHandler(bridge)
        try:
            log_widget.write(f"[bold]Pulling full library from {self._title}…[/]\n")

            from common.store import save_library
            from spotify.export import fetch_library

            library = await asyncio.to_thread(fetch_library)

            log_widget.write("")
            log_widget.write(
                f"[bold green]  {len(library.playlists)}[/] playlists, "
                f"[bold green]{len(library.liked_songs)}[/] liked songs, "
                f"[bold green]{len(library.saved_albums)}[/] saved albums, "
                f"[bold green]{len(library.followed_artists)}[/] followed artists"
            )

            out = await asyncio.to_thread(save_library, library)
            log_widget.write(f"\n[bold]Library saved to {out}[/]")
            self.query_one("#svc-status", Static).update("  Pull complete.")
        except Exception as exc:
            log_widget.write(f"[bold red]Error: {exc}[/]")
            self.query_one("#svc-status", Static).update("  Pull failed.")
        finally:
            root.removeHandler(bridge)
