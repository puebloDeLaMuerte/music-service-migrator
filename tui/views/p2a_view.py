"""Playlist-to-album view — the most interactive screen.

Layout: playlist list | action buttons | detail pane.
"""

from __future__ import annotations

import asyncio
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Label,
    ListItem,
    ListView,
    Static,
)

from tui.views.base import BaseView


# ── Modals ───────────────────────────────────────────────────────────────────


class ConfirmModal(ModalScreen[bool]):
    BINDINGS = [
        Binding("y", "confirm_yes", "Yes", show=True),
        Binding("n", "confirm_no", "No", show=True),
        Binding("escape", "confirm_no", "Cancel"),
    ]

    CSS = """
    ConfirmModal { align: center middle; }
    #confirm-box {
        width: 60; height: auto; max-height: 20;
        border: thick $accent; background: $surface; padding: 1 2;
    }
    """

    def __init__(self, body: str) -> None:
        super().__init__()
        self._body = body

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Static(self._body)
            yield Static(
                "\n[bold]y[/] = apply   [bold]n[/] / ESC = cancel", markup=True
            )

    def action_confirm_yes(self) -> None:
        self.dismiss(True)

    def action_confirm_no(self) -> None:
        self.dismiss(False)


class LeftoversModal(ModalScreen[bool]):
    BINDINGS = [
        Binding("y", "yes", "Keep", show=True),
        Binding("n", "no", "Discard", show=True),
        Binding("escape", "yes", "Keep"),
    ]

    CSS = """
    LeftoversModal { align: center middle; }
    #leftovers-box {
        width: 55; height: auto;
        border: thick $warning; background: $surface; padding: 1 2;
    }
    """

    def __init__(self, count: int) -> None:
        super().__init__()
        self._count = count

    def compose(self) -> ComposeResult:
        with Vertical(id="leftovers-box"):
            yield Static(
                f"[bold]{self._count}[/] loose tracks remain.\n"
                "Keep as trimmed playlist?",
                markup=True,
            )
            yield Static(
                "\n[bold]y[/] = keep   [bold]n[/] = discard", markup=True
            )

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)


# ── P2A view ─────────────────────────────────────────────────────────────────

_ACTION_METHODS = [
    "action_extract",
    "action_complete_extract",
    "action_skip",
    "action_apply",
]


