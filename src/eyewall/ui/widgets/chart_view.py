"""A line chart as a widget: M3's `render_chart` painted line by line, redrawn when the data or size changes."""

from __future__ import annotations

from collections.abc import Sequence

from rich.segment import Segment
from rich.style import Style as RichStyle
from textual import events
from textual.strip import Strip
from textual.widget import Widget

from eyewall.render.canvas import Mode
from eyewall.render.chart import ChartSeries, Tick, render_chart
from eyewall.ui.theme import DIM
from eyewall.ui.widgets.strips import blank, canvas_strips


class ChartView(Widget):
    """One chart on shared axes. `set_chart` replaces everything it draws; an empty chart says so in `empty`."""

    DEFAULT_CSS = "ChartView { height: 1fr; min-height: 5; }"

    def __init__(self, *, mode: Mode = Mode.BRAILLE, id: str | None = None) -> None:
        super().__init__(id=id)
        self.mode = mode
        self._series: tuple[ChartSeries, ...] = ()
        self._title = ""
        self._x_range: tuple[float, float] = (-24.0, 0.0)
        self._x_ticks: tuple[Tick, ...] = ()
        self._empty = "No data"
        self._strips: list[Strip] | None = None

    def set_chart(
        self,
        series: Sequence[ChartSeries],
        *,
        title: str,
        x_range: tuple[float, float],
        x_ticks: Sequence[Tick],
        empty: str,
    ) -> None:
        self._series = tuple(series)
        self._title = title
        self._x_range = x_range
        self._x_ticks = tuple(x_ticks)
        self._empty = empty
        self._strips = None
        self.refresh()

    def _has_data(self) -> bool:
        return any(y is not None for s in self._series for _, y in s.points)

    def _build(self) -> list[Strip]:
        width, height = self.size.width, self.size.height
        if width < 1 or height < 1:
            return []
        if not self._has_data():
            empty = blank(width)
            message = f" {self._title}: {self._empty}"[:width]
            line = Strip([Segment(message, RichStyle(color=DIM))], width)
            return [line] + [empty] * (height - 1)
        canvas = render_chart(
            self._series,
            width,
            height,
            mode=self.mode,
            x_range=self._x_range,
            x_ticks=self._x_ticks,
            title=self._title,
        )
        return canvas_strips(canvas, width)

    def render_line(self, y: int) -> Strip:
        if self._strips is None:
            self._strips = self._build()
        if 0 <= y < len(self._strips):
            return self._strips[y]
        return blank(self.size.width)

    def on_resize(self, event: events.Resize) -> None:
        self._strips = None
