"""Playlist-to-album view — tree playlist list, per-album extract, instant apply.

Layout: playlist tree | actions | detail pane.
"""

from __future__ import annotations

import asyncio
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, ListItem, ListView, Static

from common.config import p2a_always_keep_leftovers
from tui.transient_status import TransientStatus
from tui.views.base import BaseView


# ── List row metadata ───────────────────────────────────────────────────────


class P2AListItem(ListItem):
    """Sidebar row: playlist parent (album_idx None) or └ album child."""

    def __init__(
        self,
        label: Label,
        *,
        playlist_idx: int,
        album_idx: int | None,
    ) -> None:
        super().__init__(label)
        self.p2a_playlist_idx = playlist_idx
        self.p2a_album_idx = album_idx


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
        width: 62; height: auto; max-height: 22;
        border: thick $accent; background: $surface; padding: 1 2;
    }
    """

    def __init__(self, body: str) -> None:
        super().__init__()
        self._body = body

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Static(self._body, markup=True)
            yield Static(
                "\n[bold]y[/] = confirm   [bold]n[/] / ESC = cancel", markup=True
            )

    def action_confirm_yes(self) -> None:
        self.dismiss(True)

    def action_confirm_no(self) -> None:
        self.dismiss(False)


class LeftoversModal(ModalScreen[bool]):
    """keep_remaining=True → save trimmed playlist; False → delete playlist file."""

    BINDINGS = [
        Binding("y", "yes", "Keep file", show=True),
        Binding("n", "no", "Delete playlist", show=True),
        Binding("escape", "yes", "Keep file"),
    ]

    CSS = """
    LeftoversModal { align: center middle; }
    #leftovers-box {
        width: 58; height: auto;
        border: thick $warning; background: $surface; padding: 1 2;
    }
    """

    def __init__(self, body: str) -> None:
        super().__init__()
        self._body = body

    def compose(self) -> ComposeResult:
        with Vertical(id="leftovers-box"):
            yield Static(self._body, markup=True)
            yield Static(
                "\n[bold]y[/] = keep playlist file with remaining tracks\n"
                "[bold]n[/] = delete entire playlist file",
                markup=True,
            )

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)


# ── P2A view ─────────────────────────────────────────────────────────────────

_ACTION_METHODS = [
    "action_extract_delete",
    "action_extract_keep",
    "action_keep",
]

# One-line status tooltips when an action row is highlighted (Rich markup).
_P2A_ACTION_TOOLTIPS: tuple[str, ...] = (
    r"  [yellow]\[d] Extract+delete: write album(s) to saved library and remove those "
    r"tracks from this playlist file (confirms; may ask about leftover tracks).[/]",
    r"  [yellow]\[v] Extract+keep: write album(s) to saved library; playlist file stays "
    r"unchanged (tracks remain listed).[/]",
    r"  [yellow]\[n] Keep: do nothing to disk for this selection—pick another row or action.[/]",
)


class P2AView(BaseView):
    """List columns use Textual's default ListView fill ($surface); detail has no extra tint
    (main $background). Album lines use [on $surface] to match the list columns."""

    BINDINGS: ClassVar = [
        Binding("d", "extract_delete", show=False),
        Binding("v", "extract_keep", show=False),
        Binding("n", "keep", show=False),
    ]

    DEFAULT_CSS = """
    P2AView { height: 1fr; width: 1fr; }
    #p2a-main { height: 1fr; }
    #p2a-main > Vertical {
        height: 1fr;
    }
    .p2a-col-title {
        padding: 0 1;
        height: 1;
        text-style: bold;
        color: $text;
    }
    .p2a-col-gap {
        height: 1;
    }
    #p2a-col-playlists .p2a-col-title,
    #p2a-col-playlists .p2a-col-gap,
    #p2a-col-actions .p2a-col-title,
    #p2a-col-actions .p2a-col-gap {
        background: $surface;
    }
    #p2a-col-detail .p2a-col-title,
    #p2a-col-detail .p2a-col-gap {
        background: $background;
    }
    #p2a-col-playlists {
        width: 1fr;
        min-width: 28;
        border-right: solid $primary-background-lighten-2;
    }
    #p2a-col-playlists #playlist-list {
        height: 1fr;
    }
    #p2a-col-actions {
        width: 24;
        border-right: solid $primary-background-lighten-2;
    }
    #p2a-col-actions #p2a-actions {
        height: 1fr;
    }
    #p2a-col-detail {
        width: 2fr;
    }
    #detail {
        height: 1fr;
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
        self._results: list[tuple] = []

    def compose(self) -> ComposeResult:
        with Horizontal(id="p2a-main"):
            with Vertical(id="p2a-col-playlists"):
                yield Static("Playlists", classes="p2a-col-title")
                yield Static("", classes="p2a-col-gap")
                yield ListView(id="playlist-list")
            with Vertical(id="p2a-col-actions"):
                yield Static("Actions", classes="p2a-col-title")
                yield Static("", classes="p2a-col-gap")
                yield ListView(
                    ListItem(Label(r"  \[d] Extract+delete")),
                    ListItem(Label(r"  \[v] Extract+keep")),
                    ListItem(Label(r"  \[n] Keep")),
                    id="p2a-actions",
                )
            with Vertical(id="p2a-col-detail"):
                yield Static("Details", classes="p2a-col-title")
                yield Static("", classes="p2a-col-gap")
                yield Static("Loading…", id="detail", markup=True)
        yield Static("Loading library…", id="p2a-status")

    def on_mount(self) -> None:
        self._status_line = TransientStatus(self.query_one("#p2a-status", Static))
        self._status_line.set_baseline("Loading library…")
        self.run_worker(self._load_data(), group="p2a-load")

    # ── Column navigation ─────────────────────────────────────────

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

    # ── Events ────────────────────────────────────────────────────

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id == "playlist-list" and event.item is not None:
            self._refresh_detail_from_list()
            event.stop()
        elif event.list_view.id == "p2a-actions":
            idx = event.list_view.index
            if idx is not None and 0 <= idx < len(_P2A_ACTION_TOOLTIPS):
                self._status_line.flash(_P2A_ACTION_TOOLTIPS[idx])
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

    # ── Selection helpers ─────────────────────────────────────────

    def _current_row(self) -> P2AListItem | None:
        lv = self.query_one("#playlist-list", ListView)
        i = lv.index
        if i is None:
            return None
        children = list(lv.children)
        if i < 0 or i >= len(children):
            return None
        row = children[i]
        return row if isinstance(row, P2AListItem) else None

    def _highlight_indices(self, row: P2AListItem | None) -> set[int] | None:
        if row is None:
            return None
        _, result = self._results[row.p2a_playlist_idx]
        if row.p2a_album_idx is None:
            return set(range(len(result.album_groups)))
        return {row.p2a_album_idx}

    def _refresh_detail_from_list(self) -> None:
        row = self._current_row()
        if row is None:
            return
        pl, result = self._results[row.p2a_playlist_idx]
        self._render_detail(pl, result, self._highlight_indices(row))

    def _render_detail(
        self,
        pl,
        result,
        highlight_idx: set[int] | None,
    ) -> None:
        lines: list[str] = []
        lines.append(f"[bold]'{pl.name}'[/] ({pl.track_count} tracks)\n")
        lines.append("[underline]Albums found:[/]")
        for i, ag in enumerate(result.album_groups):
            hl = highlight_idx is not None and i in highlight_idx
            if ag.is_complete:
                status = "[green]complete[/]"
            else:
                status = f"{ag.match_ratio:.0%}"
            pct = f"({ag.present_count}/{ag.album_total_tracks})"
            in_lib = " [dim]\\[in your library][/]" if ag.in_library else ""
            artist = (
                f" [italic]by {ag.album_artists}[/]" if ag.album_artists else ""
            )
            title_line = f"  {i + 1}. [bold]{ag.album_name}[/]{artist}"
            if hl:
                title_line = f"[on $surface]{title_line}[/]"
            lines.append(title_line)
            lines.append(f"     {status} {pct}{in_lib}")
            if ag.missing_tracks:
                lines.append(
                    f"     [yellow]missing: {', '.join(ag.missing_tracks)}[/]"
                )
        if result.loose_track_count:
            lines.append(
                f"\n  + [yellow]{result.loose_track_count}[/] loose tracks "
                "(not part of a detected album above)"
            )
        self.query_one("#detail", Static).update("\n".join(lines))

    # ── Data loading ──────────────────────────────────────────────

    async def _load_data(self) -> None:
        from common.store import load_library
        from spotify.album_detect import analyse_playlist

        library = await asyncio.to_thread(load_library, "spotify")

        lv = self.query_one("#playlist-list", ListView)
        lv.clear()

        if not library.playlists:
            self.query_one("#detail", Static).update(
                "[yellow]No playlists. Run 'spotify pull' first.[/]"
            )
            self._update_status()
            return

        playlists = library.playlists
        if self._filter:
            needle = self._filter.lower()
            playlists = [p for p in playlists if needle in p.name.lower()]
            if not playlists:
                self.query_one("#detail", Static).update(
                    f"[yellow]No playlist matching '{self._filter}'.[/]"
                )
                self._update_status()
                return

        saved_ids = {
            sa.album.service_id
            for sa in library.saved_albums
            if sa.album.service_id
        }

        self._results = []
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

        for pi, (pl, result) in enumerate(self._results):
            lv.append(
                P2AListItem(
                    Label(pl.name),
                    playlist_idx=pi,
                    album_idx=None,
                )
            )
            if len(result.album_groups) > 1:
                for ai, ag in enumerate(result.album_groups):
                    lv.append(
                        P2AListItem(
                            Label(f"  └ {ag.album_name}"),
                            playlist_idx=pi,
                            album_idx=ai,
                        )
                    )

        self._update_status()
        lv.index = 0
        self._refresh_detail_from_list()

    def _update_status(self) -> None:
        n = len(self._results)
        self._status_line.set_baseline(
            f"  {n} playlist(s) with album groups  ·  "
            r"\[d] remove from playlist  ·  \[v] keep in playlist  ·  \[n] leave unchanged"
        )

    # ── Actions ───────────────────────────────────────────────────

    def _selection_bundle(self):
        row = self._current_row()
        if not row or not self._results:
            return None
        pl, result = self._results[row.p2a_playlist_idx]
        if row.p2a_album_idx is None:
            groups = list(result.album_groups)
        else:
            groups = [result.album_groups[row.p2a_album_idx]]
        return pl, result, groups, row

    def action_keep(self) -> None:
        if not self._selection_bundle():
            return
        self._status_line.set_baseline(
            "  No changes — select another row or action."
        )

    def action_extract_keep(self) -> None:
        bundle = self._selection_bundle()
        if not bundle:
            return
        pl, result, groups, row = bundle
        names = ", ".join(g.album_name for g in groups)
        scope = (
            f"all {len(groups)} album(s) in this playlist"
            if row.p2a_album_idx is None
            else f"album “{groups[0].album_name}”"
        )
        body = (
            f"[bold]Extract+keep[/]\n\n"
            f"Playlist: [bold]{pl.name}[/]\n"
            f"Scope: {scope}\n\n"
            f"Albums: {names}\n\n"
            "Saved album entries will be added from local data. "
            "Tracks stay in the playlist (duplicate: library + playlist).\n\n"
            "Confirm?"
        )
        self.app.push_screen(ConfirmModal(body), lambda ok: self._on_extract_keep(ok, pl, groups))

    def _on_extract_keep(self, ok: bool, pl, groups) -> None:
        if not ok:
            return
        self.run_worker(self._do_extract_keep(pl, groups), group="p2a-apply")

    async def _do_extract_keep(self, pl, groups) -> None:
        from data.playlist2album import apply_extract_once

        try:
            r = await asyncio.to_thread(
                apply_extract_once,
                pl,
                groups,
                remove_from_playlist=False,
                keep_remaining_in_playlist_file=True,
                service="spotify",
            )
            self._status_line.set_baseline(
                f"  Added {r.albums_added} album(s) to saved library (playlist unchanged)."
            )
        except Exception as exc:
            self._status_line.set_baseline(f"  Error: {exc}")
            return
        await self._load_data()

    def action_extract_delete(self) -> None:
        bundle = self._selection_bundle()
        if not bundle:
            return
        pl, result, groups, row = bundle
        names = ", ".join(g.album_name for g in groups)
        scope = (
            f"all {len(groups)} album(s)"
            if row.p2a_album_idx is None
            else f"“{groups[0].album_name}”"
        )

        def do_confirm(ok: bool) -> None:
            if not ok:
                return
            if result.loose_track_count > 0:
                if p2a_always_keep_leftovers():
                    self._run_extract_delete(pl, groups, True)
                else:
                    body = (
                        f"This playlist has [bold]{result.loose_track_count}[/] loose "
                        "track(s) not tied to the album(s) you are extracting.\n\n"
                        "After removing the album tracks, do you want to keep a playlist "
                        "file with what is left, or delete the playlist file entirely?"
                    )
                    self.app.push_screen(
                        LeftoversModal(body),
                        lambda keep_file: self._run_extract_delete(
                            pl, groups, keep_file
                        ),
                    )
            else:
                self._run_extract_delete(pl, groups, True)

        body = (
            f"[bold]Extract+delete[/]\n\n"
            f"Playlist: [bold]{pl.name}[/]\n"
            f"Scope: {scope}\n\n"
            f"Albums: {names}\n\n"
            "[bold yellow]Those tracks will be removed from this playlist file[/] "
            "after saving album(s) to your local saved library.\n\n"
            "Confirm?"
        )
        self.app.push_screen(ConfirmModal(body), do_confirm)

    def _run_extract_delete(
        self,
        pl,
        groups: list,
        keep_remaining_in_playlist_file: bool,
    ) -> None:
        self.run_worker(
            self._do_extract_delete(pl, groups, keep_remaining_in_playlist_file),
            group="p2a-apply",
        )

    async def _do_extract_delete(
        self,
        pl,
        groups: list,
        keep_remaining_in_playlist_file: bool,
    ) -> None:
        from data.playlist2album import apply_extract_once

        try:
            r = await asyncio.to_thread(
                apply_extract_once,
                pl,
                groups,
                remove_from_playlist=True,
                keep_remaining_in_playlist_file=keep_remaining_in_playlist_file,
                service="spotify",
            )
            msg = f"  {r.detail.get('playlist_outcome', 'done')}"
            if r.albums_added:
                msg = f"  Added {r.albums_added} album(s). " + msg
            self._status_line.set_baseline(msg)
        except Exception as exc:
            self._status_line.set_baseline(f"  Error: {exc}")
            return
        await self._load_data()
