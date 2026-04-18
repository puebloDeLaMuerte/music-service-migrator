"""TUI screen for 'data playlist2album' — the most interactive screen.

Left pane: list of playlists with detected albums.
Right pane: detail view for the highlighted playlist.
Footer: queued action count, apply shortcut.
"""

from __future__ import annotations

import asyncio
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Footer,
    Header,
    Label,
    ListItem,
    ListView,
    Static,
)

from common.models import Playlist
from data.playlist2album import Action, apply_actions
from spotify.album_detect import PlaylistAnalysis, analyse_playlist
from tui.app import APP_TITLE


# ── Confirm modal ────────────────────────────────────────────────────────────


class ConfirmModal(ModalScreen[bool]):
    """Yes / No confirmation dialog."""

    BINDINGS = [
        Binding("y", "confirm_yes", "Yes", show=True),
        Binding("n", "confirm_no", "No", show=True),
        Binding("escape", "confirm_no", "Cancel"),
    ]

    CSS = """
    ConfirmModal {
        align: center middle;
    }
    #confirm-box {
        width: 60;
        height: auto;
        max-height: 20;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    """

    def __init__(self, body: str) -> None:
        super().__init__()
        self._body = body

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Static(self._body)
            yield Static("\n[bold]y[/] = apply   [bold]n[/] / ESC = cancel", markup=True)

    def action_confirm_yes(self) -> None:
        self.dismiss(True)

    def action_confirm_no(self) -> None:
        self.dismiss(False)


# ── Leftovers modal ──────────────────────────────────────────────────────────


