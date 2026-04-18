"""Images view — downloads playlist artwork."""

from __future__ import annotations

import asyncio

from textual.widgets import RichLog

from tui.views.base import LogView


class ImagesView(LogView):
    def on_mount(self) -> None:
        self._start_task()

    async def run_task(self, log_widget: RichLog) -> None:
        from common.store import load_workspace
        from data.images import download_all_artwork

        log_widget.write("[bold]Loading stored Spotify library…[/]")
        library = await asyncio.to_thread(load_workspace)

        if not library.playlists:
            log_widget.write(
                "[yellow]No playlists found. Run Spotify → Pull first.[/]"
            )
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
