"""music-service-migrator – unified CLI entry point.

Usage:
    python cli.py                             (launches full TUI)
    python cli.py spotify pull
    python cli.py spotify push                (future)
    python cli.py data dedupe
    python cli.py data playlist2album [-p NAME]
    python cli.py data playlistimages
    python cli.py tidal pull                  (future)
    python cli.py tidal push                  (future)
"""

from __future__ import annotations

import sys

import click


def _launch(initial: str = "svc-spotify", **kwargs) -> None:
    from tui.main_app import MigratorApp

    MigratorApp(initial=initial, **kwargs).run()


def _handle_spotify_errors(func):
    """Decorator that catches SpotifyAuthError and exits cleanly."""
    import functools

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            from spotify.client import SpotifyAuthError

            if isinstance(exc, SpotifyAuthError):
                click.secho(f"Error: {exc}", fg="red", err=True)
                sys.exit(1)
            raise

    return wrapper


@click.group(invoke_without_command=True)
@click.pass_context
def main(ctx) -> None:
    """Music service migrator & playlist management toolkit."""
    if ctx.invoked_subcommand is None:
        _launch()


# ── Spotify sub-commands ─────────────────────────────────────────────────────


@main.group()
def spotify() -> None:
    """Spotify ↔ API commands (pull / push)."""


@spotify.command()
@_handle_spotify_errors
def pull() -> None:
    """Pull your entire Spotify library and save to disk."""
    _launch("svc-spotify")


@spotify.command()
@_handle_spotify_errors
def push() -> None:
    """Push local changes back to Spotify."""
    _launch("svc-spotify")


# ── Data sub-commands (operate on stored data) ───────────────────────────────


@main.group()
def data() -> None:
    """Analyse & transform locally stored library data."""


@data.command()
def dedupe() -> None:
    """Find duplicate tracks within and across playlists."""
    _launch("data-dedupe")


@data.command()
@click.option(
    "--playlist",
    "-p",
    default=None,
    help="Name (or substring) of a single playlist to analyse.",
)
def playlist2album(playlist: str | None) -> None:
    """Detect albums embedded in playlists and optionally extract them."""
    _launch("data-p2a", playlist_filter=playlist)


@data.command()
def playlistimages() -> None:
    """Download playlist artwork at the highest available resolution."""
    _launch("data-images")


# ── Tidal sub-commands (future) ──────────────────────────────────────────────


@main.group()
def tidal() -> None:
    """Tidal ↔ API commands (pull / push)."""


@tidal.command()
def pull() -> None:
    """Pull your entire Tidal library and save to disk."""
    _launch("svc-tidal")


@tidal.command()
def push() -> None:
    """Push local library to Tidal."""
    _launch("svc-tidal")


if __name__ == "__main__":
    main()
