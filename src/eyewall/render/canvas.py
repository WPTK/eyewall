"""A grid of terminal cells drawn with braille dots, half blocks or plain ASCII.

Each cell is a 2 by 4 braille dot block (or 1 by 2 dots in the half-block and ASCII modes). Drawing methods take dot
coordinates, where dot (i, j) covers [i, i+1) by [j, j+1) with the origin at the top-left, and give each stroke a color
and a priority. A cell holds one color: the one from the highest-priority stroke that touched it, so a track drawn over
a coastline recolors the cell while the coastline's dots stay visible. Text labels and glyph markers replace a cell's
dots.

The result comes out as rows of (text, Style) runs, which a Textual widget turns into a Strip. Nothing here imports
Textual.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import NamedTuple

Dot = tuple[float, float]


class Mode(StrEnum):
    BRAILLE = "braille"  # 2 by 4 dots per cell
    HALF = "half"  # 1 by 2 dots per cell, drawn with half blocks, for fonts with poor braille
    ASCII = "ascii"  # 1 by 2 dots per cell, drawn with ' . : for the legacy Windows console

    @property
    def dots_x(self) -> int:
        return 2 if self is Mode.BRAILLE else 1

    @property
    def dots_y(self) -> int:
        return 4 if self is Mode.BRAILLE else 2


class Priority(IntEnum):
    """Layer priorities. A higher one wins the cell's color: track over warning over cone over coast."""

    LAND = 10
    BORDER = 15
    COAST = 20
    OUTLOOK = 30
    CONE = 40
    SURGE = 50
    WARNING = 60
    RADII = 65
    TRACK = 70
    FORECAST = 75
    STATION = 80
    MARKER = 90
    LABEL = 95
    CURSOR = 100


class Shade(StrEnum):
    """Dot patterns for filled areas, fixed to the dot grid so neighbouring fills line up."""

    SOLID = "solid"
    DENSE = "dense"  # 3 dots in 4
    HALF = "half"  # a checkerboard
    SPARSE = "sparse"  # 1 dot in 4
    LIGHT = "light"  # 1 dot in 8, spread evenly
    HATCH_LIGHT = "hatch-light"  # diagonal lines, 8 dots apart
    HATCH_MEDIUM = "hatch-medium"  # diagonal lines, 4 dots apart
    HATCH_HEAVY = "hatch-heavy"  # diagonal lines, 2 dots apart


def _pattern(test: Callable[[int, int], bool]) -> tuple[tuple[bool, ...], ...]:
    return tuple(tuple(bool(test(x, y)) for x in range(8)) for y in range(8))


# Every pattern repeats every 8 dots in both directions, so a fill is a table lookup per dot.
_PATTERNS: dict[Shade, tuple[tuple[bool, ...], ...]] = {
    Shade.SOLID: _pattern(lambda x, y: True),
    Shade.DENSE: _pattern(lambda x, y: (x + y) % 4 != 0),
    Shade.HALF: _pattern(lambda x, y: (x + y) % 2 == 0),
    Shade.SPARSE: _pattern(lambda x, y: (x + y) % 4 == 0),
    Shade.LIGHT: _pattern(lambda x, y: y % 2 == 0 and (x + y) % 4 == 0),
    Shade.HATCH_LIGHT: _pattern(lambda x, y: (x - y) % 8 == 0),
    Shade.HATCH_MEDIUM: _pattern(lambda x, y: (x - y) % 4 == 0),
    Shade.HATCH_HEAVY: _pattern(lambda x, y: (x - y) % 2 == 0),
}


class Style(NamedTuple):
    """How a run of text is drawn. Colors are hex strings from the palette; None is the terminal default."""

    fg: str | None = None
    bg: str | None = None
    bold: bool = False
    underline: bool = False
    reverse: bool = False


Run = tuple[str, Style]


@dataclass(frozen=True)
class Glyphs:
    """The single-width characters used for markers and chart furniture."""

    center: str
    forecast: str
    buoy: str
    tide: str
    cursor: str
    legend: str
    axis_v: str
    axis_h: str
    corner: str
    tick_x: str
    tick_y: str


UNICODE_GLYPHS = Glyphs("◉", "◆", "●", "▲", "┼", "■", "│", "─", "└", "┬", "┤")
ASCII_GLYPHS = Glyphs("@", "*", "o", "^", "+", "#", "|", "-", "+", "+", "+")