class LeftoversModal(ModalScreen[bool]):
    """Ask whether to keep loose tracks."""

    BINDINGS = [
        Binding("y", "yes", "Keep", show=True),
        Binding("n", "no", "Discard", show=True),
        Binding("escape", "yes", "Keep"),
    ]

    CSS = """
    LeftoversModal {
        align: center middle;
    }
    #leftovers-box {
        width: 55;
        height: auto;
        border: thick $warning;
        background: $surface;
        padding: 1 2;
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
            yield Static("\n[bold]y[/] = keep   [bold]n[/] = discard", markup=True)

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)


# ── Main app ─────────────────────────────────────────────────────────────────


class P2AApp(App):
    BINDINGS: ClassVar = [
        Binding("e", "extract", "Extract", show=True),
        Binding("c", "complete_extract", "Complete+Extract", show=True),
        Binding("s", "skip", "Skip", show=True),
        Binding("a", "apply", "Apply queued", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    CSS = """
    #main {
        height: 1fr;
    }
    #playlist-list {
        width: 1fr;
        min-width: 30;
        border-right: solid $accent;
    }
    #detail {
        width: 2fr;
        padding: 1 2;
        overflow-y: auto;
    }
    #status-bar {
        dock: bottom;
        height: 1;
        background: $surface;
        color: $text;
        padding: 0 1;
    }
    .queued {
        color: $success;
    }
    .skipped {
        color: $text-muted;
    }
    """

    def __init__(self, playlist_filter: str | None = None) -> None:
        super().__init__()
        self._filter = playlist_filter
        self._results: list[tuple[Playlist, PlaylistAnalysis]] = []
        self._actions: list[Action] = []
        self._decided: set[int] = set()

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main"):
            yield ListView(id="playlist-list")
            yield Static("Loading…", id="detail", markup=True)
        yield Static("Loading library…", id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        self.title = APP_TITLE
        self.sub_title = "playlist → album"
        self.run_worker(self._load_data(), exclusive=True)

    async def _load_data(self) -> None:
        from common.store import load_library

        library = await asyncio.to_thread(load_library, "spotify")

        if not library.playlists:
            self.query_one("#detail", Static).update(
                "[red]No playlists. Run 'spotify pull' first.[/]"
            )
            return

        playlists = library.playlists
        if self._filter:
            needle = self._filter.lower()
            playlists = [p for p in playlists if needle in p.name.lower()]
            if not playlists:
                self.query_one("#detail", Static).update(
                    f"[red]No playlist matching '{self._filter}'.[/]"
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

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item is not None:
            idx = self.query_one("#playlist-list", ListView).index
            if idx is not None:
                self._show_detail(idx)

    def _show_detail(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._results):
            return
        pl, result = self._results[idx]
        lines: list[str] = []
        lines.append(f"[bold]'{pl.name}'[/] ({pl.track_count} tracks)\n")
        lines.append("[underline]Albums found:[/]")
        for i, ag in enumerate(result.album_groups, 1):
            status = "complete" if ag.is_complete else f"{ag.match_ratio:.0%}"
            pct = f"({ag.present_count}/{ag.album_total_tracks})"
            in_lib = " [dim]\\[in your library][/]" if ag.in_library else ""
            artist = f" [italic]by {ag.album_artists}[/]" if ag.album_artists else ""
            lines.append(f"  {i}. [bold]{ag.album_name}[/]{artist}")
            lines.append(f"     {status} {pct}{in_lib}")
            if ag.missing_tracks:
                lines.append(f"     [yellow]missing: {', '.join(ag.missing_tracks)}[/]")
        if result.loose_track_count:
            lines.append(f"\n  + [yellow]{result.loose_track_count}[/] loose tracks")

        if idx in self._decided:
            action = next((a for a in self._actions if a.playlist is pl), None)
            if action:
                lines.append(f"\n[green]✓ Queued: extract {action.albums_to_extract} album(s)[/]")
            else:
                lines.append("\n[dim]— Skipped[/]")

        self.query_one("#detail", Static).update("\n".join(lines))

    def _update_status(self) -> None:
        total_albums = sum(a.albums_to_extract for a in self._actions)
        msg = (
            f"  {len(self._results)} playlist(s)  ·  "
            f"Queued: {len(self._actions)} action(s), {total_albums} album(s)  ·  "
            f"[a]pply  [q]uit"
        )
        self.query_one("#status-bar", Static).update(msg)

    def _current_index(self) -> int | None:
        return self.query_one("#playlist-list", ListView).index

    def _advance(self) -> None:
        """Move highlight to the next undecided playlist."""
        lv = self.query_one("#playlist-list", ListView)
        if lv.index is None:
            return
        start = lv.index + 1
        for i in range(start, len(self._results)):
            if i not in self._decided:
                lv.index = i
                self._show_detail(i)
                return

    def _queue_action(self, flag_missing: bool) -> None:
        idx = self._current_index()
        if idx is None or idx in self._decided:
            return
        pl, result = self._results[idx]

        if result.loose_track_count > 0:
            self.push_screen(
                LeftoversModal(result.loose_track_count),
                callback=lambda keep: self._finish_queue(idx, flag_missing, keep),
            )
        else:
            self._finish_queue(idx, flag_missing, keep_leftovers=True)

    def _finish_queue(self, idx: int, flag_missing: bool, keep_leftovers: bool) -> None:
        pl, result = self._results[idx]
        self._actions.append(Action(
            playlist=pl,
            analysis=result,
            album_groups=result.album_groups,
            keep_leftovers=keep_leftovers,
            flag_missing=flag_missing,
        ))
        self._decided.add(idx)
        self._update_status()
        self._show_detail(idx)
        self._advance()

    # ── Key actions ──────────────────────────────────────────────────────

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
        if not self._actions:
            return

        lines = ["[bold]Apply these changes?[/]\n"]
        for a in self._actions:
            albums = ", ".join(ag.album_name for ag in a.album_groups)
            outcome = (
                f"trim to {a.tracks_remaining} tracks"
                if a.keep_leftovers and a.tracks_remaining > 0
                else "delete"
            )
            lines.append(f"  [bold]{a.playlist_name}[/]")
            lines.append(f"    extract: {albums}")
            lines.append(f"    playlist: {outcome}")
        total = sum(a.albums_to_extract for a in self._actions)
        lines.append(f"\n  Total: {total} album(s) from {len(self._actions)} playlist(s)")

        self.push_screen(
            ConfirmModal("\n".join(lines)),
            callback=self._on_apply_confirmed,
        )

    def _on_apply_confirmed(self, confirmed: bool) -> None:
        if not confirmed:
            return
        self.run_worker(self._do_apply(), exclusive=True)

    async def _do_apply(self) -> None:
        summary = await asyncio.to_thread(apply_actions, self._actions, "spotify")
        detail = self.query_one("#detail", Static)
        detail.update(
            f"[bold green]Done![/]\n\n"
            f"  {summary['albums_added']} album(s) added\n"
            f"  {summary['playlists_modified']} playlist(s) trimmed\n"
            f"  {summary['playlists_deleted']} playlist(s) deleted\n\n"
            f"[dim]Press q to quit.[/]"
        )
        self.query_one("#status-bar", Static).update("  Changes applied.  ·  [q]uit")
