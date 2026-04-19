"""Service view — service actions (pull, push, backup, wipe, login).

Layout: action menu | detail pane (instructions / log output).
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Label, ListItem, ListView, RichLog, Static

from common import config
from common.catalog_adapters import CatalogPullAdapter, get_catalog_pull
from tui.app import LogBridge
from tui.views.base import BaseView

# https? URLs — tidalapi prints the login link as plain text; Rich link style enables
# OSC-8 hyperlinks + Textual click-to-open in :class:`LinkedRichLog`.
_URL_RE = re.compile(r"(https?://[^\s<>]+)")


def _is_usable_http_url(url: str) -> bool:
    try:
        p = urlparse(url.strip())
    except Exception:
        return False
    return p.scheme in ("http", "https") and bool(p.netloc)


def _append_line_with_urls(out: Text, line: str) -> None:
    pos = 0
    for m in _URL_RE.finditer(line):
        if m.start() > pos:
            out.append(line[pos : m.start()])
        url = m.group(1)
        out.append(url, style=f"link {url}")
        pos = m.end()
    if pos < len(line):
        out.append(line[pos:])


def rich_text_with_urls(msg: str) -> Text:
    """Plain text with ``https://`` spans turned into Rich hyperlink segments."""
    lines = msg.split("\n")
    out = Text()
    for i, line in enumerate(lines):
        if i:
            out.append("\n")
        _append_line_with_urls(out, line)
    return out


def schedule_open_new_https_urls(app, text: str, *, opened: set[str]) -> None:
    """Open each distinct ``https://`` URL from *text* in the default browser (main thread).

    *opened* tracks URLs already launched during this login attempt so tidalapi
    duplicate lines do not spawn extra tabs.
    """
    for m in _URL_RE.finditer(text):
        url = m.group(1)
        if not _is_usable_http_url(url) or url in opened:
            continue
        opened.add(url)

        def _open(u: str = url) -> None:
            try:
                app.open_url(u)
            except Exception:
                pass

        app.call_from_thread(_open)


class LinkedRichLog(RichLog):
    """RichLog that opens Rich ``link`` segments in the system browser on click."""

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("wrap", True)
        super().__init__(*args, **kwargs)

    async def on_click(self, event: events.Click) -> None:
        link = getattr(event.style, "link", None)
        if link:
            url = str(link).strip()
            if _is_usable_http_url(url):
                self.app.open_url(url)
                event.stop()


