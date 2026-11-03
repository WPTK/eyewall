"""The base map: land, coastline and borders from the vendored Natural Earth data.

Every view draws the Natural Earth 1:10 million data in one of three simplifications of it: 0.002 degrees (about 220 m)
below DETAIL_SWITCH degrees per dot, 0.009 (about 1 km, what linecast draws) up to MID_SWITCH, and 0.03 for a
hemisphere. Each keeps every island. Borders, and the state and province lines with them, appear with the full tier
only. Land is a flat background
tint of the cells inside it; a cell the shore runs through shows its land-side dots instead (a part-cell glyph), so the
shore follows the data to the dot and not to the cell. The raster for a
viewport is kept, because a map that only gains a cursor or a new advisory should not redraw the coast.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache, lru_cache

from eyewall.mapdata.loader import DATA_EAST, DATA_NORTH, DATA_SOUTH, KIND_STATE, MapLayer, MapPath, load_layer
from eyewall.palette import BORDER, COAST, LAND, STATE_LINE
from eyewall.render.canvas import Canvas, Dot, Mode, Priority
from eyewall.render.projection import Bounds, Viewport

# Degrees per dot at which the map stops drawing borders and keeps only the lakes a few cells across. A 120 by 40 cell
# view of the Gulf of Mexico and the Caribbean is about 0.16 degrees per dot; the whole basin is about one.
DETAIL_SWITCH = 0.3
# The 1 km tier takes over from the full one here, and the 0.03 degree tier from it at MID_SWITCH. Measured, an
# uncached draw of a basin at 0.28 degrees per dot is 0.4 s on the full tier and 0.2 s on the 1 km one.
THIN_GAP = 0.7  # dots; see _project
MID_SWITCH = 0.6  # a quiet-day map is at most 0.5; the 0.03 degree tier is for a hemisphere
MIN_LAKE_CELLS = 3  # at basin scale a lake narrower than this, in cells, is left out


@dataclass(frozen=True)
class BasemapStyle:
    land: str = LAND
    coast: str = COAST
    border: str = BORDER
    state: str = STATE_LINE


DEFAULT_STYLE = BasemapStyle()


def is_detailed(viewport: Viewport) -> bool:
    """Whether this zoom draws the full 10 m data rather than the coarse whole-basin copy."""
    return viewport.deg_per_dot < DETAIL_SWITCH


def tier_suffix(viewport: Viewport) -> str:
    """The layer-name suffix of the data tier this zoom draws: '' (full), '_mid' (1 km) or '_lo'."""
    if viewport.deg_per_dot < DETAIL_SWITCH:
        return ""
    return "_mid" if viewport.deg_per_dot < MID_SWITCH else "_lo"


def ensure_matches(canvas: Canvas, viewport: Viewport) -> None:
    """Raise if a canvas and a viewport disagree about the grid, which would silently misplace everything."""
    if (canvas.cols, canvas.rows, canvas.dots_x, canvas.dots_y) != (
        viewport.cols,
        viewport.rows,
        viewport.dots_x,
        viewport.dots_y,
    ):
        raise ValueError(
            f"viewport is {viewport.cols}x{viewport.rows} cells of {viewport.dots_x}x{viewport.dots_y} dots, "
            f"canvas is {canvas.cols}x{canvas.rows} cells of {canvas.dots_x}x{canvas.dots_y} dots"
        )


@cache
def _indexed(name: str) -> tuple[MapLayer, tuple[tuple[Bounds, MapPath], ...]]:
    layer = load_layer(name)
    return layer, tuple((Bounds(p.south, p.west, p.north, p.east - p.west), p) for p in layer.paths)


def _visible(name: str, viewport: Viewport) -> list[MapPath]:
    view = viewport.bounds()
    return [path for bounds, path in _indexed(name)[1] if view.intersects(bounds)]


def _cut_lines(viewport: Viewport) -> tuple[float, float, float]:
    """Where the vendored data stops, in dots: the northern and southern cuts and the Atlantic-side cut."""
    return (
        viewport.to_dot(DATA_NORTH, 0.0)[1],
        viewport.to_dot(DATA_SOUTH, 0.0)[1],
        viewport.to_dot(0.0, DATA_EAST)[0],
    )


def _project(path: MapPath, viewport: Viewport, gap: float) -> list[Dot]:
    """A path in dot coordinates. With a gap, a vertex less than that many dots from the last one kept is dropped (the
    first and the last never are), because at the 1 km tier and coarser most neighbouring vertices share a dot and
    cost a segment each for nothing."""
    dots = viewport.project_path(path.points)
    if gap <= 0.0 or len(dots) < 3:
        return dots
    limit = gap * gap
    kept = [dots[0]]
    x, y = dots[0]
    for point in dots[1:-1]:
        if (point[0] - x) ** 2 + (point[1] - y) ** 2 >= limit:
            kept.append(point)
            x, y = point
    kept.append(dots[-1])
    return kept


def _cells_across(ring: Sequence[Dot], canvas: Canvas) -> float:
    """The longer side of a ring's bounding box, in cells."""
    xs, ys = [p[0] for p in ring], [p[1] for p in ring]
    return max((max(xs) - min(xs)) / canvas.dots_x, (max(ys) - min(ys)) / canvas.dots_y)


