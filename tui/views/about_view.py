"""About view — short project blurb."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Static

from tui.views.base import BaseView

_ABOUT_TEXT = (
    "[bold]About[/]\n\n"
    "Spotify sucks. Tidal probably sucks too, but i hear less so.\n\n"
    "I took the migration as an opportunity to clean up my collection a bit, "
    "thought others might want such a tool too - after all this way we "
    "don't have to give our access tokens to some other company...."
    "\n\n"
    "Philipp Tögel, 2026"
    "https://github.com/puebloDeLaMuerte/music-service-migrator"
)


class AboutView(BaseView):
    DEFAULT_CSS = """
    AboutView { height: 1fr; width: 1fr; }
    #about-body {
        width: 1fr;
        height: 1fr;
        padding: 1 2;
        overflow-y: auto;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(_ABOUT_TEXT, id="about-body", markup=True)
