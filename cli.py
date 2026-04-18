"""music-service-migrator – unified CLI entry point.

Usage:
    python cli.py spotify pull
    python cli.py spotify push              (future)
    python cli.py data dedupe
    python cli.py data playlist2album
    python cli.py data playlistimages
    python cli.py tidal pull                (future)
    python cli.py tidal push                (future)
"""

from __future__ import annotations

import sys

import click

from common.log import get_logger

log = get_logger(__name__)


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


@click.group()
def main() -> None:
    """Music service migrator & playlist management toolkit."""


# ── Spotify sub-commands ─────────────────────────────────────────────────────


@main.group()
def spotify() -> None:
    """Spotify ↔ API commands (pull / push)."""


@spotify.command()
@_handle_spotify_errors
def pull() -> None:
    """Pull your entire Spotify library and save to disk."""
    from common.store import save_library
    from spotify.export import fetch_library

    click.echo("Pulling full library from Spotify…")
    library = fetch_library()

    click.echo(
        f"  {len(library.playlists)} playlists, "
        f"{len(library.liked_songs)} liked songs, "
        f"{len(library.saved_albums)} saved albums, "
        f"{len(library.followed_artists)} followed artists"
    )

    out = save_library(library)
    click.echo(f"Library saved to {out}")


@spotify.command()
@_handle_spotify_errors
def push() -> None:
    """Push local changes back to Spotify."""
    click.echo("Not yet implemented.")


# ── Data sub-commands (operate on stored data) ───────────────────────────────


@main.group()
def data() -> None:
    """Analyse & transform locally stored library data."""


@data.command()
def dedupe() -> None:
    """Find duplicate tracks within and across playlists."""
    from common.store import load_library
    from spotify.dedupe import find_duplicates_across

    click.echo("Loading stored Spotify library…")
    library = load_library("spotify")

    if not library.playlists:
        click.echo("No playlists found. Run 'spotify pull' first.")
        return

    dupes = find_duplicates_across(library.playlists)
    if not dupes:
        click.echo("No cross-playlist duplicates found.")
        return

    click.echo(f"Found {len(dupes)} duplicate track(s) across playlists:\n")
    for d in dupes:
        locations = ", ".join(f"{name} #{pos}" for name, pos in d.occurrences)
        click.echo(f"  {d.track_name} – {d.artists}")
        click.echo(f"    in: {locations}\n")


@data.command()
def playlist2album() -> None:
    """Detect albums embedded in playlists."""
    from common.store import load_library
    from spotify.album_detect import analyse_playlist

    click.echo("Loading stored Spotify library…")
    library = load_library("spotify")

    if not library.playlists:
        click.echo("No playlists found. Run 'spotify pull' first.")
        return

    saved_album_ids = {
        sa.album.service_id
        for sa in library.saved_albums
        if sa.album.service_id
    }

    for pl in library.playlists:
        result = analyse_playlist(pl, saved_album_ids=saved_album_ids)
        if not result.album_groups:
            continue

        click.echo(f"\n  '{pl.name}' ({pl.track_count} tracks):")
        for ag in result.album_groups:
            status = "complete" if ag.is_complete else f"{ag.match_ratio:.0%}"
            in_library = " [in your library]" if ag.in_library else ""
            click.echo(f"    • {ag.album_name} – {status}{in_library}")
            if ag.missing_tracks:
                names = ", ".join(ag.missing_tracks)
                click.echo(f"      missing: {names}")
        if result.loose_track_count:
            click.echo(f"    + {result.loose_track_count} tracks not part of any detected album")


@data.command()
def playlistimages() -> None:
    """Download playlist artwork at the highest available resolution."""
    from common.store import load_library
    from data.images import download_all_artwork

    click.echo("Loading stored Spotify library…")
    library = load_library("spotify")

    if not library.playlists:
        click.echo("No playlists found. Run 'spotify pull' first.")
        return

    click.echo(f"Downloading artwork for {len(library.playlists)} playlists…")
    downloaded, skipped = download_all_artwork(library)
    click.echo(f"Done: {downloaded} downloaded, {skipped} skipped (no artwork).")


# ── Tidal sub-commands (future) ──────────────────────────────────────────────


@main.group()
def tidal() -> None:
    """Tidal ↔ API commands (pull / push)."""


@tidal.command()
def pull() -> None:
    """Pull your entire Tidal library and save to disk."""
    click.echo("Not yet implemented – Tidal adapter coming soon.")


@tidal.command()
def push() -> None:
    """Push local library to Tidal."""
    click.echo("Not yet implemented – Tidal adapter coming soon.")


if __name__ == "__main__":
    main()