def draw_basemap(
    canvas: Canvas,
    viewport: Viewport,
    *,
    land: bool = True,
    coast: bool = True,
    borders: bool = True,
    style: BasemapStyle = DEFAULT_STYLE,
) -> None:
    """Draw land fill, coastline and borders onto a canvas, in that order."""
    ensure_matches(canvas, viewport)
    fine = is_detailed(viewport)
    suffix = tier_suffix(viewport)
    gap = THIN_GAP if suffix else 0.0
    # Lakes are rings inside the land, so the even-odd fill leaves them as holes. At basin scale only the lakes a few
    # cells across are kept: the rest would be dark pinpricks and stray dots in the land.
    lakes = [_project(path, viewport, gap) for path in _visible("lakes" + suffix, viewport)] if land or coast else []
    if not fine:
        lakes = [ring for ring in lakes if _cells_across(ring, canvas) >= MIN_LAKE_CELLS]
    if land:
        canvas.tint_polygon(
            [_project(path, viewport, gap) for path in _visible("land" + suffix, viewport)] + lakes,
            style.land,
            style.coast if coast else None,
            cut=_cut_lines(viewport),
        )
    if coast:
        for path in _visible("coast" + suffix, viewport):
            canvas.polyline(_project(path, viewport, gap), style.coast, Priority.COAST)
        for ring in lakes:
            canvas.polyline([*ring, ring[0]], style.coast, Priority.COAST)
    if borders and fine:  # at basin scale a border is a few dots wide: noise, not information
        for path in _visible("borders", viewport):
            color = style.state if path.kind == KIND_STATE else style.border
            canvas.polyline(viewport.project_path(path.points), color, Priority.BORDER)


@lru_cache(maxsize=8)
def _raster(viewport: Viewport, mode: Mode, land: bool, coast: bool, borders: bool, style: BasemapStyle) -> Canvas:
    canvas = Canvas(viewport.cols, viewport.rows, mode)
    draw_basemap(canvas, viewport, land=land, coast=coast, borders=borders, style=style)
    return canvas


def basemap_canvas(
    viewport: Viewport,
    mode: Mode = Mode.BRAILLE,
    *,
    land: bool = True,
    coast: bool = True,
    borders: bool = True,
    style: BasemapStyle = DEFAULT_STYLE,
) -> Canvas:
    """A canvas holding the base map for a viewport, ready to draw on. The raster itself is cached per viewport."""
    return _raster(viewport, mode, land, coast, borders, style).copy()
