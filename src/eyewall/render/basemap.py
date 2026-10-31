"""The base map: land, coastline and borders from the vendored Natural Earth data.

Every view draws the Natural Earth 1:10 million data (simplified to 0.002 degrees) except basin-scale views (0.3
degrees per dot or coarser), where a coarser copy of the same data (0.03 degrees, every island kept) is drawn instead.
State and province lines appear with the detailed data. The raster for a viewport is kept, because a map that only
gains a cursor or a new advisory should not redraw the coast.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache, lru_cache

from eyewall.mapdata.loader import KIND_STATE, MapLayer, MapPath, load_layer
from eyewall.render.canvas import Canvas, Mode, Priority, Shade
from eyewall.render.projection import Bounds, Viewport

# Degrees per dot at which the map switches from the detailed data to the coarse copy. A 120 by 40 cell view of the Gulf
# of Mexico and the Caribbean is about 0.16 degrees per dot; the whole basin is about one.
DETAIL_SWITCH = 0.3


@dataclass(frozen=True)
class BasemapStyle:
    land: str = "#3a4658"
    land_shade: Shade = Shade.LIGHT
    coast: str = "#9fb3c8"
    border: str = "#6e7f94"
    state: str = "#4a5668"


DEFAULT_STYLE = BasemapStyle()


def is_detailed(viewport: Viewport) -> bool:
    """Whether this zoom draws the full 10 m data rather than the coarse whole-basin copy."""
    return viewport.deg_per_dot < DETAIL_SWITCH


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
    fine = is_detailed(viewport)
    suffix = "" if fine else "_lo"
    if land:
        # Lakes are rings inside the land, so the even-odd fill leaves them as holes.
        rings = [
            viewport.project_path(path.points)
            for name in ("land" + suffix, "lakes" + suffix)
            for path in _visible(name, viewport)
        ]
        canvas.fill_polygon(rings, style.land, Priority.LAND, style.land_shade)
    if coast:
        for path in _visible("coast" + suffix, viewport):
            canvas.polyline(viewport.project_path(path.points), style.coast, Priority.COAST)
        for path in _visible("lakes" + suffix, viewport):
            dots = viewport.project_path(path.points)
            canvas.polyline([*dots, dots[0]], style.coast, Priority.COAST)
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
