"""The base map: land, coastline and borders from the vendored Natural Earth data.

Zoomed out the 110 m data is enough; zoomed in the 50 m data takes over, and state and province lines appear. The raster
for a viewport is kept, because a map that only gains a cursor or a new advisory should not redraw the coast.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache, lru_cache

from eyewall.mapdata.loader import KIND_STATE, MapLayer, MapPath, load_layer
from eyewall.render.canvas import Canvas, Mode, Priority, Shade
from eyewall.render.projection import Bounds, Viewport

# Degrees per dot at which the map switches from the 110 m to the 50 m data. A 120 by 40 cell view of the Gulf of Mexico
# and the Caribbean is about 0.16 degrees per dot; the whole basin is about one.
DETAIL_SWITCH = 0.3


@dataclass(frozen=True)
class BasemapStyle:
    land: str = "#3a4658"
    land_shade: Shade = Shade.LIGHT
    coast: str = "#9fb3c8"
    border: str = "#6e7f94"
    state: str = "#4a5668"


DEFAULT_STYLE = BasemapStyle()


def detail_for(viewport: Viewport) -> int:
    """The Natural Earth scale to draw at this zoom: 50 for the 1:50 million data, 110 for the 1:110 million data."""
    return 50 if viewport.deg_per_dot < DETAIL_SWITCH else 110


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
    fine = detail_for(viewport) == 50
    if land:
        rings = [viewport.project_path(path.points) for path in _visible("land50" if fine else "land110", viewport)]
        canvas.fill_polygon(rings, style.land, Priority.LAND, style.land_shade)
    if coast:
        for path in _visible("coast50" if fine else "coast110", viewport):
            canvas.polyline(viewport.project_path(path.points), style.coast, Priority.COAST)
    if borders:
        for path in _visible("borders", viewport):
            if path.kind == KIND_STATE and not fine:
                continue
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
