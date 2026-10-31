"""The side panels and the status bar: thin widgets that show text built in `eyewall.ui.format`."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

PANEL_KINDS: tuple[tuple[str, str, str], ...] = (
    # (kind, title, short tab name)
    ("headline", "Headline", "Now"),
    ("ww", "Watches and warnings", "Warn"),
    ("wind", "Wind", "Wind"),
    ("surge", "Storm surge", "Surge"),
    ("buoys", "Nearest buoys", "Buoys"),
)


class Panel(VerticalScroll):
    """One side panel, scrollable when its text outgrows it. The dashboard keeps two sets (stacked and tabbed) and fills
    both from the same text."""

    def __init__(self, kind: str, title: str) -> None:
        super().__init__(classes=f"panel {kind}")
        self.kind = kind
        self.border_title = title
        self.body = Static("")

    def compose(self) -> ComposeResult:
        yield self.body

    def update(self, text: Text) -> None:
        text = text.copy()
        text.rstrip()  # the builders end every line with a newline; the last one would show as a blank row
        self.body.update(text)
        if self.kind == "surge":  # no surge text, no panel: an empty box says nothing
            self.display = bool(text)


class StatusBar(Static):
    """The bottom line: feed freshness, next poll, alert count and the replay transport."""

    def show(self, text: Text) -> None:
        self.update(text)
