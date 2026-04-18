"""music-service-migrator – unified CLI entry point.

Usage:
    python cli.py spotify export   [--split] [--liked-songs] [--html-report]
    python cli.py spotify dedupe
    python cli.py spotify detect-albums
    python cli.py migrate spotify-to-tidal          (future)
"""

from __future__ import annotations

import click

from common.log import get_logger

log = get_logger(__name__)


@click.group()
def main() -> None:
    """Music service migrator & playlist management toolkit."""


# ── Spotify sub-commands ─────────────────────────────────────────────────────


@main.group()
def spotify() -> None:
    """Spotify playlist tools."""


@spotify.command()
@click.option("--split", is_flag=True, help="One JSON file per playlist.")
@click.option("--liked-songs", is_flag=True, help="Include liked songs.")
@click.option("--html-report", is_flag=True, help="Generate an HTML report.")
@click.option("--playlist-name", default=None, help="Export only this playlist.")
def export(split: bool, liked_songs: bool, html_report: bool, playlist_name: str | None) -> None:
    """Export Spotify playlists to JSON."""
    from spotify.export import fetch_all_playlists, fetch_liked_songs

    click.echo("Fetching playlists from Spotify…")
    playlists = fetch_all_playlists()

    if playlist_name:
        playlists = [p for p in playlists if p.name == playlist_name]
        if not playlists:
            click.echo(f"No playlist found with name '{playlist_name}'")
            return

    click.echo(f"Fetched {len(playlists)} playlist(s)")

    if liked_songs:
        liked = fetch_liked_songs()
        click.echo(f"Fetched {len(liked)} liked song(s)")

    # TODO: write JSON output (split vs single), HTML report generation
    click.echo("Export complete. (JSON/HTML serialisation not yet wired up)")


@spotify.command()
def dedupe() -> None:
    """Find duplicate tracks within and across playlists."""
    from spotify.dedupe import find_duplicates_across
    from spotify.export import fetch_all_playlists

    click.echo("Fetching playlists…")
    playlists = fetch_all_playlists()

    dupes = find_duplicates_across(playlists)
    if not dupes:
        click.echo("No cross-playlist duplicates found.")
        return

    click.echo(f"Found {len(dupes)} duplicate track(s) across playlists:\n")
    for d in dupes:
        locations = ", ".join(f"{name} #{pos}" for name, pos in d.occurrences)
        click.echo(f"  {d.track_name} – {d.artists}")
        click.echo(f"    in: {locations}\n")


@spotify.command("detect-albums")
def detect_albums() -> None:
    """Flag playlists that are really just full albums."""
    from spotify.album_detect import check_playlist
    from spotify.export import fetch_all_playlists

    click.echo("Fetching playlists…")
    playlists = fetch_all_playlists()

    matches = []
    for pl in playlists:
        m = check_playlist(pl)
        if m:
            matches.append(m)

    if not matches:
        click.echo("No playlists look like standalone albums.")
        return

    click.echo(f"{len(matches)} playlist(s) appear to be albums:\n")
    for m in matches:
        click.echo(f"  '{m.playlist_name}' → album '{m.album_name}' ({m.match_ratio:.0%} match)")


# ── Migrate sub-commands (future) ────────────────────────────────────────────


@main.group()
def migrate() -> None:
    """Cross-service migration tools."""


@migrate.command("spotify-to-tidal")
def spotify_to_tidal() -> None:
    """Migrate playlists from Spotify to Tidal."""
    click.echo("Not yet implemented – Tidal adapter coming soon.")


if __name__ == "__main__":
    main()
