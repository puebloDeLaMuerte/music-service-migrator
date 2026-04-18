"""TUI screen for 'spotify pull'."""

from __future__ import annotations

import asyncio

from textual.widgets import RichLog

from tui.app import LogScreen


class PullApp(LogScreen):
    def __init__(self) -> None:
        super().__init__(title="spotify pull")

    async def run_task(self, log_widget: RichLog) -> None:
        log_widget.write("[bold]Pulling full library from Spotify…[/]\n")

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
        log_widget.write("\n[dim]Press [bold]q[/bold] to quit.[/]")
