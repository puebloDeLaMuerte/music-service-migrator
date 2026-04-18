"""Settings — edit .env-backed options (column: names | values)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Input, Label, ListItem, ListView, Static, Switch

from common.config import get, p2a_always_keep_leftovers, write_env_key
from tui.transient_status import TransientStatus
from tui.views.base import BaseView


@dataclass(frozen=True)
class _Setting:
    env_key: str
    label: str
    kind: Literal["bool", "float", "string"]
    help: str


SETTINGS: tuple[_Setting, ...] = (
    _Setting(
        "TUI_STATUS_FLASH_SECONDS",
        "Status flash (seconds)",
        "float",
        "How long transient status lines stay visible (tooltips, short notices).",
    ),
    _Setting(
        "P2A_ALWAYS_KEEP_LEFTOVERS",
        "P2A: always keep leftovers",
        "bool",
        "After Extract+delete, skip the dialog when loose tracks remain; "
        "always keep the trimmed playlist file.",
    ),
    _Setting(
        "OUTPUT_DIR",
        "Output directory",
        "string",
        "Folder for exported library data (relative paths are under the project).",
    ),
    _Setting(
        "LOG_LEVEL",
        "Log level",
        "string",
        "Python logging level (e.g. INFO, DEBUG, WARNING).",
    ),
)


class SettingsView(BaseView):
    DEFAULT_CSS = """
    SettingsView { height: 1fr; width: 1fr; }
    #settings-main { height: 1fr; }
    #settings-main > Vertical { height: 1fr; }
    .settings-col-title {
        padding: 0 1;
        height: 1;
        text-style: bold;
        color: $text;
        background: $surface;
    }
    .settings-col-gap {
        height: 1;
        background: $surface;
    }
    #settings-col-options {
        width: 1fr;
        min-width: 28;
        border-right: solid $primary-background-lighten-2;
    }
    #settings-col-options #settings-list { height: 1fr; }
    #settings-col-value { width: 1fr; min-width: 32; }
    #settings-value-body {
        height: 1fr;
        padding: 0 1;
        overflow-y: auto;
        background: $background;
    }
    #settings-blurb {
        padding-bottom: 1;
        color: $text-muted;
    }
    #settings-bool-switch { display: none; }
    SettingsView.show-bool #settings-text-input { display: none; }
    SettingsView.show-bool #settings-bool-switch { display: block; }
    #settings-text-input { width: 100%; }
    #settings-status {
        dock: bottom;
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="settings-main"):
            with Vertical(id="settings-col-options"):
                yield Static("Setting", classes="settings-col-title")
                yield Static("", classes="settings-col-gap")
                yield ListView(
                    *[ListItem(Label(f"  {s.label}")) for s in SETTINGS],
                    id="settings-list",
                )
            with Vertical(id="settings-col-value"):
                yield Static("Value", classes="settings-col-title")
                yield Static("", classes="settings-col-gap")
                with Vertical(id="settings-value-body"):
                    yield Static("", id="settings-blurb", markup=True)
                    yield Input(placeholder="Edit and press Enter", id="settings-text-input")
                    yield Switch(id="settings-bool-switch", value=False)
        yield Static("", id="settings-status")

    def on_mount(self) -> None:
        self._suppress_switch = False
        self._status_line = TransientStatus(self.query_one("#settings-status", Static))
        self._status_line.set_baseline(
            "  ↑↓ choose a setting  ·  → to edit  ·  Enter saves the text field"
        )
        lv = self.query_one("#settings-list", ListView)
        lv.index = 0
        self._sync_panel(0)

    def _read_bool(self, row: _Setting) -> bool:
        if row.env_key == "P2A_ALWAYS_KEEP_LEFTOVERS":
            return p2a_always_keep_leftovers()
        return False

    def _read_text_value(self, row: _Setting) -> str:
        key = row.env_key
        if key == "TUI_STATUS_FLASH_SECONDS":
            return get(key, "5") or "5"
        if key == "OUTPUT_DIR":
            return get(key, "./output") or "./output"
        if key == "LOG_LEVEL":
            return get(key, "INFO") or "INFO"
        return get(key, "") or ""

    def _sync_panel(self, index: int) -> None:
        if index < 0 or index >= len(SETTINGS):
            return
        row = SETTINGS[index]
        self.query_one("#settings-blurb", Static).update(row.help)
        self.remove_class("show-text", "show-bool")
        if row.kind == "bool":
            self.add_class("show-bool")
            sw = self.query_one("#settings-bool-switch", Switch)
            self._suppress_switch = True
            sw.value = self._read_bool(row)
            self._suppress_switch = False
        else:
            self.add_class("show-text")
            self.query_one("#settings-text-input", Input).value = self._read_text_value(
                row
            )

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id != "settings-list" or event.list_view.index is None:
            return
        self._sync_panel(event.list_view.index)
        event.stop()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "settings-text-input":
            return
        lv = self.query_one("#settings-list", ListView)
        idx = lv.index
        if idx is None:
            return
        row = SETTINGS[idx]
        if row.kind == "bool":
            return
        text = event.value.strip()
        err = self._validate(row, text)
        if err:
            self._status_line.flash(f"  [yellow]{err}[/]")
            return
        write_env_key(row.env_key, self._serialize(row, text))
        self._status_line.flash("  [yellow]Saved to .env[/]")

    def _validate(self, row: _Setting, text: str) -> str | None:
        if row.kind == "float":
            try:
                v = float(text.replace(",", "."))
            except ValueError:
                return "Enter a number."
            if v < 0:
                return "Must be ≥ 0."
        if row.kind == "string" and row.env_key == "LOG_LEVEL":
            if not text:
                return "Log level cannot be empty."
        return None

    def _serialize(self, row: _Setting, text: str) -> str:
        if row.kind == "float":
            v = float(text.replace(",", "."))
            return str(int(v)) if v == int(v) else str(v)
        return text

    def _save_bool(self, row: _Setting, value: bool) -> None:
        write_env_key(row.env_key, "1" if value else "0")
        self._status_line.flash("  [yellow]Saved to .env[/]")

    def on_switch_changed(self, event: Switch.Changed) -> None:
        if event.switch.id != "settings-bool-switch" or self._suppress_switch:
            return
        lv = self.query_one("#settings-list", ListView)
        idx = lv.index
        if idx is None:
            return
        row = SETTINGS[idx]
        if row.kind != "bool":
            return
        self._save_bool(row, event.value)

    # ── Column navigation (MigratorApp) ───────────────────────────

    def zone_left(self) -> None:
        fid = getattr(self.app.focused, "id", None)
        if fid in ("settings-text-input", "settings-bool-switch"):
            self.query_one("#settings-list", ListView).focus()
        else:
            self.app._focus_sidebar()

    def zone_right(self) -> None:
        fid = getattr(self.app.focused, "id", None)
        if fid == "settings-list":
            idx = self.query_one("#settings-list", ListView).index
            if idx is None:
                return
            if SETTINGS[idx].kind == "bool":
                self.query_one("#settings-bool-switch", Switch).focus()
            else:
                self.query_one("#settings-text-input", Input).focus()
