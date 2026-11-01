"""Line charts for buoy and tide gauge traces, drawn on the same dot grid as the map.

A chart is a Canvas, so it comes out as the same rows of (text, style) runs and works in all three modes. Several series
share one set of axes. The caller chooses what x means (hours before now, for a buoy) and, when the default numbers are
not what it wants on the axis, passes its own tick labels such as -24h, -12h and now.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from eyewall.palette import CHART_AXIS, CHART_GRID, CHART_TEXT
from eyewall.render.canvas import Canvas, Mode, Priority

Point = tuple[float, float | None]  # (x, y); a y of None is a gap in the trace


@dataclass(frozen=True)
class ChartSeries:
    name: str
    points: tuple[Point, ...]
    color: str


@dataclass(frozen=True)
class Tick:
    value: float
    label: str


@dataclass(frozen=True)
class ChartStyle:
    axis: str = CHART_AXIS
    grid: str = CHART_GRID
    text: str = CHART_TEXT


DEFAULT_STYLE = ChartStyle()
_GRID_SPACING = 4  # dots between the dots of a grid line


def nice_step(span: float, target: int) -> float:
    """A step of 1, 2 or 5 times a power of ten that divides span into roughly target intervals."""
    raw = span / max(1, target)
    magnitude = 10.0 ** math.floor(math.log10(raw))
    for factor in (1.0, 2.0, 5.0, 10.0):
        if raw <= factor * magnitude * (1.0 + 1e-9):
            return factor * magnitude
    return 10.0 * magnitude


def format_values(values: Sequence[float], step: float) -> list[str]:
    """Labels for evenly spaced tick values, with just enough decimals for the step."""
    decimals = max(0, -math.floor(math.log10(step) + 1e-9))
    labels = []
    for value in values:
        text = f"{value:.{decimals}f}"
        labels.append("0" if text.startswith("-") and float(text) == 0.0 else text)
    return labels


def nice_ticks(lo: float, hi: float, target: int = 5, *, cover: bool = False) -> tuple[list[float], float]:
    """Tick values between lo and hi and the step between them. With cover, the first and last tick lie at or beyond
    lo and hi, so an axis that spans the ticks shows all the data."""
    if not hi > lo:
        lo, hi = lo - 0.5, hi + 0.5
    step = nice_step(hi - lo, target)
    first = math.floor(lo / step + 1e-9) if cover else math.ceil(lo / step - 1e-9)
    last = math.ceil(hi / step - 1e-9) if cover else math.floor(hi / step + 1e-9)
    return [round(k * step, 10) for k in range(first, last + 1)], step


def _valid(value: float | None) -> bool:
    return value is not None and math.isfinite(value)


def _rows(rows: int, title: str | None, series: Sequence[ChartSeries]) -> tuple[int, int]:
    legend_rows = 1 if rows >= 6 and (title or any(s.name for s in series)) else 0
    return legend_rows, max(1, rows - legend_rows - 2)


def _y_axis(
    series: Sequence[ChartSeries],
    plot_rows: int,
    y_range: tuple[float, float] | None,
    y_ticks: Sequence[Tick] | None,
) -> tuple[Sequence[Tick], float, float]:
    ys = [y for s in series for _, y in s.points if y is not None and math.isfinite(y)]
    if y_ticks is None:
        data_lo, data_hi = y_range if y_range else ((min(ys), max(ys)) if ys else (0.0, 1.0))
        values, step = nice_ticks(data_lo, data_hi, max(2, plot_rows // 3), cover=y_range is None)
        y_ticks = [Tick(v, label) for v, label in zip(values, format_values(values, step), strict=True)]
        y_lo, y_hi = (values[0], values[-1]) if y_range is None and len(values) > 1 else (data_lo, data_hi)
    else:
        y_lo, y_hi = y_range if y_range else ((min(ys), max(ys)) if ys else (0.0, 1.0))
    if not y_hi > y_lo:
        y_lo, y_hi = y_lo - 0.5, y_hi + 0.5
    return y_ticks, y_lo, y_hi


def _gutter(y_ticks: Sequence[Tick]) -> int:
    return max((len(t.label) for t in y_ticks), default=0)


def gutter_width(
    series: Sequence[ChartSeries],
    rows: int,
    *,
    title: str | None = None,
    y_range: tuple[float, float] | None = None,
    y_ticks: Sequence[Tick] | None = None,
) -> int:
    """The y label gutter `render_chart` would use for these series at this height."""
    _, plot_rows = _rows(rows, title, series)
    return _gutter(_y_axis(series, plot_rows, y_range, y_ticks)[0])


def render_chart(
    series: Sequence[ChartSeries],
    cols: int,
    rows: int,
    *,
    mode: Mode = Mode.BRAILLE,
    x_range: tuple[float, float] | None = None,
    y_range: tuple[float, float] | None = None,
    x_ticks: Sequence[Tick] | None = None,
    y_ticks: Sequence[Tick] | None = None,
    title: str | None = None,
    grid: bool = True,
    style: ChartStyle = DEFAULT_STYLE,
    min_gutter: int = 0,
) -> Canvas:
    """Draw series on shared axes. The layout, top to bottom: a legend row (when there is a title or a named series),
    the plot, an axis line and a row of x labels; y labels sit in a gutter to the left.

    x_range and y_range default to the data; the default y axis is stretched to its outer ticks. Rows of data with a
    None or NaN y break the line there. `min_gutter` widens the y label gutter so charts stacked together share one
    plot edge (see `gutter_width`). A canvas too small to hold the plot just comes out with the plot clipped."""
    canvas = Canvas(cols, rows, mode)
    glyphs = canvas.glyphs
    xs = [x for s in series for x, y in s.points if _valid(y) and math.isfinite(x)]
    x_lo, x_hi = x_range if x_range else ((min(xs), max(xs)) if xs else (0.0, 1.0))
    if not x_hi > x_lo:
        x_lo, x_hi = x_lo - 0.5, x_hi + 0.5
    legend_rows, plot_rows = _rows(rows, title, series)
    y_ticks, y_lo, y_hi = _y_axis(series, plot_rows, y_range, y_ticks)
    gutter = max(min_gutter, _gutter(y_ticks))
    plot_cols = max(1, cols - gutter - 1)
    px0, py0 = (gutter + 1) * canvas.dots_x, legend_rows * canvas.dots_y
    pw, ph = plot_cols * canvas.dots_x, plot_rows * canvas.dots_y

    def x_dot(x: float) -> float:
        return px0 + (x - x_lo) / (x_hi - x_lo) * (pw - 1) + 0.5

    def y_dot(y: float) -> float:
        return py0 + (y_hi - y) / (y_hi - y_lo) * (ph - 1) + 0.5

    if x_ticks is None:
        values, step = nice_ticks(x_lo, x_hi, max(2, plot_cols // 12))
        x_ticks = [Tick(v, label) for v, label in zip(values, format_values(values, step), strict=True)]
    axis_row = legend_rows + plot_rows

    # Grid lines first, so data and axes draw over them.
    if grid:
        with canvas.clipped(px0, py0, px0 + pw, py0 + ph):
            for tick in y_ticks:
                if y_lo <= tick.value <= y_hi:
                    row = math.floor(y_dot(tick.value))
                    for dot in range(px0, px0 + pw, _GRID_SPACING):
                        canvas.plot(dot, row, style.grid, Priority.LAND)
            for tick in x_ticks:
                if x_lo <= tick.value <= x_hi:
                    column = math.floor(x_dot(tick.value))
                    for dot in range(py0, py0 + ph, _GRID_SPACING):
                        canvas.plot(column, dot, style.grid, Priority.LAND)

    # Data.
    with canvas.clipped(px0, py0, px0 + pw, py0 + ph):
        for index, s in enumerate(series):
            prio = Priority.TRACK + index
            run: list[tuple[float, float]] = []
            for x, y in [*s.points, (0.0, None)]:  # the sentinel flushes the last run
                if y is not None and math.isfinite(y) and math.isfinite(x):
                    run.append((x_dot(x), y_dot(y)))
                else:
                    if run:
                        canvas.polyline(run, s.color, prio)
                    run = []

    # Axes and labels.
    y_axis = {math.floor(y_dot(t.value) - py0) // canvas.dots_y: t for t in y_ticks if y_lo <= t.value <= y_hi}
    for r in range(plot_rows):
        tick_here = y_axis.get(r)
        canvas.text(gutter, legend_rows + r, glyphs.tick_y if tick_here else glyphs.axis_v, style.axis, Priority.MARKER)
        if tick_here:
            canvas.text(gutter - len(tick_here.label), legend_rows + r, tick_here.label, style.text, Priority.LABEL)
    canvas.text(gutter, axis_row, glyphs.corner, style.axis, Priority.MARKER)
    canvas.text(gutter + 1, axis_row, glyphs.axis_h * plot_cols, style.axis, Priority.MARKER)
    next_free = 0
    for tick in sorted(x_ticks, key=lambda t: t.value):
        if not x_lo <= tick.value <= x_hi:
            continue
        col = math.floor(x_dot(tick.value)) // canvas.dots_x
        canvas.text(col, axis_row, glyphs.tick_x, style.axis, Priority.MARKER)
        start = min(max(col - len(tick.label) // 2, next_free), max(0, cols - len(tick.label)))
        if start >= next_free:
            canvas.text(start, axis_row + 1, tick.label, style.text, Priority.LABEL)
            next_free = start + len(tick.label) + 1

    if legend_rows:
        col = 0
        if title:
            canvas.text(0, 0, title, style.text, Priority.LABEL, bold=True)
            col = len(title) + 2
        for s in series:
            if s.name:
                canvas.text(col, 0, glyphs.legend, s.color, Priority.LABEL)
                canvas.text(col + 2, 0, s.name, style.text, Priority.LABEL)
                col += len(s.name) + 4
    return canvas
