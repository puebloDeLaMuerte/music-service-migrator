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

from rich.markup import escape
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Label, ListItem, ListView, RichLog, Static

from common import config
from common.catalog_adapters import CatalogPullAdapter, get_catalog_pull
from tui.app import LogBridge, LogHighlighter
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
        self.highlighter = LogHighlighter()

    async def on_click(self, event: events.Click) -> None:
        link = getattr(event.style, "link", None)
        if link:
            url = str(link).strip()
            if _is_usable_http_url(url):
                self.app.open_url(url)
                event.stop()


class SvcMenuItem(ListItem):
    """Sidebar row with a stable action id (not menu index)."""

    def __init__(self, action_id: str, label: str, *, disabled: bool = False) -> None:
        self.action_id = action_id
        super().__init__(Label(label, markup=True), disabled=disabled)


class ServiceView(BaseView):
    """Service actions: push mode (radio), data flow, local backup/wipe, account."""

    DEFAULT_CSS = """
    ServiceView { height: 1fr; width: 1fr; }
    #svc-main { height: 1fr; }
    #svc-main > Vertical { height: 1fr; }
    .svc-col-title {
        padding: 0 1;
        height: 1;
        text-style: bold;
        color: $text;
        background: $background;
    }
    .svc-col-gap { height: 1; background: $background; }
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
    #svc-menu > ListItem:disabled Label { color: $text-disabled; }
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
        from common.push.models import PushMode

        self._push_mode = PushMode.ADD

    def _mode_label(self, mode) -> str:
        from common.push.models import PushMode

        mark = r"\[*] " if self._push_mode == mode else r"\[ ] "
        names = {
            PushMode.ADD: "Push-Add",
            PushMode.DELETE: "Push-Delete",
            PushMode.WIPE: "Wipe-Push [dim](mirror)[/]",
        }
        return f"  {mark}{names[mode]}"

    def _mode_title(self) -> str:
        from common.push.report import MODE_TITLES

        return MODE_TITLES[self._push_mode.value]

    def _build_menu_items(self) -> list[SvcMenuItem]:
        from common.push.models import PushMode

        return [
            SvcMenuItem("hdr_mode", "  [bold dim]— push mode —[/]", disabled=True),
            SvcMenuItem("mode_add", self._mode_label(PushMode.ADD)),
            SvcMenuItem("mode_delete", self._mode_label(PushMode.DELETE)),
            SvcMenuItem("mode_wipe", self._mode_label(PushMode.WIPE)),
            SvcMenuItem("sep_flow", " ", disabled=True),
            SvcMenuItem("hdr_flow", "  [bold dim]— data flow —[/]", disabled=True),
            SvcMenuItem("pull", "  Pull Now"),
            SvcMenuItem("push_dry", "  Push (dry run)"),
            SvcMenuItem("push_inspect", "  Inspect Push Plan", disabled=True),
            SvcMenuItem("push_now", "  Push Now"),
            SvcMenuItem("sep_backup", " ", disabled=True),
            SvcMenuItem("backup", "  Backup"),
            SvcMenuItem("wipe_remote", "  [red]Wipe[/]"),
            SvcMenuItem("sep_account", " ", disabled=True),
            SvcMenuItem("hdr_account", "  [bold dim]— account —[/]", disabled=True),
            SvcMenuItem("login", "  Login"),
        ]

    def _refresh_menu_labels(self) -> None:
        from common.push.models import PushMode

        menu = self.query_one("#svc-menu", ListView)
        for item in menu.children:
            if not isinstance(item, SvcMenuItem):
                continue
            if item.action_id == "mode_add":
                item.query_one(Label).update(self._mode_label(PushMode.ADD))
            elif item.action_id == "mode_delete":
                item.query_one(Label).update(self._mode_label(PushMode.DELETE))
            elif item.action_id == "mode_wipe":
                item.query_one(Label).update(self._mode_label(PushMode.WIPE))

    def compose(self) -> ComposeResult:
        with Horizontal(id="svc-main"):
            with Vertical(id="svc-col-menu"):
                yield Static("Actions", classes="svc-col-title")
                yield Static("", classes="svc-col-gap")
                yield ListView(*self._build_menu_items(), id="svc-menu")
            with Vertical(id="svc-col-right"):
                yield Static("Details", id="svc-pane-title", classes="svc-col-title")
                yield Static("", classes="svc-col-gap")
                yield Static("", id="svc-detail", markup=True)
                yield LinkedRichLog(highlight=True, markup=True, id="svc-log")
        yield Static("", id="svc-status")

    def on_mount(self) -> None:
        self._show_pull_warning()
        self._update_status()
        self._refresh_inspect_availability()

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

    def _push_mode_blurb(self) -> str:
        from common.push.models import PushMode

        t = self._title
        if self._push_mode == PushMode.ADD:
            return (
                f"[bold]Push-Add[/] — adds everything in Local Data to {t}; nothing is "
                f"removed there. Existing playlists keep tracks that are only on {t}."
            )
        if self._push_mode == PushMode.DELETE:
            return (
                f"[bold]Push-Delete[/] — like Push-Add, and also removes on {t} what you "
                "removed locally (unliked songs, tracks taken out of playlists, removed "
                "playlists, albums and artists). Unliking a song does not remove it "
                "from playlists."
            )
        return (
            f"[bold]Wipe-Push[/] — {t} becomes an exact copy of Local Data: anything on "
            f"{t} that is not in Local Data is removed, piece by piece. Local files "
            "and other services are untouched."
        )

    def _write_scope_hint(self) -> str:
        if self._service != "spotify":
            return ""
        from spotify.client import token_lacks_push_scopes

        if not token_lacks_push_scopes():
            return ""
        return (
            "[yellow]Your Spotify sign-in predates write access. Use Account → Login "
            "once before pushing.[/]\n\n"
        )

    def _show_push_dry_details(self) -> None:
        text = (
            f"[bold]{self._title} — Push (dry run)[/]\n\n"
            f"{self._write_scope_hint()}"
            f"{self._push_mode_blurb()}\n\n"
            "Source: everything under [bold]Local Data[/] in the sidebar.\n\n"
            f"Reads your current {self._title} library and searches the catalog for "
            f"every item. Nothing is changed on {self._title}. The report lists what "
            "would change; items with several possible matches come first and must be "
            "settled in [bold]Inspect Push Plan[/] before Push Now.\n\n"
            "Press [bold]Enter[/] to run the dry run."
        )
        self.query_one("#svc-detail", Static).update(text)

    def _show_push_inspect_details(self) -> None:
        from common.push.planner import inspectable_plan
        from tui.views.push_plan_modal import decision_rows

        plan = inspectable_plan(self._service, self._push_mode)
        head = f"[bold]{self._title} — Inspect Push Plan[/] ({self._mode_title()})\n\n"
        if plan is None:
            body = (
                "No current dry run for this mode. Run [bold]Push (dry run)[/] first — "
                "a plan no longer counts once Local Data changes."
            )
        else:
            rows = decision_rows(plan)
            pending = sum(1 for r in rows if r["status"] == "ambiguous")
            state = (
                f"[bold yellow]{pending} item(s) need your decision.[/]"
                if pending
                else "[green]Nothing is waiting for a decision.[/]"
            )
            body = (
                f"{state}\n\n"
                "Pick the right match for each item, or exclude it from pushing. "
                "Earlier decisions are listed too and can be undone.\n\n"
                "Press [bold]Enter[/] to open."
            )
        self.query_one("#svc-detail", Static).update(head + body)

    def _show_push_now_details(self) -> None:
        text = (
            f"[bold]{self._title} — Push Now[/]\n\n"
            f"{self._write_scope_hint()}"
            f"{self._push_mode_blurb()}\n\n"
            "Uses the last dry run for this mode. If Local Data, recorded removals, "
            "your decisions or the matching rules changed since, it plans again first. "
            "You see a summary and confirm before anything is written.\n\n"
            "If a previous Push Now stopped midway, running it again continues where "
            "it left off.\n\n"
            "Press [bold]Enter[/] to start."
        )
        self.query_one("#svc-detail", Static).update(text)

    def _show_wipe_remote_details(self) -> None:
        text = (
            f"[bold red]{self._title} — Wipe[/]\n\n"
            f"[bold red]Empties your {self._title} account library.[/]\n\n"
            "Removes, piece by piece:\n"
            "  • all playlists (yours are deleted, followed ones unfollowed)\n"
            "  • liked songs\n"
            "  • saved albums\n"
            "  • followed artists\n\n"
            "Local Data and other services are not touched. Afterwards, "
            '"Resist" by Wipers is added to your liked songs.\n\n'
            f"{self._write_scope_hint()}"
            "Press [bold]Enter[/] to see what would be removed; you confirm before "
            "anything happens."
        )
        self.query_one("#svc-detail", Static).update(text)

    def _show_push_mode_pick_details(self, preview_mode=None) -> None:
        from common.push.models import PushMode

        mode = preview_mode or self._push_mode
        saved = self._push_mode
        self._push_mode = mode
        blurb = self._push_mode_blurb()
        self._push_mode = saved
        text = (
            f"[bold]{self._title} — Push mode[/]\n\n"
            f"{blurb}\n\n"
            "Press [bold]Enter[/] to select this mode ([*] marker)."
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

    def _menu_action_id(self, event: ListView.Highlighted | ListView.Selected) -> str | None:
        item = event.item
        if isinstance(item, SvcMenuItem):
            return item.action_id
        return None

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id != "svc-menu" or self._op_active:
            return
        aid = self._menu_action_id(event)
        if not aid or aid.startswith(("hdr_", "sep_")):
            return
        from common.push.models import PushMode

        self._reveal_menu_detail_pane()
        if aid == "pull":
            self._show_pull_warning()
        elif aid == "mode_add":
            self._show_push_mode_pick_details(PushMode.ADD)
        elif aid == "mode_delete":
            self._show_push_mode_pick_details(PushMode.DELETE)
        elif aid == "mode_wipe":
            self._show_push_mode_pick_details(PushMode.WIPE)
        elif aid == "push_dry":
            self._show_push_dry_details()
        elif aid == "push_inspect":
            self._show_push_inspect_details()
        elif aid == "push_now":
            self._show_push_now_details()
        elif aid == "backup":
            self._show_backup_details()
        elif aid == "wipe_remote":
            self._show_wipe_remote_details()
        elif aid == "login":
            self._show_login_details()
        event.stop()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id != "svc-menu" or self._op_active:
            event.stop()
            return
        aid = self._menu_action_id(event)
        if not aid:
            event.stop()
            return
        from common.push.models import PushMode

        modes = {"mode_add": PushMode.ADD, "mode_delete": PushMode.DELETE, "mode_wipe": PushMode.WIPE}
        if aid in modes:
            self._push_mode = modes[aid]
            self._refresh_menu_labels()
            self._show_push_mode_pick_details()
            self._refresh_inspect_availability()
        elif aid == "pull":
            self._start_pull()
        elif aid == "push_dry":
            self._start_push_dry()
        elif aid == "push_inspect":
            self._start_push_inspect()
        elif aid == "push_now":
            self._start_push_now()
        elif aid == "backup":
            self._start_backup()
        elif aid == "wipe_remote":
            self._start_wipe_remote()
        elif aid == "login":
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

    # ── Push ────────────────────────────────────────────────────────

    def _refresh_inspect_availability(self) -> None:
        self.run_worker(self._do_refresh_inspect(), group="svc-inspect", exclusive=True)

    async def _do_refresh_inspect(self) -> None:
        from common.push.planner import inspectable_plan

        try:
            plan = await asyncio.to_thread(inspectable_plan, self._service, self._push_mode)
        except Exception:
            plan = None
        for item in self.query_one("#svc-menu", ListView).children:
            if isinstance(item, SvcMenuItem) and item.action_id == "push_inspect":
                item.disabled = plan is None

    def _log(self) -> LinkedRichLog:
        return self.query_one("#svc-log", LinkedRichLog)

    def _set_status(self, text: str) -> None:
        self.query_one("#svc-status", Static).update(f"  {text}")

    def _attach_log_bridge(self) -> logging.Handler:
        bridge = LogBridge(self._log())
        bridge.setFormatter(logging.Formatter("%(message)s"))
        logging.getLogger().addHandler(bridge)
        return bridge

    def _write_push_error(self, exc: Exception) -> None:
        from common.push.errors import PushError, PushErrorCode

        log_widget = self._log()
        if isinstance(exc, PushError):
            log_widget.write(f"[bold red]{escape(exc.message)}[/]")
            if exc.code == PushErrorCode.REMOTE_ERROR:
                log_widget.write("Run Push Now again to continue where it stopped.")
        else:
            log_widget.write(f"[bold red]Error: {escape(str(exc))}[/]")

    def _start_push_dry(self) -> None:
        self._switch_to_log()
        self.run_worker(self._do_push_dry(), group="svc-op")

    def _start_push_inspect(self) -> None:
        from common.push.planner import inspectable_plan
        from tui.views.push_plan_modal import PushPlanModal

        plan = inspectable_plan(self._service, self._push_mode)
        if plan is None:
            self._show_push_inspect_details()
            self._refresh_inspect_availability()
            return
        self.app.push_screen(PushPlanModal(plan), self._after_inspect)

    def _after_inspect(self, changed: bool | None) -> None:
        self._reveal_menu_detail_pane()
        if changed:
            self.query_one("#svc-detail", Static).update(
                f"[bold]{self._title} — Inspect Push Plan[/]\n\n"
                "[green]Decisions saved.[/]\n\n"
                "Run [bold]Push (dry run)[/] to see the updated plan, or go straight to "
                "[bold]Push Now[/] — it plans again with your decisions first."
            )
        else:
            self._show_push_inspect_details()

    def _start_push_now(self) -> None:
        self._switch_to_log()
        self.run_worker(self._do_push_now(), group="svc-op")

    def _start_wipe_remote(self) -> None:
        self._switch_to_log()
        self.run_worker(self._do_wipe_remote_plan(), group="svc-op")

    async def _do_push_dry(self) -> None:
        from common.push.planner import dry_run_push
        from common.push.report import format_plan_report

        log_widget = self._log()
        log_widget.write(f"[bold]Push (dry run) → {self._title} · {self._mode_title()}[/]\n")
        bridge = self._attach_log_bridge()
        try:
            plan = await asyncio.to_thread(dry_run_push, self._service, self._push_mode)
            log_widget.write("")
            log_widget.write(escape(format_plan_report(plan)))
            self._set_status("Dry run complete.")
        except Exception as exc:
            self._write_push_error(exc)
            self._set_status("Dry run failed.")
        finally:
            logging.getLogger().removeHandler(bridge)
            self._op_active = False
            self._update_status()
            self._refresh_inspect_availability()

    async def _do_push_now(self) -> None:
        from common.push.planner import prepare_push
        from common.push.report import confirm_summary, format_plan_report
        from tui.views.p2a_view import ConfirmModal

        log_widget = self._log()
        log_widget.write(f"[bold]Push Now → {self._title} · {self._mode_title()}[/]\n")
        bridge = self._attach_log_bridge()
        try:
            plan, refreshed = await asyncio.to_thread(prepare_push, self._service, self._push_mode)
        except Exception as exc:
            self._write_push_error(exc)
            self._set_status("Push failed.")
            return
        finally:
            logging.getLogger().removeHandler(bridge)
            self._op_active = False
            self._update_status()
            self._refresh_inspect_availability()

        if refreshed:
            log_widget.write("Things changed since the last dry run — planned again:\n")
            log_widget.write(escape(format_plan_report(plan)))
        summary = plan.get("summary") or {}
        if not summary.get("can_apply"):
            log_widget.write(f"\n[bold yellow]{escape(summary.get('blocking_reason') or 'Blocked.')}[/]")
            self._set_status("Push blocked — decisions needed.")
            return
        if not plan.get("operations"):
            log_widget.write(f"\n[green]{self._title} already matches — nothing to change.[/]")
            self._set_status("Nothing to push.")
            return
        body = (
            f"[bold]Push Now → {self._title} · {self._mode_title()}[/]\n\n"
            f"{escape(confirm_summary(plan))}\n\n"
            f"Apply these changes to {self._title}?"
        )
        self.app.push_screen(ConfirmModal(body), lambda ok: self._after_push_confirm(ok, plan))

    async def _do_wipe_remote_plan(self) -> None:
        from common.push.planner import dry_run_remote_wipe
        from common.push.report import format_plan_report
        from tui.views.p2a_view import ConfirmModal

        log_widget = self._log()
        log_widget.write(f"[bold]Wipe → {self._title}[/]\n")
        bridge = self._attach_log_bridge()
        try:
            plan = await asyncio.to_thread(dry_run_remote_wipe, self._service)
        except Exception as exc:
            self._write_push_error(exc)
            self._set_status("Wipe failed.")
            return
        finally:
            logging.getLogger().removeHandler(bridge)
            self._op_active = False
            self._update_status()
            self._refresh_inspect_availability()

        log_widget.write(escape(format_plan_report(plan)))
        rc = plan.get("removal_counts") or {}
        body = (
            f"[bold red]Wipe your {self._title} library?[/]\n\n"
            f"{rc.get('playlists', 0)} playlists, {rc.get('liked_songs', 0)} liked songs, "
            f"{rc.get('saved_albums', 0)} saved albums and {rc.get('followed_artists', 0)} "
            f"followed artists will be removed from {self._title}.\n\n"
            "This cannot be undone on the service. Local Data stays as it is."
        )
        self.app.push_screen(ConfirmModal(body), lambda ok: self._after_push_confirm(ok, plan))

    def _after_push_confirm(self, ok: bool | None, plan: dict) -> None:
        if not ok:
            self._log().write(f"\nCancelled — nothing was changed on {self._title}.")
            self._set_status("Cancelled.")
            return
        self._op_active = True
        self._update_status()
        self.run_worker(self._do_apply(plan), group="svc-op")

    async def _do_apply(self, plan: dict) -> None:
        from common.push.executor import execute_plan
        from common.push.registry import get_push_backend

        log_widget = self._log()
        log_widget.write(f"\n[bold]Applying to {self._title}…[/]")

        def progress(i: int, n: int, text: str) -> None:
            self.app.call_from_thread(log_widget.write, escape(f"  step {i} of {n}: {text}"))

        def run() -> dict:
            return execute_plan(get_push_backend(self._service), plan, on_progress=progress)

        bridge = self._attach_log_bridge()
        try:
            await asyncio.to_thread(run)
            log_widget.write(f"\n[bold green]Done — {self._title} is updated.[/]")
            self._set_status("Push complete.")
        except Exception as exc:
            self._write_push_error(exc)
            self._set_status("Push stopped.")
        finally:
            logging.getLogger().removeHandler(bridge)
            self._op_active = False
            self._update_status()
            self._refresh_inspect_availability()

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
            self._refresh_inspect_availability()
