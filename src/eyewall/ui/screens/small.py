"""Shown instead of the layout while the terminal is smaller than the app can use."""

from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Static

MIN_SIZE = (60, 16)


def too_small(width: int, height: int) -> bool:
    return width < MIN_SIZE[0] or height < MIN_SIZE[1]


class TooSmallScreen(Screen[None]):
    def compose(self) -> ComposeResult:
        yield Static("Needs at least {}x{}   (q quit)".format(*MIN_SIZE), id="too-small")

    def on_resize(self, event: events.Resize) -> None:
        if self.is_current and not too_small(*event.size):
            self.dismiss()
