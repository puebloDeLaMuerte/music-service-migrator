"""Blinking left-edge marker on the service status line while work runs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from common.config import tui_activity_blink_ms

if TYPE_CHECKING:
    from textual.timer import Timer
    from textual.widgets import Static


class RunningStatus:
    """``█░`` / ``░█`` prefix toggling on a ``Static`` status widget."""

    def __init__(self, widget: Static) -> None:
        self._widget = widget
        self._timer: Timer | None = None
        self._phase = 0
        self._message = ""

    def start(self, message: str) -> None:
        self.stop()
        self._message = message
        self._phase = 0
        self._paint()
        interval = tui_activity_blink_ms() / 1000.0
        self._timer = self._widget.set_interval(interval, self._tick, name="running-status")

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def _tick(self) -> None:
        self._phase ^= 1
        self._paint()

    def _paint(self) -> None:
        mark = "█░" if self._phase == 0 else "░█"
        self._widget.update(f"  {mark} {self._message}")
