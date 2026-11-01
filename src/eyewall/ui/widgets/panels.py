"""The side panels: thin widgets that show text built in `eyewall.ui.format`."""

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


def has_text(text: Text) -> bool:
    """True when a panel's text shows something: an empty or blank text leaves the panel nothing to say."""
    return bool(text.plain.strip())


class Panel(VerticalScroll):
    """One side panel, scrollable when its text outgrows it. The dashboard keeps two sets (stacked and tabbed) and fills
    both from the same text."""

    def __init__(self, kind: str, title: str) -> None:
        super().__init__(classes=f"panel {kind}")
        self.kind = kind
        self.border_title = title
        self.body = Static("")
        self.filled = True  # has text to show
        self.dropped = False  # the stacked column has no room for it (`DashboardScreen.fit_stack`)

    def compose(self) -> ComposeResult:
        yield self.body

    def update(self, text: Text) -> None:
        text = text.copy()
        text.rstrip()  # the builders end every line with a newline; the last one would show as a blank row
        self.body.update(text)
        if self.kind != "headline":  # no text, no panel: an empty box says nothing
            self.filled = has_text(text)
            self.display = self.filled and not self.dropped