class P2AView(BaseView):
    BINDINGS: ClassVar = [
        Binding("e", "extract", show=False),
        Binding("c", "complete_extract", show=False),
        Binding("s", "skip", show=False),
        Binding("a", "apply", show=False),
    ]

    DEFAULT_CSS = """
    P2AView { height: 1fr; width: 1fr; }
    #p2a-main { height: 1fr; }
    #playlist-list {
        width: 1fr;
        min-width: 28;
        border-right: solid $primary-background-lighten-2;
    }
    #p2a-actions {
        width: 22;
        border-right: solid $primary-background-lighten-2;
    }
    #detail {
        width: 2fr;
        padding: 1 2;
        overflow-y: auto;
    }
    #p2a-status {
        dock: bottom;
        height: 1;
        background: $surface;
        color: $text;
        padding: 0 1;
    }
    """

    def __init__(self, playlist_filter: str | None = None) -> None:
        super().__init__()
        self._filter = playlist_filter
        self._results: list = []
        self._actions_queue: list = []
        self._decided: set[int] = set()

    def compose(self) -> ComposeResult:
        with Horizontal(id="p2a-main"):
            yield ListView(id="playlist-list")
            yield ListView(
                ListItem(Label("  [e] Extract")),
                ListItem(Label("  [c] Complete+Extract")),
                ListItem(Label("  [s] Skip")),
                ListItem(Label("  [a] Apply queued")),
                id="p2a-actions",
            )
            yield Static("Loading…", id="detail", markup=True)
        yield Static("Loading library…", id="p2a-status")

    def on_mount(self) -> None:
        self.run_worker(self._load_data(), group="p2a-load")

    # ── Column navigation (called by MigratorApp) ─────────────────

    def zone_left(self) -> None:
        focused = self.app.focused
        if focused and getattr(focused, "id", None) == "p2a-actions":
            self.query_one("#playlist-list").focus()
        else:
            self.app._focus_sidebar()

    def zone_right(self) -> None:
        focused = self.app.focused
        if focused and getattr(focused, "id", None) == "playlist-list":
            self.query_one("#p2a-actions").focus()

    # ── Event routing ───────────────────────────────────────────────

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id == "playlist-list" and event.item is not None:
            idx = event.list_view.index
            if idx is not None:
                self._show_detail(idx)
            event.stop()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "p2a-actions":
            idx = event.list_view.index
            if idx is not None and idx < len(_ACTION_METHODS):
                method = getattr(self, _ACTION_METHODS[idx], None)
                if callable(method):
                    method()
            event.stop()
        elif event.list_view.id == "playlist-list":
            event.stop()

    # ── Data loading ────────────────────────────────────────────────

    async def _load_data(self) -> None:
        from common.store import load_library
        from spotify.album_detect import analyse_playlist

        library = await asyncio.to_thread(load_library, "spotify")

        if not library.playlists:
            self.query_one("#detail", Static).update(
                "[yellow]No playlists. Run 'spotify pull' first.[/]"
            )
            return

        playlists = library.playlists
        if self._filter:
            needle = self._filter.lower()
            playlists = [p for p in playlists if needle in p.name.lower()]
            if not playlists:
                self.query_one("#detail", Static).update(
                    f"[yellow]No playlist matching '{self._filter}'.[/]"
                )
                return

        saved_ids = {
            sa.album.service_id
            for sa in library.saved_albums
            if sa.album.service_id
        }

        for pl in playlists:
            result = analyse_playlist(pl, saved_album_ids=saved_ids)
            if result.album_groups:
                self._results.append((pl, result))

        if not self._results:
            self.query_one("#detail", Static).update(
                "No playlists with detected albums (>= 80% match)."
            )
            self._update_status()
            return

        lv = self.query_one("#playlist-list", ListView)
        for pl, _ in self._results:
            lv.append(ListItem(Label(pl.name)))

        self._update_status()
        if self._results:
            lv.index = 0
            self._show_detail(0)

    # ── Detail display ──────────────────────────────────────────────

    def _show_detail(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._results):
            return
        pl, result = self._results[idx]
        lines: list[str] = []
        lines.append(f"[bold]'{pl.name}'[/] ({pl.track_count} tracks)\n")
        lines.append("[underline]Albums found:[/]")
        for i, ag in enumerate(result.album_groups, 1):
            if ag.is_complete:
                status = "[green]complete[/]"
            else:
                status = f"{ag.match_ratio:.0%}"
            pct = f"({ag.present_count}/{ag.album_total_tracks})"
            in_lib = " [dim]\\[in your library][/]" if ag.in_library else ""
            artist = (
                f" [italic]by {ag.album_artists}[/]" if ag.album_artists else ""
            )
            lines.append(f"  {i}. [bold]{ag.album_name}[/]{artist}")
            lines.append(f"     {status} {pct}{in_lib}")
            if ag.missing_tracks:
                lines.append(
                    f"     [yellow]missing: {', '.join(ag.missing_tracks)}[/]"
                )
        if result.loose_track_count:
            lines.append(
                f"\n  + [yellow]{result.loose_track_count}[/] loose tracks"
            )

        if idx in self._decided:
            action = next(
                (a for a in self._actions_queue if a.playlist is pl), None
            )
            if action:
                lines.append(
                    f"\n[green]✓ Queued: extract "
                    f"{action.albums_to_extract} album(s)[/]"
                )
            else:
                lines.append("\n[dim]— Skipped[/]")

        self.query_one("#detail", Static).update("\n".join(lines))

    def _update_status(self) -> None:
        total_albums = sum(a.albums_to_extract for a in self._actions_queue)
        msg = (
            f"  {len(self._results)} playlist(s)  ·  "
            f"Queued: {len(self._actions_queue)} action(s), "
            f"{total_albums} album(s)"
        )
        self.query_one("#p2a-status", Static).update(msg)

    # ── Navigation helpers ──────────────────────────────────────────

    def _current_index(self) -> int | None:
        return self.query_one("#playlist-list", ListView).index

    def _advance(self) -> None:
        lv = self.query_one("#playlist-list", ListView)
        if lv.index is None:
            return
        start = lv.index + 1
        for i in range(start, len(self._results)):
            if i not in self._decided:
                lv.index = i
                self._show_detail(i)
                return

    # ── Action queue ────────────────────────────────────────────────

    def _queue_action(self, flag_missing: bool) -> None:
        idx = self._current_index()
        if idx is None or idx in self._decided:
            return
        _, result = self._results[idx]

        if result.loose_track_count > 0:
            self.app.push_screen(
                LeftoversModal(result.loose_track_count),
                callback=lambda keep: self._finish_queue(
                    idx, flag_missing, keep
                ),
            )
        else:
            self._finish_queue(idx, flag_missing, keep_leftovers=True)

    def _finish_queue(
        self, idx: int, flag_missing: bool, keep_leftovers: bool
    ) -> None:
        from data.playlist2album import Action

        pl, result = self._results[idx]
        self._actions_queue.append(
            Action(
                playlist=pl,
                analysis=result,
                album_groups=result.album_groups,
                keep_leftovers=keep_leftovers,
                flag_missing=flag_missing,
            )
        )
        self._decided.add(idx)
        self._update_status()
        self._show_detail(idx)
        self._advance()

    # ── Key / action-button methods ─────────────────────────────────

    def action_extract(self) -> None:
        self._queue_action(flag_missing=False)

    def action_complete_extract(self) -> None:
        self._queue_action(flag_missing=True)

    def action_skip(self) -> None:
        idx = self._current_index()
        if idx is None or idx in self._decided:
            return
        self._decided.add(idx)
        self._update_status()
        self._show_detail(idx)
        self._advance()

    def action_apply(self) -> None:
        if not self._actions_queue:
            return

        lines = ["[bold]Apply these changes?[/]\n"]
        for a in self._actions_queue:
            albums = ", ".join(ag.album_name for ag in a.album_groups)
            outcome = (
                f"trim to {a.tracks_remaining} tracks"
                if a.keep_leftovers and a.tracks_remaining > 0
                else "delete"
            )
            lines.append(f"  [bold]{a.playlist_name}[/]")
            lines.append(f"    extract: {albums}")
            lines.append(f"    playlist: {outcome}")
        total = sum(a.albums_to_extract for a in self._actions_queue)
        lines.append(
            f"\n  Total: {total} album(s) from "
            f"{len(self._actions_queue)} playlist(s)"
        )

        self.app.push_screen(
            ConfirmModal("\n".join(lines)),
            callback=self._on_apply_confirmed,
        )

    def _on_apply_confirmed(self, confirmed: bool) -> None:
        if not confirmed:
            return
        self.run_worker(self._do_apply(), group="p2a-apply")

    async def _do_apply(self) -> None:
        from data.playlist2album import apply_actions

        summary = await asyncio.to_thread(
            apply_actions, self._actions_queue, "spotify"
        )
        detail = self.query_one("#detail", Static)
        detail.update(
            f"[bold green]Done![/]\n\n"
            f"  {summary['albums_added']} album(s) added\n"
            f"  {summary['playlists_modified']} playlist(s) trimmed\n"
            f"  {summary['playlists_deleted']} playlist(s) deleted\n\n"
            f"[dim]Done.[/]"
        )
        self.query_one("#p2a-status", Static).update("  Changes applied.")
