"""TUI screen for 'data playlistimages'."""

from __future__ import annotations

import asyncio

from textual.widgets import RichLog

from tui.app import LogScreen


class ImagesApp(LogScreen):
    def __init__(self) -> None:
        super().__init__(title="playlist images")

    async def run_task(self, log_widget: RichLog) -> None:
        from common.store import load_library
        from data.images import download_all_artwork

        log_widget.write("[bold]Loading stored Spotify library…[/]")
        library = await asyncio.to_thread(load_library, "spotify")

        if not library.playlists:
            log_widget.write("[red]No playlists found. Run 'spotify pull' first.[/]")
            return

        log_widget.write(
            f"Downloading artwork for [bold]{len(library.playlists)}[/] playlists…\n"
        )
        downloaded, skipped = await asyncio.to_thread(download_all_artwork, library)
        log_widget.write("")
        log_widget.write(
            f"[bold green]{downloaded}[/] downloaded, "
            f"[yellow]{skipped}[/] skipped (no artwork)."
        )
        log_widget.write("\n[dim]Press [bold]q[/bold] to quit.[/]")
