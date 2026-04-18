"""Temporary status-line text on a Static widget, then restore baseline."""

from __future__ import annotations

from typing import TYPE_CHECKING

from common.config import tui_status_flash_seconds

if TYPE_CHECKING:
    from textual.timer import Timer
    from textual.widgets import Static


class TransientStatus:
    """Flash a message on a docked ``Static`` status line, then show baseline again.

    Use :meth:`set_baseline` for the normal hint or state (shown at once when
    nothing is flashing, and used as the restore target after :meth:`flash`).
    Use :meth:`flash` for short-lived notices; duration defaults to
    :func:`common.config.tui_status_flash_seconds` unless overridden per call.
    """

    def __init__(
        self,
        widget: Static,
        *,
        default_seconds: float | None = None,
    ) -> None:
        self._widget = widget
        self._default_seconds = (
            tui_status_flash_seconds()
            if default_seconds is None
            else max(0.0, default_seconds)
        )
        self._baseline = ""
        self._timer: Timer | None = None

    def set_baseline(self, text: str) -> None:
        """Normal status text. Updates the widget immediately if no flash is running."""
        self._baseline = text
        if self._timer is None:
            self._widget.update(text)

    def flash(self, text: str, *, seconds: float | None = None) -> None:
        """Show ``text`` briefly, then restore the current baseline."""
        self._cancel_timer()
        self._widget.update(text)
        delay = self._default_seconds if seconds is None else max(0.0, seconds)
        if delay <= 0:
            self._restore()
            return
        self._timer = self._widget.set_timer(
            delay, self._restore, name="transient-status"
        )

    def _restore(self) -> None:
        self._timer = None
        self._widget.update(self._baseline)

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
