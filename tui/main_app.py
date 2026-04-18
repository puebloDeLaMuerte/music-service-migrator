"""Unified TUI application — single app with sidebar navigation."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Footer, Label, ListItem, ListView, Static

from tui.app import APP_THEME, APP_TITLE, AppBanner
from tui.views import MENU, create_view
from tui.views.base import BaseView


# ── Sidebar ──────────────────────────────────────────────────────────────────


class NavItem(ListItem):
    """A sidebar item — section header, navigable link, or spacer."""

    def __init__(self, label: str, view_id: str = "") -> None:
        self.view_id = view_id
        is_spacer = view_id == "---"
        is_header = (not view_id) and (not is_spacer)

        if is_spacer:
            super().__init__(
                Label(""),
                classes="nav-spacer",
                disabled=True,
            )
        elif is_header:
            super().__init__(
                Label(f"[bold dim]─ {label} ─[/]", markup=True),
                classes="nav-header",
                disabled=True,
            )
        else:
            super().__init__(
                Label(f"  {label}", markup=True),
                classes="nav-item",
            )


class NavSidebar(Container):
    """Left sidebar with grouped navigation menu."""

    DEFAULT_CSS = """
    NavSidebar {
        width: 24;
        border-right: solid $primary-background-lighten-2;
    }
    NavSidebar > Vertical {
        height: 1fr;
    }
    #nav-col-title {
        padding: 0 1;
        height: 1;
        text-style: bold;
        color: $text;
        background: $surface;
    }
    #nav-col-gap {
        height: 1;
        background: $surface;
    }
    #nav-list { height: 1fr; }
    .nav-header { color: $text-muted; height: 1; }
    .nav-header:hover { background: transparent; }
    .nav-spacer { height: 1; }
    .nav-spacer:hover { background: transparent; }
    .nav-item.active { background: $accent 20%; }
    .nav-item.active Label { text-style: bold; }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Menu", id="nav-col-title")
            yield Static("", id="nav-col-gap")
            items = [NavItem(label, view_id) for label, view_id in MENU]
            yield ListView(*items, id="nav-list")

    def highlight_active(self, view_id: str) -> None:
        nav_list = self.query_one("#nav-list", ListView)
        for i, item in enumerate(nav_list.children):
            if isinstance(item, NavItem):
                if item.view_id == view_id:
                    item.add_class("active")
                    nav_list.index = i
                else:
                    item.remove_class("active")


# ── Main app ─────────────────────────────────────────────────────────────────


class MigratorApp(App):
    theme = APP_THEME

    BINDINGS = [
        Binding("left", "zone_left", priority=True, show=False),
        Binding("right", "zone_right", priority=True, show=False),
        Binding("escape", "focus_nav", "Navigation", show=True),
        Binding("q", "quit", "Quit"),
    ]

    CSS = """
    #body { height: 1fr; }
    #content { width: 1fr; height: 100%; }
    """

    def __init__(self, initial: str = "svc-spotify", **view_kwargs) -> None:
        super().__init__()
        self._initial = initial
        self._initial_kwargs = view_kwargs
        self._active_view: BaseView | None = None
        self._active_view_id: str = ""

    def compose(self) -> ComposeResult:
        yield AppBanner()
        with Horizontal(id="body"):
            yield NavSidebar()
            yield Container(id="content")
        yield Footer()

    def on_mount(self) -> None:
        self.title = APP_TITLE
        self.run_worker(
            self._do_switch_view(self._initial, **self._initial_kwargs),
            group="view-switch",
        )

    # ── View switching ──────────────────────────────────────────────

    async def _do_switch_view(self, view_id: str, **kwargs) -> None:
        content = self.query_one("#content")
        if self._active_view is not None:
            await self._active_view.remove()
        self._active_view = create_view(view_id, **kwargs)
        self._active_view_id = view_id
        await content.mount(self._active_view)
        self.query_one(NavSidebar).highlight_active(view_id)
        self.call_after_refresh(self._focus_content)

    # ── Event handlers ──────────────────────────────────────────────

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "nav-list":
            self._activate_nav_item(event.item)

    def _activate_nav_item(self, item: ListItem | None) -> None:
        """Switch to the view for this row (if any), then focus content when unchanged."""
        if not isinstance(item, NavItem):
            return
        vid = item.view_id
        if not vid or vid == "---":
            return
        if vid == "quit":
            self.exit()
            return
        if vid != self._active_view_id:
            self.run_worker(
                self._do_switch_view(vid),
                group="view-switch",
                exclusive=True,
            )
        else:
            self.call_after_refresh(self._focus_content)

    # ── Zone navigation (priority bindings) ─────────────────────────

    def action_zone_left(self) -> None:
        if self._in_sidebar():
            return
        view = self._active_view
        if view and hasattr(view, "zone_left"):
            view.zone_left()
        else:
            self._focus_sidebar()

    def action_zone_right(self) -> None:
        if self._in_sidebar():
            nav = self.query_one("#nav-list", ListView)
            idx = nav.index
            if idx is not None:
                children = list(nav.children)
                if 0 <= idx < len(children):
                    item = children[idx]
                    if (
                        isinstance(item, NavItem)
                        and item.view_id
                        and item.view_id != "---"
                    ):
                        self._activate_nav_item(item)
                        return
            self._focus_content()
            return
        view = self._active_view
        if view and hasattr(view, "zone_right"):
            view.zone_right()

    def action_focus_nav(self) -> None:
        """Escape always returns focus to the sidebar."""
        self._focus_sidebar()

    # ── Focus helpers ───────────────────────────────────────────────

    def _in_sidebar(self) -> bool:
        node = self.focused
        while node is not None and node is not self:
            if isinstance(node, NavSidebar):
                return True
            node = node.parent
        return False

    def _focus_sidebar(self) -> None:
        try:
            self.query_one("#nav-list", ListView).focus()
        except Exception:
            pass

    def _focus_content(self) -> None:
        if self._active_view is None:
            return
        for widget in self._active_view.query("*"):
            if widget.can_focus:
                widget.focus()
                return