# Index is dy * dots_x + dx. Braille dots are numbered down the left column (1, 2, 3, 7) then the right (4, 5, 6, 8).
_BRAILLE_BITS = (0x01, 0x08, 0x02, 0x10, 0x04, 0x20, 0x40, 0x80)
_BLOCK_BITS = (0x01, 0x02)
_BRAILLE_GLYPHS = tuple(" " if mask == 0 else chr(0x2800 + mask) for mask in range(256))
_HALF_GLYPHS = (" ", "▀", "▄", "█")
_ASCII_GLYPHS = (" ", "'", ".", ":")

_BLANK = Style()


class Canvas:
    """The drawing surface. Create one per frame, or copy() a cached base map and draw on top of it."""

    def __init__(self, cols: int, rows: int, mode: Mode = Mode.BRAILLE) -> None:
        if cols < 1 or rows < 1:
            raise ValueError("a canvas needs at least one cell")
        self.cols = cols
        self.rows = rows
        self.mode = mode
        self.dots_x = mode.dots_x
        self.dots_y = mode.dots_y
        self.width = cols * self.dots_x
        self.height = rows * self.dots_y
        count = cols * rows
        self._bits = [0] * count
        self._fg: list[str | None] = [None] * count
        self._prio = [-1] * count
        self._char: list[str | None] = [None] * count
        self._bold = [False] * count
        self._clip = (0, 0, self.width, self.height)
        self._bit_table = _BRAILLE_BITS if mode is Mode.BRAILLE else _BLOCK_BITS
        self._glyph_table = {Mode.BRAILLE: _BRAILLE_GLYPHS, Mode.HALF: _HALF_GLYPHS, Mode.ASCII: _ASCII_GLYPHS}[mode]

    # ------------------------------------------------------------------------------------------------ housekeeping

    @property
    def glyphs(self) -> Glyphs:
        return ASCII_GLYPHS if self.mode is Mode.ASCII else UNICODE_GLYPHS

    def copy(self) -> Canvas:
        other = Canvas.__new__(Canvas)
        other.__dict__.update(self.__dict__)
        other._bits = self._bits[:]
        other._fg = self._fg[:]
        other._prio = self._prio[:]
        other._char = self._char[:]
        other._bold = self._bold[:]
        return other

    @contextmanager
    def clipped(self, x0: int, y0: int, x1: int, y1: int) -> Iterator[None]:
        """Restrict dot drawing to [x0, x1) by [y0, y1) inside the block, within any clip already in force."""
        saved = self._clip
        self._clip = (max(saved[0], x0), max(saved[1], y0), min(saved[2], x1), min(saved[3], y1))
        try:
            yield
        finally:
            self._clip = saved

    # ------------------------------------------------------------------------------------------------------- dots

    def plot(self, x: int, y: int, color: str | None, prio: int = 0) -> None:
        """Set one dot. Dots outside the canvas or the clip are ignored."""
        x0, y0, x1, y1 = self._clip
        if x < x0 or x >= x1 or y < y0 or y >= y1:
            return
        i = (y // self.dots_y) * self.cols + x // self.dots_x
        self._bits[i] |= self._bit_table[(y % self.dots_y) * self.dots_x + x % self.dots_x]
        if prio >= self._prio[i]:
            self._fg[i] = color
            self._prio[i] = prio

    def dot(self, x: int, y: int) -> bool:
        """Whether a dot is set."""
        if x < 0 or y < 0 or x >= self.width or y >= self.height:
            return False
        bit = self._bit_table[(y % self.dots_y) * self.dots_x + x % self.dots_x]
        return bool(self._bits[(y // self.dots_y) * self.cols + x // self.dots_x] & bit)

    def line(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        color: str | None,
        prio: int = 0,
        *,
        dash: tuple[int, int] | None = None,
        width: int = 1,
    ) -> None:
        """A Bresenham line between two dot coordinates. dash is (dots on, dots off); width 2 doubles the stroke."""
        self._segment(x0, y0, x1, y1, color, prio, dash, 0.0, width)

    def polyline(
        self,
        points: Sequence[Dot],
        color: str | None,
        prio: int = 0,
        *,
        dash: tuple[int, int] | None = None,
        width: int = 1,
        closed: bool = False,
    ) -> None:
        """Connected lines. A dash pattern carries on unbroken from one segment to the next."""
        if not points:
            return
        if len(points) == 1:
            self.plot(math.floor(points[0][0]), math.floor(points[0][1]), color, prio)
            return
        run = 0.0
        pairs = itertools.pairwise(points)
        for (xa, ya), (xb, yb) in pairs:
            run += self._segment(xa, ya, xb, yb, color, prio, dash, run, width)
        if closed and len(points) > 2:
            self._segment(*points[-1], *points[0], color, prio, dash, run, width)

    def _segment(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        color: str | None,
        prio: int,
        dash: tuple[int, int] | None,
        run: float,
        width: int,
    ) -> float:
        """Draw one segment and return its length in dot steps, so dashes can continue along a polyline."""
        if not all(map(math.isfinite, (x0, y0, x1, y1))):
            return 0.0
        dx, dy = x1 - x0, y1 - y0
        length = max(abs(dx), abs(dy))
        cx0, cy0, cx1, cy1 = self._clip
        t0, t1 = 0.0, 1.0
        for p, q in ((-dx, x0 - cx0), (dx, cx1 - x0), (-dy, y0 - cy0), (dy, cy1 - y0)):
            if p == 0:
                if q < 0:
                    return length
                continue
            t = q / p
            if p < 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
            if t0 > t1:
                return length
        ax, ay = (x0, y0) if t0 == 0.0 else (x0 + t0 * dx, y0 + t0 * dy)
        bx, by = (x1, y1) if t1 == 1.0 else (x0 + t1 * dx, y0 + t1 * dy)
        self._bresenham(
            min(max(math.floor(ax), cx0), cx1 - 1),
            min(max(math.floor(ay), cy0), cy1 - 1),
            min(max(math.floor(bx), cx0), cx1 - 1),
            min(max(math.floor(by), cy0), cy1 - 1),
            color,
            prio,
            dash,
            run + t0 * length,
        )
        if width > 1:
            sx, sy = (1, 0) if abs(dy) > abs(dx) else (0, 1)
            self._bresenham(
                min(max(math.floor(ax) + sx, cx0), cx1 - 1),
                min(max(math.floor(ay) + sy, cy0), cy1 - 1),
                min(max(math.floor(bx) + sx, cx0), cx1 - 1),
                min(max(math.floor(by) + sy, cy0), cy1 - 1),
                color,
                prio,
                dash,
                run + t0 * length,
            )
        return length

    def _bresenham(
        self, x0: int, y0: int, x1: int, y1: int, color: str | None, prio: int, dash: tuple[int, int] | None, run: float
    ) -> None:
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx + dy
        x, y = x0, y0
        step = 0
        on, period = (dash[0], dash[0] + dash[1]) if dash else (1, 1)
        while True:
            if (run + step) % period < on:
                self.plot(x, y, color, prio)
            if x == x1 and y == y1:
                return
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x += sx
            if e2 <= dx:
                err += dx
                y += sy
            step += 1

    def arc(
        self,
        cx: float,
        cy: float,
        radius: float,
        start: float,
        end: float,
        color: str | None,
        prio: int = 0,
        *,
        dash: tuple[int, int] | None = None,
    ) -> None:
        """An arc around (cx, cy) from start to end degrees, measured clockwise from straight up like a compass
        bearing. An end below the start runs the other way round."""
        steps = max(2, min(4096, math.ceil(abs(end - start) / 360.0 * 2.0 * math.pi * max(radius, 1.0)) + 1))
        points = []
        for k in range(steps + 1):
            angle = math.radians(start + (end - start) * k / steps)
            # Rounded to a billionth of a dot, so trigonometry that differs in its last bit cannot change a pixel.
            points.append((round(cx + radius * math.sin(angle), 9), round(cy - radius * math.cos(angle), 9)))
        self.polyline(points, color, prio, dash=dash)

    def circle(
        self,
        cx: float,
        cy: float,
        radius: float,
        color: str | None,
        prio: int = 0,
        *,
        dash: tuple[int, int] | None = None,
    ) -> None:
        self.arc(cx, cy, radius, 0.0, 360.0, color, prio, dash=dash)

    def fill_polygon(
        self,
        rings: Iterable[Sequence[Dot]],
        color: str | None,
        prio: int = 0,
        shade: Shade = Shade.SOLID,
    ) -> None:
        """Scanline fill with the even-odd rule, so a ring inside another one is a hole. Each ring closes itself.
        A dot is filled when its center lies inside, and only the dots the shade pattern selects are set."""
        cx0, cy0, cx1, cy1 = self._clip
        if cx0 >= cx1 or cy0 >= cy1:
            return
        crossings: list[list[float]] = [[] for _ in range(cy1 - cy0)]
        for ring in rings:
            n = len(ring)
            if n < 3:
                continue
            for i in range(n):
                xa, ya = ring[i]
                xb, yb = ring[(i + 1) % n]
                if ya == yb or not all(map(math.isfinite, (xa, ya, xb, yb))):
                    continue
                if ya > yb:
                    xa, ya, xb, yb = xb, yb, xa, ya
                first = max(cy0, math.ceil(ya - 0.5))
                last = min(cy1, math.ceil(yb - 0.5))  # exclusive: a vertex is counted by only one of its two edges
                if first >= last:
                    continue
                slope = (xb - xa) / (yb - ya)
                for y in range(first, last):
                    crossings[y - cy0].append(xa + (y + 0.5 - ya) * slope)
        table = _PATTERNS[shade]
        dots_x, dots_y, cols = self.dots_x, self.dots_y, self.cols
        bit_table, bits, fg, prios = self._bit_table, self._bits, self._fg, self._prio
        for offset, xs in enumerate(crossings):
            if len(xs) < 2:
                continue
            y = cy0 + offset
            xs.sort()
            pattern = table[y & 7]
            base = (y // dots_y) * cols
            bit_row = (y % dots_y) * dots_x
            for k in range(0, len(xs) - 1, 2):
                for x in range(max(cx0, math.ceil(xs[k] - 0.5)), min(cx1, math.ceil(xs[k + 1] - 0.5))):
                    if pattern[x & 7]:
                        i = base + x // dots_x
                        bits[i] |= bit_table[bit_row + x % dots_x]
                        if prio >= prios[i]:
                            fg[i] = color
                            prios[i] = prio

    # ------------------------------------------------------------------------------------------------ text, markers

    def cell_of(self, x: float, y: float) -> tuple[int, int] | None:
        """The (column, row) of the cell holding a dot coordinate, or None when it is off the canvas."""
        if not (math.isfinite(x) and math.isfinite(y)):
            return None
        col, row = math.floor(x) // self.dots_x, math.floor(y) // self.dots_y
        return (col, row) if 0 <= col < self.cols and 0 <= row < self.rows else None

    def text_free(self, col: int, row: int, length: int) -> bool:
        """Whether a label of this length fits on the canvas without covering another label or marker."""
        if row < 0 or row >= self.rows or col < 0 or col + length > self.cols:
            return False
        start = row * self.cols + col
        return all(self._char[i] is None for i in range(start, start + length))

    def text(
        self, col: int, row: int, s: str, color: str | None, prio: int = Priority.LABEL, *, bold: bool = False
    ) -> None:
        """Write text over the cells starting at (col, row). Parts that fall off the canvas are dropped. Text never
        replaces text of a higher priority."""
        if self.mode is Mode.ASCII:
            s = s.encode("ascii", "replace").decode("ascii")
        if row < 0 or row >= self.rows:
            return
        for k, ch in enumerate(s):
            c = col + k
            if c < 0 or c >= self.cols:
                continue
            i = row * self.cols + c
            if self._char[i] is not None and self._prio[i] > prio:
                continue
            self._char[i] = ch
            self._fg[i] = color
            self._bold[i] = bold
            self._prio[i] = max(self._prio[i], int(prio))

    def marker(
        self, x: float, y: float, glyph: str, color: str | None, prio: int = Priority.MARKER, *, bold: bool = False
    ) -> tuple[int, int] | None:
        """Put a one-character glyph in the cell holding a dot coordinate. Returns that cell, or None if off canvas."""
        cell = self.cell_of(x, y)
        if cell is not None:
            self.text(cell[0], cell[1], glyph, color, prio, bold=bold)
        return cell

    # ----------------------------------------------------------------------------------------------------- output

    def cell(self, col: int, row: int) -> tuple[str, Style]:
        """The character and style a cell is drawn with."""
        i = row * self.cols + col
        ch = self._char[i]
        if ch is None:
            ch = self._glyph_table[self._bits[i]]
        return (ch, _BLANK if ch == " " else Style(self._fg[i], None, self._bold[i]))

    def rows_as_runs(self) -> list[list[Run]]:
        """Rows of (text, style) runs with neighbouring cells of one style merged."""
        out: list[list[Run]] = []
        for row in range(self.rows):
            runs: list[Run] = []
            pending: list[str] = []
            current = _BLANK
            for col in range(self.cols):
                ch, style = self.cell(col, row)
                if ch == " " and pending:
                    style = current  # a blank cell joins the run before it
                if pending and style != current:
                    runs.append(("".join(pending), current))
                    pending = []
                current = style
                pending.append(ch)
            runs.append(("".join(pending), current))
            out.append(runs)
        return out

    def lines(self) -> list[str]:
        """Plain text, one string per row, without colors."""
        return ["".join(self.cell(col, row)[0] for col in range(self.cols)) for row in range(self.rows)]

    def to_text(self) -> str:
        return "\n".join(self.lines())
