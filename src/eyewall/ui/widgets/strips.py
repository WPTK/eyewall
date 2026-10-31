"""Strips for the widgets that paint their own lines.

Textual's no-colour filter reads the style of every segment, so a segment with no style crashes the app when
`NO_COLOR` is set. Every strip these widgets return is built here, and none carries a missing style.
"""

from __future__ import annotations

from rich.segment import Segment
from rich.style import Style as RichStyle
from textual.strip import Strip

from eyewall.render.canvas import Canvas

PLAIN = RichStyle()


def blank(width: int) -> Strip:
    return Strip.blank(width, PLAIN)


def centered(line: Strip, width: int) -> Strip:
    pad = max(0, (width - line.cell_length) // 2)
    return Strip([Segment(" " * pad, PLAIN), *line]).adjust_cell_length(width, PLAIN)


def canvas_strips(canvas: Canvas, width: int) -> list[Strip]:
    strips = []
    for runs in canvas.rows_as_runs():
        segments = [Segment(text, RichStyle(color=s.fg, bgcolor=s.bg, bold=s.bold or None)) for text, s in runs]
        strips.append(Strip(segments, width))
    return strips
