"""Download playlist artwork at the highest available resolution."""

from __future__ import annotations

from pathlib import Path
from urllib.request import Request, urlopen

from common import config
from common.log import get_logger
from common.models import Image, Library, Playlist
from common.store import sanitise_filename

log = get_logger(__name__)

_USER_AGENT = "music-service-migrator/0.1"

_SCDN_SIZE_PREFIXES = {
    "ab67616d00004851": 64,
    "ab67616d00001e02": 300,
    "ab67616d0000b273": 640,
}
_SCDN_BEST_PREFIX = "ab67616d0000b273"


def _upgrade_scdn_url(url: str) -> str:
    """If the URL is a Spotify CDN image, swap the size prefix for 640px."""
    for prefix in _SCDN_SIZE_PREFIXES:
        if prefix in url:
            return url.replace(prefix, _SCDN_BEST_PREFIX)
    return url


def _best_image(images: list[Image]) -> Image | None:
    """Pick the largest image by pixel area (or first if sizes unknown)."""
    if not images:
        return None
    candidates = [i for i in images if i.width and i.height]
    if candidates:
        return max(candidates, key=lambda i: (i.width or 0) * (i.height or 0))
    return images[0]


def _guess_extension(url: str, content_type: str | None) -> str:
    if content_type:
        ct = content_type.lower()
        if "png" in ct:
            return ".png"
        if "webp" in ct:
            return ".webp"
        if "gif" in ct:
            return ".gif"
    lower = url.lower().split("?")[0]
    for ext in (".png", ".webp", ".gif"):
        if lower.endswith(ext):
            return ext
    return ".jpg"


def _download(url: str, dest: Path) -> Path:
    """Download a URL to a local file, returning the final path."""
    url = _upgrade_scdn_url(url)
    req = Request(url, headers={"User-Agent": _USER_AGENT})
    with urlopen(req) as resp:
        ext = _guess_extension(url, resp.headers.get("Content-Type"))
        final = dest.with_suffix(ext)
        final.parent.mkdir(parents=True, exist_ok=True)
        final.write_bytes(resp.read())
    return final


def download_playlist_artwork(
    playlist: Playlist,
    workspace_root: Path | None = None,
) -> Path | None:
    """Download the best artwork for a single playlist.

    Saves to: ``<work_dir>/playlists/<name>_data/artwork.<ext>``
    Returns the path on success, None if no image available.
    """
    img = _best_image(playlist.images)
    if img is None:
        return None

    if workspace_root is None:
        workspace_root = config.work_dir()

    folder = workspace_root / "playlists" / (sanitise_filename(playlist.name) + "_data")
    dest = folder / "artwork"
    final = _download(img.url, dest)
    log.info("Saved artwork for '%s' → %s", playlist.name, final)
    return final


def download_all_artwork(library: Library) -> tuple[int, int]:
    """Download artwork for every playlist in the library.

    Returns (downloaded, skipped) counts.
    """
    workspace_root = config.work_dir()
    downloaded = 0
    skipped = 0

    for pl in library.playlists:
        result = download_playlist_artwork(pl, workspace_root=workspace_root)
        if result:
            downloaded += 1
        else:
            log.warning("No artwork for '%s'", pl.name)
            skipped += 1

    return downloaded, skipped