class ServiceView(BaseView):
    """Menu indices: 0 pull, 1 push, 2 separator (disabled), 3 backup, 4 wipe, 5 login."""

    _IX_PULL = 0
    _IX_PUSH = 1
    _IX_SEP = 2
    _IX_BACKUP = 3
    _IX_WIPE = 4
    _IX_LOGIN = 5

    DEFAULT_CSS = """
    ServiceView { height: 1fr; width: 1fr; }
    #svc-main { height: 1fr; }
    #svc-main > Vertical { height: 1fr; }
    .svc-col-title {
        padding: 0 1;
        height: 1;
        text-style: bold;
        color: $text;
    }
    .svc-col-gap { height: 1; }
    #svc-col-menu .svc-col-title,
    #svc-col-menu .svc-col-gap {
        background: $surface;
    }
    #svc-col-right .svc-col-title,
    #svc-col-right .svc-col-gap {
        background: $background;
    }
    #svc-col-menu {
        width: 28;
        border-right: solid $primary-background-lighten-2;
    }
    #svc-menu > ListItem.svc-menu-sep {
        height: 1;
        min-height: 1;
        padding: 0;
        background: $surface;
    }
    #svc-menu > ListItem.svc-menu-sep Label {
        height: 1;
        color: $surface;
    }
    #svc-col-menu #svc-menu { height: 1fr; }
    #svc-col-right { width: 1fr; }
    #svc-detail {
        padding: 1 2;
        overflow-y: auto;
        height: 1fr;
    }
    #svc-log {
        display: none;
        height: 1fr;
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
            with Vertical(id="svc-col-menu"):
                yield Static("Actions", classes="svc-col-title")
                yield Static("", classes="svc-col-gap")
                yield ListView(
                    ListItem(Label("  Pull Now")),
                    ListItem(Label("  Push Now")),
                    ListItem(
                        Label(" "),
                        disabled=True,
                        classes="svc-menu-sep",
                    ),
                    ListItem(Label("  Backup")),
                    ListItem(Label("  [red]Wipe[/]", markup=True)),
                    ListItem(Label("  Login")),
                    id="svc-menu",
                )
            with Vertical(id="svc-col-right"):
                yield Static("Details", id="svc-pane-title", classes="svc-col-title")
                yield Static("", classes="svc-col-gap")
                yield Static("", id="svc-detail", markup=True)
                yield LinkedRichLog(highlight=True, markup=True, id="svc-log")
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

    def _backup_destination(self) -> Path:
        stamp = datetime.now().strftime("%Y-%m-%d-%H-%M")
        return (config.project_root() / "backups" / self._service / stamp).resolve()

    def _show_backup_details(self) -> None:
        dest = self._backup_destination()
        text = (
            f"[bold]{self._title} — Backup[/]\n\n"
            "Download the same data as [bold]Pull Now[/], but write it under the "
            "project’s [bold]backups[/] folder instead of your live workspace.\n\n"
            f"This run will create:\n  [dim]{dest}[/]\n\n"
            f"Downloaded from {self._title}:\n\n"
            "  • Playlists and their tracks\n"
            "  • Liked songs\n"
            "  • Saved albums\n"
            "  • Followed artists\n\n"
            "Press [bold]Enter[/] to start."
        )
        self.query_one("#svc-detail", Static).update(text)

    def _show_wipe_details(self) -> None:
        text = (
            f"[bold red]{self._title} — Wipe[/]\n\n"
            "[yellow]Not implemented yet.[/]\n\n"
            "This action will eventually remove or reset local data for this "
            "service; details will be added here."
        )
        self.query_one("#svc-detail", Static).update(text)

    def _show_login_details(self) -> None:
        if self._service == "spotify":
            from spotify.client import spotify_login_status, token_cache_path

            ok, status = spotify_login_status()
            p = token_cache_path()
            head = f"[bold]{self._title} — Login[/]\n\n{status}\n\n"
            if ok:
                text = head + (
                    "You are already signed in. Press [bold]Enter[/] to run OAuth again "
                    "from scratch (the cached token file is deleted first).\n\n"
                    "[bold].env[/]\n"
                    "  • SPOTIFY_CLIENT_ID\n"
                    "  • SPOTIFY_CLIENT_SECRET\n"
                    "  • SPOTIFY_REDIRECT_URI — must match your Spotify Developer app\n\n"
                    f"[dim]Token file: {p}[/]\n\n"
                    "[dim]Some API access in development requires Premium on the account "
                    "that owns the app.[/]"
                )
            else:
                text = head + (
                    "Sign in with Spotify (OAuth). Your browser may open.\n\n"
                    "[bold].env[/]\n"
                    "  • SPOTIFY_CLIENT_ID\n"
                    "  • SPOTIFY_CLIENT_SECRET\n"
                    "  • SPOTIFY_REDIRECT_URI — must match your app in the "
                    "Spotify Developer Dashboard\n\n"
                    f"Token cache (after login):\n  [dim]{p}[/]\n\n"
                    "[dim]Some API access in development requires Premium on the "
                    "account that owns the app. If you see errors after signing in, "
                    "check that account.[/]\n\n"
                    "Press [bold]Enter[/] to sign in or re-authenticate."
                )
        elif self._service == "tidal":
            from tidal.client import session_file_path, tidal_login_status

            ok, status = tidal_login_status()
            p = session_file_path()
            head = f"[bold]{self._title} — Login[/]\n\n{status}\n\n"
            if ok:
                text = head + (
                    "You already have a valid session. Press [bold]Enter[/] to run "
                    "device login again (the existing session file is removed first).\n\n"
                    "[bold]Optional[/]\n"
                    "  • TIDAL_SESSION_FILE — custom path for the session JSON\n\n"
                    f"Session file:\n  [dim]{p}[/]"
                )
            else:
                text = head + (
                    "Device login: you will get a link and a code to approve in your "
                    "browser.\n\n"
                    "[bold]Optional[/]\n"
                    "  • TIDAL_SESSION_FILE — custom path for the session JSON\n\n"
                    f"Default session file:\n  [dim]{p}[/]\n\n"
                    "Press [bold]Enter[/] to start login (replaces an existing session)."
                )
        else:
            text = (
                f"[bold]{self._title} — Login[/]\n\n"
                "[yellow]Login is not available for this service.[/]"
            )
        self.query_one("#svc-detail", Static).update(text)

    def _restore_detail_pane(self, body: str) -> None:
        self._op_active = False
        log_w = self.query_one("#svc-log", LinkedRichLog)
        log_w.remove_class("visible")
        detail = self.query_one("#svc-detail", Static)
        detail.styles.display = "block"
        detail.update(body)
        self.query_one("#svc-pane-title", Static).update("Details")
        self._update_status()
        self.query_one("#svc-menu").focus()

    def _reveal_menu_detail_pane(self) -> None:
        """Show the details column again (e.g. after Pull finished but log was still visible)."""
        log_w = self.query_one("#svc-log", LinkedRichLog)
        if log_w.has_class("visible"):
            log_w.remove_class("visible")
        self.query_one("#svc-detail", Static).styles.display = "block"
        self.query_one("#svc-pane-title", Static).update("Details")

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
        if idx is None or idx == self._IX_SEP:
            return
        # After Pull/Backup the log stays visible but _op_active is cleared; show details again.
        self._reveal_menu_detail_pane()
        if idx == self._IX_PULL:
            self._show_pull_warning()
        elif idx == self._IX_PUSH:
            self._show_push_warning()
        elif idx == self._IX_BACKUP:
            self._show_backup_details()
        elif idx == self._IX_WIPE:
            self._show_wipe_details()
        elif idx == self._IX_LOGIN:
            self._show_login_details()
        event.stop()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id != "svc-menu" or self._op_active:
            event.stop()
            return
        idx = event.list_view.index
        if idx == self._IX_PULL:
            self._start_pull()
        elif idx == self._IX_PUSH:
            self._start_push()
        elif idx == self._IX_BACKUP:
            self._start_backup()
        elif idx == self._IX_WIPE:
            self._start_wipe()
        elif idx == self._IX_LOGIN:
            self._start_login()
        event.stop()

    # ── Operations ──────────────────────────────────────────────────

    def _switch_to_log(self) -> None:
        self._op_active = True
        self.query_one("#svc-detail").styles.display = "none"
        self.query_one("#svc-pane-title", Static).update("Log")
        log = self.query_one("#svc-log", LinkedRichLog)
        log.add_class("visible")
        self._update_status()

    def _start_pull(self) -> None:
        from common.catalog_adapters import get_catalog_pull

        adapter = get_catalog_pull(self._service)
        if adapter is None:
            self.query_one("#svc-detail", Static).update(
                f"[yellow]{self._title} pull is not registered.[/]"
            )
            return
        self._switch_to_log()
        self.run_worker(self._do_catalog_pull(adapter), group="svc-op")

    def _start_backup(self) -> None:
        from common.catalog_adapters import get_catalog_pull

        adapter = get_catalog_pull(self._service)
        if adapter is None:
            self.query_one("#svc-detail", Static).update(
                f"[yellow]{self._title} backup is not registered.[/]"
            )
            return
        dest = self._backup_destination()
        self._switch_to_log()
        self.run_worker(self._do_catalog_pull(adapter, workspace_root=dest), group="svc-op")

    def _start_wipe(self) -> None:
        self.query_one("#svc-detail", Static).update(
            f"[yellow]{self._title} wipe is not yet implemented.[/]"
        )

    def _start_push(self) -> None:
        self.query_one("#svc-detail", Static).update(
            f"[yellow]{self._title} push is not yet implemented.[/]"
        )

    def _start_login(self) -> None:
        if self._service not in ("spotify", "tidal"):
            self.query_one("#svc-detail", Static).update(
                f"[yellow]{self._title} login is not available.[/]"
            )
            return
        log_w = self.query_one("#svc-log", LinkedRichLog)
        log_w.clear()
        self._switch_to_log()
        self.query_one("#svc-log").focus()
        if self._service == "spotify":
            self.run_worker(self._do_spotify_login(), group="svc-op")
        else:
            self.run_worker(self._do_tidal_login(), group="svc-op")

    async def _do_spotify_login(self) -> None:
        log_widget = self.query_one("#svc-log", LinkedRichLog)
        log_widget.write("[bold]Starting Spotify OAuth…[/]\n")
        try:
            from spotify.client import SpotifyAuthError, login_interactive

            name = await asyncio.to_thread(login_interactive)
            self._restore_detail_pane(
                f"[bold green]Signed in as {name}[/]\n\n"
                "You can run Pull from the actions menu when ready."
            )
            self.query_one("#svc-status", Static).update("  Login complete.")
        except asyncio.CancelledError:
            self._restore_detail_pane("[yellow]Login cancelled.[/]")
            self.query_one("#svc-status", Static).update("  Cancelled.")
            raise
        except SpotifyAuthError as exc:
            self._restore_detail_pane(f"[bold red]Spotify sign-in failed[/]\n\n{exc}")
            self.query_one("#svc-status", Static).update("  Login failed.")
        except Exception as exc:
            self._restore_detail_pane(f"[bold red]Error[/]\n\n{exc}")
            self.query_one("#svc-status", Static).update("  Login failed.")

    async def _do_tidal_login(self) -> None:
        log_widget = self.query_one("#svc-log", LinkedRichLog)
        log_widget.write("[bold]Starting TIDAL device login…[/]\n")
        _browser_opened_urls: set[str] = set()

        def tidal_print(msg: str) -> None:
            raw = str(msg)
            line = rich_text_with_urls(raw)
            self.app.call_from_thread(log_widget.write, line)
            schedule_open_new_https_urls(self.app, raw, opened=_browser_opened_urls)

        try:
            from tidal.client import run_interactive_login, session_file_path

            ok = await asyncio.to_thread(run_interactive_login, tidal_print)
            path = session_file_path()
            if ok:
                self._restore_detail_pane(
                    f"[bold green]TIDAL session saved.[/]\n\n"
                    f"[dim]{path}[/]\n\n"
                    "You can run Pull from the actions menu when ready."
                )
                self.query_one("#svc-status", Static).update("  Login complete.")
            else:
                self._restore_detail_pane(
                    "[bold red]TIDAL login did not complete[/]\n\n"
                    "Try again or check the log above."
                )
                self.query_one("#svc-status", Static).update("  Login incomplete.")
        except asyncio.CancelledError:
            self._restore_detail_pane("[yellow]Login cancelled.[/]")
            self.query_one("#svc-status", Static).update("  Cancelled.")
            raise
        except Exception as exc:
            self._restore_detail_pane(f"[bold red]Error[/]\n\n{exc}")
            self.query_one("#svc-status", Static).update("  Login failed.")

    async def _do_catalog_pull(
        self,
        adapter: CatalogPullAdapter,
        *,
        workspace_root: Path | None = None,
    ) -> None:
        log_widget = self.query_one("#svc-log", LinkedRichLog)
        bridge = LogBridge(log_widget)
        bridge.setFormatter(logging.Formatter("%(message)s"))
        root = logging.getLogger()
        root.addHandler(bridge)
        is_backup = workspace_root is not None
        try:
            lead = "Backing up" if is_backup else "Pulling"
            log_widget.write(f"[bold]{lead} full library from {self._title}…[/]\n")
            if is_backup:
                log_widget.write(f"[dim]Destination: {workspace_root}[/]\n")

            from common.pull import apply_pull_result

            library = await asyncio.to_thread(adapter.fetch_library)

            log_widget.write("")
            log_widget.write(
                f"[bold green]  {len(library.playlists)}[/] playlists, "
                f"[bold green]{len(library.liked_songs)}[/] liked songs, "
                f"[bold green]{len(library.saved_albums)}[/] saved albums, "
                f"[bold green]{len(library.followed_artists)}[/] followed artists"
            )

            def _apply() -> Path:
                return apply_pull_result(
                    adapter.provider_id,
                    library,
                    workspace_root=workspace_root,
                )

            out = await asyncio.to_thread(_apply)
            log_widget.write(f"\n[bold]Library saved to {out}[/]")
            self.query_one("#svc-status", Static).update(
                f"  {'Backup complete.' if is_backup else 'Pull complete.'}"
            )
        except asyncio.CancelledError:
            log_widget.write("\n[dim]Cancelled.[/]")
            self.query_one("#svc-status", Static).update("  Cancelled.")
            raise
        except Exception as exc:
            log_widget.write(f"[bold red]Error: {exc}[/]")
            self.query_one("#svc-status", Static).update(
                f"  {'Backup failed.' if is_backup else 'Pull failed.'}"
            )
        finally:
            root.removeHandler(bridge)
            # Always release the UI lock so the menu + detail pane work again after Pull/Backup.
            self._op_active = False
            self._update_status()
