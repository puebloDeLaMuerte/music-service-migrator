"""Modal: browse tracks in a playlist from local workspace JSON (no API calls)."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Static

from common.models import Playlist, PlaylistTrack


def _fmt_artists(pt: PlaylistTrack) -> str:
    return ", ".join(a.name for a in pt.track.artists) if pt.track.artists else ""


def _fmt_duration(ms: int | None) -> str:
    if ms is None or ms < 0:
        return ""
    sec = ms // 1000
    m, s = divmod(sec, 60)
    if m >= 60:
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _album_cell(pt: PlaylistTrack) -> str:
    a = pt.track.album
    return a.name if a else ""


class PlaylistTracksModal(ModalScreen[None]):
    """Show tracks for one playlist loaded from disk; optional filter by album service_id."""

    BINDINGS = [
        Binding("escape", "close_modal", "Close", show=False),
    ]

    CSS = """
    PlaylistTracksModal { align: center middle; }
    #pt-modal-box {
        width: 90%;
        max-width: 100;
        height: 85%;
        border: thick $accent;
        background: $surface;
        padding: 0 1 1 1;
    }
    #pt-modal-title {
        padding: 1 1 0 1;
        height: auto;
    }
    #pt-modal-table { height: 1fr; }
    #pt-modal-footer {
        dock: bottom;
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    """

    def __init__(
        self,
        playlist: Playlist,
        *,
        album_service_id: str | None = None,
        filter_heading: str | None = None,
    ) -> None:
        super().__init__()
        self._playlist = playlist
        self._album_service_id = album_service_id
        self._filter_heading = filter_heading

    def compose(self) -> ComposeResult:
        with Vertical(id="pt-modal-box"):
            yield Static(self._title_text(), id="pt-modal-title", markup=True)
            yield DataTable(id="pt-modal-table", zebra_stripes=True)
            yield Static(
                r"[dim]ESC = close[/]",
                id="pt-modal-footer",
                markup=True,
            )

    def _title_text(self) -> str:
        name = self._playlist.name
        if self._album_service_id and self._filter_heading:
            n = self._filtered_count()
            return (
                f"[bold]{name}[/] — [italic]{self._filter_heading}[/] "
                f"({n} track{'s' if n != 1 else ''} in playlist file)"
            )
        n = self._playlist.track_count
        return f"[bold]{name}[/] — {n} track{'s' if n != 1 else ''} (local export)"

    def _filtered_count(self) -> int:
        aid = self._album_service_id
        if not aid:
            return self._playlist.track_count
        return sum(
            1
            for pt in self._playlist.tracks
            if pt.track.album and pt.track.album.service_id == aid
        )

    def on_mount(self) -> None:
        table = self.query_one("#pt-modal-table", DataTable)
        table.cursor_type = "row"
        table.add_column("#", width=4)
        table.add_column("Track")
        table.add_column("Artists")
        table.add_column("Album")
        table.add_column("Time", width=8)

        rows = self._table_rows()
        if not rows:
            msg = (
                "No tracks for this album in the local playlist file."
                if self._album_service_id
                else "No tracks in local playlist file. Run a catalog pull first."
            )
            table.add_row("—", msg, "", "", "")
            return

        for row in rows:
            table.add_row(*row)
        table.focus()

    def _table_rows(self) -> list[tuple[str, str, str, str, str]]:
        out: list[tuple[str, str, str, str, str]] = []
        n = 0
        for pt in self._playlist.tracks:
            if self._album_service_id:
                al = pt.track.album
                sid = al.service_id if al else None
                if sid != self._album_service_id:
                    continue
            n += 1
            t = pt.track
            idx = str(pt.position) if pt.position is not None else str(n)
            out.append(
                (
                    idx,
                    t.name,
                    _fmt_artists(pt),
                    _album_cell(pt),
                    _fmt_duration(t.duration_ms),
                )
            )
        return out

    def action_close_modal(self) -> None:
        self.dismiss(None)
