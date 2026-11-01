"""Strips for the widgets that paint their own lines.

Textual's no-colour filter reads the style of every segment, so a segment with no style crashes the app when
`NO_COLOR` is set. Every strip these widgets return is built here, and none carries a missing style.
"""

from __future__ import annotations

from rich.segment import Segment
from rich.style import Style as RichStyle
from textual.strip import Strip

from eyewall.render.canvas import Canvas
from eyewall.render.canvas import Style as CanvasStyle

PLAIN = RichStyle()


def blank(width: int) -> Strip:
    return Strip.blank(width, PLAIN)


def centered(line: Strip, width: int) -> Strip:
    pad = max(0, (width - line.cell_length) // 2)
    return Strip([Segment(" " * pad, PLAIN), *line]).adjust_cell_length(width, PLAIN)


def canvas_strips(canvas: Canvas, width: int) -> list[Strip]:
    strips = []
    for runs in canvas.rows_as_runs():
        segments = [Segment(text, rich_style(s)) for text, s in runs]
        strips.append(Strip(segments, width))
    return strips


def rich_style(style: CanvasStyle) -> RichStyle:
    """A canvas style as a rich one. Bold, underline and reverse survive `NO_COLOR`, so they carry cues color cannot."""
    return RichStyle(
        color=style.fg,
        bgcolor=style.bg,
        bold=style.bold or None,
        underline=style.underline or None,
        reverse=style.reverse or None,
    )


def reverse_cell(strip: Strip, col: int) -> Strip:
    """The strip with one cell in reverse video: the focus ring on a mark. Reverse survives `NO_COLOR`."""
    before, cell, after = strip.divide([col, col + 1, strip.cell_length])
    return Strip(
        [*before, *(Segment(seg.text, (seg.style or PLAIN) + RichStyle(reverse=True)) for seg in cell), *after]
    )
