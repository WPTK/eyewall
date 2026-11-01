"""Place names and the scale bar: furniture that helps read the map, drawn after everything that carries meaning.

Places come from eyewall.mapdata (Natural Earth populated places, most important first). How many are labelled depends
on the zoom: a whole-basin view names only the great cities, a close view names towns. A label is dropped, never moved
far, when it would touch another label, a marker, or anything drawn at warning priority or above (watch and warning
lines, wind radii, the track, stations, storm markers). The rarer place always loses to the more important one because
places are tried in rank order. Pure rendering: no Textual.
"""

from __future__ import annotations

import math
import unicodedata

from eyewall.mapdata.loader import Place, load_places
from eyewall.render.canvas import Canvas, Mode, Priority
from eyewall.render.projection import Viewport
from eyewall.units import LABELS, convert

# (deg per dot at or above, highest scalerank labelled): coarse views name only the largest places.
RANK_BY_ZOOM: tuple[tuple[float, int], ...] = ((0.5, 2), (0.3, 4), (0.1, 6))
FINEST_RANK = 8
CELLS_PER_LABEL = 150  # at most one place label per this many map cells
KEEP_CLEAR = Priority.WARNING  # place labels and the scale bar stay off cells drawn at this priority or higher
NM_PER_DEGREE = 60.0
SCALE_UNITS = ("nm", "mi", "km")
SCALE_MIN_CELLS = 4
SCALE_MAX_CELLS = 20
_NICE = (1, 2, 5)


def max_rank(deg_per_dot: float) -> int:
    """The highest scalerank labelled at this zoom."""
    for floor, rank in RANK_BY_ZOOM:
        if deg_per_dot >= floor:
            return rank
    return FINEST_RANK


def label_limit(cols: int, rows: int) -> int:
    """How many place labels a map of this size may carry."""
    return max(1, cols * rows // CELLS_PER_LABEL)


def _name(place: Place, mode: Mode) -> str:
    """The name to print: the ASCII form in ASCII mode and where the name has wide characters."""
    if mode is Mode.ASCII or any(unicodedata.east_asian_width(ch) in "WF" for ch in place.name):
        return place.name_ascii
    return place.name


def _clear(canvas: Canvas, col: int, row: int, length: int) -> bool:
    """Whether a label fits at (col, row) with a blank cell on each side, where the canvas has one."""
    if col < 0 or col + length > canvas.cols:
        return False
    lo, hi = max(0, col - 1), min(canvas.cols, col + length + 1)
    return canvas.text_free(lo, row, hi - lo, below=KEEP_CLEAR)


def draw_places(
    canvas: Canvas,
    view: Viewport,
    color: str | None,
    places: tuple[Place, ...] | None = None,
) -> int:
    """Label the places in view. Returns the number labelled."""
    places = load_places() if places is None else places
    rank, limit, bounds = max_rank(view.deg_per_dot), label_limit(view.cols, view.rows), view.bounds()
    mark = "." if canvas.mode is Mode.ASCII else "·"
    drawn = 0
    for place in places:
        if place.scalerank > rank:
            break  # the file is ordered by scalerank
        if drawn >= limit:
            break
        if not bounds.contains(place.lat, place.lon):
            continue
        cell = canvas.cell_of(*view.to_dot(place.lat, place.lon))
        if cell is None:
            continue
        col, row = cell
        name = _name(place, canvas.mode)
        n = len(name) + 1
        # the mark sits in the place's own cell, the name beside it; one blank cell is kept between labels
        for start, text in ((col, mark + name), (col - n + 1, name + mark)):
            if _clear(canvas, start, row, n):
                canvas.text(start, row, text, color, Priority.LABEL - 1)
                drawn += 1
                break
    return drawn


def scale_length(view: Viewport, unit: str) -> tuple[int, int]:
    """(distance in `unit`, bar width in cells) for the longest round distance (1, 2 or 5 times a power of ten) whose
    bar fits. Scale is true at the center latitude, where a dot is deg_per_dot degrees of latitude across both ways.
    (0, 0) when no round distance gives a bar between SCALE_MIN_CELLS and the longest that fits."""
    per_cell = convert(view.dots_x * view.deg_per_dot * NM_PER_DEGREE, "nm", unit)
    longest = min(SCALE_MAX_CELLS, view.cols // 3)
    if per_cell <= 0 or longest < SCALE_MIN_CELLS:
        return (0, 0)
    exponent = math.floor(math.log10(longest * per_cell)) + 1
    for power in range(exponent, exponent - 4, -1):
        for step in reversed(_NICE):
            distance = step * 10**power
            cells = round(distance / per_cell)
            if SCALE_MIN_CELLS <= cells <= longest:
                return (distance, cells)
    return (0, 0)


def draw_scale_bar(canvas: Canvas, view: Viewport, unit: str, color: str | None) -> bool:
    """A scale bar in the bottom row, at the left or else the right; skipped if neither end is clear. The distance is
    printed in words, so the bar reads without color."""
    unit = unit if unit in SCALE_UNITS else "nm"
    distance, cells = scale_length(view, unit)
    if cells == 0:
        return False
    ends = ("+", "+", "-") if canvas.mode is Mode.ASCII else ("├", "┤", "─")
    text = f"{ends[0]}{ends[2] * (cells - 2)}{ends[1]} {distance:g} {LABELS[unit]}"
    row = canvas.rows - 1
    for col in (1, canvas.cols - len(text) - 1):
        if _clear(canvas, col, row, len(text)):
            canvas.text(col, row, text, color, Priority.LABEL)
            return True
    return False
