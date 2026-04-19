"""About view — short project blurb."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from tui.views.base import BaseView

_ABOUT_TEXT = (
    "Spotify sucks. Tidal probably sucks too, but i hear less so.\n\n"
    "I took the migration as an opportunity to clean up my collection a bit, "
    "thought others might want such a tool too..."
    "\n\n"
    "[dim]Built with[/] "
    '[link="https://github.com/Textualize/textual"]Textual[/], '
    '[link="https://github.com/pallets/click"]Click[/], '
    '[link="https://github.com/spotipy-dev/spotipy"]spotipy[/], '
    '[link="https://github.com/EbbLabs/python-tidal"]python-tidal[/] '
    '([link="https://pypi.org/project/tidalapi/"]tidalapi[/] on PyPI), '
    '[link="https://github.com/theskumar/python-dotenv"]python-dotenv[/].\n'
    "[dim]Reference / prior art[/] "
    '[link="https://github.com/novama/my-spotify-playlists-downloader"]my-spotify-playlists-downloader[/] '
    "(vendored under lib/ for Spotify setup docs).\n\n"
    "Philipp Tögel, 2026\n"
    "https://github.com/puebloDeLaMuerte/music-service-migrator"
)


class AboutView(BaseView):
    DEFAULT_CSS = """
    AboutView { height: 1fr; width: 1fr; }
    AboutView > Vertical { height: 1fr; }
    .about-col-title {
        padding: 0 1;
        height: 1;
        text-style: bold;
        color: $text;
        background: $background;
    }
    .about-col-gap {
        height: 1;
        background: $background;
    }
    #about-body {
        width: 1fr;
        height: 1fr;
        padding: 1 2;
        overflow-y: auto;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("About", classes="about-col-title")
            yield Static("", classes="about-col-gap")
            yield Static(_ABOUT_TEXT, id="about-body", markup=True)
