"""A page of wrapped text whose lines can be links: the body of the Storm and Station screens.

The builder is given the width and returns whole lines (already wrapped on word boundaries by `side_panel.wrapped`), so
a line is never cut and a click on a row maps to a line. A line with an action runs it on the screen: `do:buoys`
calls the screen's `action_buoys`.
"""

from __future__ import annotations

from collections.abc import Callable

from rich.text import Text
from textual import events
from textual.widgets import Static

from eyewall.ui.widgets.side_panel import DO, Line


class Page(Static):
    def __init__(self, *, id: str | None = None) -> None:
        super().__init__("", id=id)
        self._build: Callable[[int], list[Line]] | None = None
        self._lines: list[Line] = []

    @property
    def lines(self) -> list[Line]:
        return self._lines

    def set_builder(self, build: Callable[[int], list[Line]]) -> None:
        self._build = build
        self.repaint()

    def on_resize(self) -> None:
        self.repaint()

    def text_width(self) -> int:
        return max(self.size.width - self.styles.gutter.width, 0)

    def repaint(self) -> None:
        width = self.text_width()
        if self._build is None or width < 1:
            return
        self._lines = self._build(width)
        self.update(Text("\n").join(line.text for line in self._lines))

    def on_click(self, event: events.Click) -> None:
        index = event.y - self.styles.gutter.top
        action = self._lines[index].action if 0 <= index < len(self._lines) else None
        if action is None:
            return
        kind, _, rest = action.partition(":")
        if kind == DO:
            event.stop()
            self.app.call_later(self.screen.run_action, rest)


__all__ = ["Page"]
