"""View registry for the unified TUI."""

from __future__ import annotations

# Sidebar menu definition.
#   ("Label", "")       → section header (disabled, bold)
#   ("Label", "view-id") → navigable entry
#   ("", "---")          → empty spacer line (disabled)

MENU: list[tuple[str, str]] = [
    ("Services", ""),
    ("Spotify", "svc-spotify"),
    ("Tidal", "svc-tidal"),
    ("", "---"),
    ("Local Data", ""),
    ("Dedupe", "data-dedupe"),
    ("Playlist→Album", "data-p2a"),
    ("Images", "data-images"),
    ("", "---"),
    ("About", "about"),
    ("Settings", "settings"),
    ("Quit", "quit"),
]


def create_view(view_id: str, **kwargs):
    """Instantiate a view widget by its menu ID."""
    from tui.views.about_view import AboutView
    from tui.views.dedupe_view import DedupeView
    from tui.views.settings_view import SettingsView
    from tui.views.images_view import ImagesView
    from tui.views.p2a_view import P2AView
    from tui.views.service_view import ServiceView
    from tui.views.stub_view import StubView

    if view_id == "svc-spotify":
        return ServiceView("spotify")
    if view_id == "svc-tidal":
        return ServiceView("tidal")
    if view_id == "data-dedupe":
        return DedupeView()
    if view_id == "data-p2a":
        return P2AView(playlist_filter=kwargs.get("playlist_filter"))
    if view_id == "data-images":
        return ImagesView()
    if view_id == "about":
        return AboutView()
    if view_id == "settings":
        return SettingsView()
    return StubView(view_id)
