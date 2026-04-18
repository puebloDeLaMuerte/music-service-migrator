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
from common.models import Playlist

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
@click.option(
    "--playlist", "-p", default=None,
    help="Name (or substring) of a single playlist to analyse.",
)
def playlist2album(playlist: str | None) -> None:
    """Detect albums embedded in playlists and optionally extract them."""
    from common.store import load_library
    from data.playlist2album import Action, apply_actions
    from spotify.album_detect import PlaylistAnalysis, analyse_playlist

    click.echo("Loading stored Spotify library…")
    library = load_library("spotify")

    if not library.playlists:
        click.echo("No playlists found. Run 'spotify pull' first.")
        return

    # Filter playlists if --playlist given
    if playlist:
        needle = playlist.lower()
        candidates = [p for p in library.playlists if needle in p.name.lower()]
        if not candidates:
            click.secho(f"No playlist matching '{playlist}' found.", fg="red")
            return
        playlists = candidates
    else:
        playlists = library.playlists

    saved_album_ids = {
        sa.album.service_id
        for sa in library.saved_albums
        if sa.album.service_id
    }

    # Phase 1: analyse and prompt per playlist
    results: list[tuple[Playlist, PlaylistAnalysis]] = []
    for pl in playlists:
        result = analyse_playlist(pl, saved_album_ids=saved_album_ids)
        if result.album_groups:
            results.append((pl, result))

    if not results:
        click.echo("No playlists with detected albums (>= 80% match).")
        return

    click.echo(f"\nFound albums in {len(results)} playlist(s).\n")

    actions: list[Action] = []
    for pl, result in results:
        _display_analysis(pl, result)
        choice = _prompt_action()

        if choice == "q":
            break
        if choice == "s":
            continue

        flag_missing = choice == "c"

        keep_leftovers = True
        if result.loose_track_count > 0:
            keep_leftovers = click.confirm(
                f"  Leftover {result.loose_track_count} tracks – keep as trimmed playlist?",
                default=True,
            )

        actions.append(Action(
            playlist=pl,
            analysis=result,
            album_groups=result.album_groups,
            keep_leftovers=keep_leftovers,
            flag_missing=flag_missing,
        ))

    if not actions:
        click.echo("\nNo actions queued.")
        return

    # Phase 2: dry-run summary
    click.echo("\n" + "─" * 60)
    click.echo("Dry-run summary:\n")
    for a in actions:
        album_names = ", ".join(ag.album_name for ag in a.album_groups)
        click.echo(f"  '{a.playlist_name}':")
        click.echo(f"    extract: {album_names}")
        if a.tracks_remaining > 0 and a.keep_leftovers:
            click.echo(f"    playlist: trim to {a.tracks_remaining} tracks")
        else:
            click.echo(f"    playlist: delete")
    click.echo(f"\n  Total: {sum(a.albums_to_extract for a in actions)} album(s) "
               f"from {len(actions)} playlist(s)")
    click.echo("─" * 60)

    if not click.confirm("\nApply these changes?", default=False):
        click.echo("Aborted – no changes made.")
        return

    summary = apply_actions(actions, "spotify")
    click.echo(
        f"\nDone: {summary['albums_added']} album(s) added, "
        f"{summary['playlists_modified']} playlist(s) trimmed, "
        f"{summary['playlists_deleted']} playlist(s) deleted."
    )


def _display_analysis(pl: Playlist, result) -> None:
    """Print the analysis findings for one playlist."""
    click.echo(f"  '{pl.name}' ({pl.track_count} tracks):")
    click.echo("  Albums found:")
    for i, ag in enumerate(result.album_groups, 1):
        status = "complete" if ag.is_complete else f"{ag.match_ratio:.0%}"
        pct = f"({ag.present_count}/{ag.album_total_tracks})"
        in_lib = " [in your library]" if ag.in_library else ""
        artist_str = f" by {ag.album_artists}" if ag.album_artists else ""
        click.echo(f"    {i}. {ag.album_name}{artist_str} – {status} {pct}{in_lib}")
        if ag.missing_tracks:
            click.echo(f"       missing: {', '.join(ag.missing_tracks)}")
    if result.loose_track_count:
        click.echo(f"  + {result.loose_track_count} loose tracks")
    click.echo()


def _prompt_action() -> str:
    """Prompt for per-playlist action. Returns 'e', 'c', 's', or 'q'."""
    while True:
        click.echo("  What to do?")
        click.echo("  [e] Extract album(s) to saved albums")
        click.echo("  [c] Complete & extract (flag missing tracks)")
        click.echo("  [s] Skip this playlist")
        click.echo("  [q] Skip all remaining playlists")
        choice = click.prompt("  ", prompt_suffix="> ", default="s", show_default=False).lower().strip()
        if choice in ("e", "c", "s", "q"):
            return choice
        click.echo("  Invalid choice, try again.\n")


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
