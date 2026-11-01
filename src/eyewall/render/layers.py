"""Map layers: plain render-ready inputs, and the code that draws them over the base map.

Nothing here knows about NHC models or Textual. The UI adapts storm data to these dataclasses (positions in degrees,
winds in knots, radii in nautical miles, rings as sequences of (lat, lon)) and calls render_map(). Layers are drawn in
this order: land, coastline, borders, cone, outlook areas, surge lines, coastal watches and warnings, best track,
forecast line, wind radii, tide gauges, buoys, forecast points, storm center, labels, scale bar, place names,
cursor. Where two layers meet in one cell, the priority in canvas.Priority decides the color: track over warning over
cone over coast.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import NamedTuple

from eyewall.geo import destination, haversine_nm
from eyewall.palette import (
    BUOY,
    CONE_EDGE,
    CONE_FILL,
    CURSOR,
    FORECAST_DASH,
    MAP_LABEL,
    NEUTRAL,
    RING_PATTERNS,
    STALE,
    TIDE_GAUGE,
    WATCH_WARNING_CUES,
    Pattern,
    WatchWarning,
    category_color,
    risk_color,
    storm_force,
)
from eyewall.render.basemap import DEFAULT_STYLE, BasemapStyle, basemap_canvas, ensure_matches
from eyewall.render.canvas import Canvas, Mode, Priority, Shade
from eyewall.render.hits import Cell, Hits, Mark, MarkKind
from eyewall.render.places import draw_places, draw_scale_bar
from eyewall.render.projection import Bounds, LatLon, Viewport, bounds_of

Ring = tuple[LatLon, ...]
NEAR_HOURS = 72  # how far ahead of the storm the dashboard map looks when it fits
QuadrantRadii = tuple[float, float, float, float]  # nautical miles in the NE, SE, SW and NW quadrants, as in the TCM

# ------------------------------------------------------------------------------------------------------------ inputs


@dataclass(frozen=True)
class TrackPoint:
    """A storm position and its maximum sustained wind in knots (None when unknown)."""

    lat: float
    lon: float
    wind_kt: float | None = None


@dataclass(frozen=True)
class ForecastPoint:
    """A forecast position. label is the time shown beside it, such as '12Z Tue'; tau is its hours from the forecast's
    synoptic time, when known."""

    lat: float
    lon: float
    wind_kt: float | None = None
    label: str | None = None
    tau: int | None = None


@dataclass(frozen=True)
class WarningSegment:
    """A coastal watch or warning (a TCWW polyline) or a storm surge watch or warning line."""

    kind: WatchWarning
    points: tuple[LatLon, ...]


@dataclass(frozen=True)
class WindRadii:
    """Wind radii around a position: the extent of 34, 50 and 64 knot winds by quadrant, None where not reported."""

    lat: float
    lon: float
    kt34: QuadrantRadii | None = None
    kt50: QuadrantRadii | None = None
    kt64: QuadrantRadii | None = None


@dataclass(frozen=True)
class StormScene:
    """Everything the map draws for one storm. id names it for the hit map."""

    id: str = ""
    name: str | None = None
    center: TrackPoint | None = None
    best_track: tuple[TrackPoint, ...] = ()
    forecast: tuple[ForecastPoint, ...] = ()
    cone: tuple[Ring, ...] = ()
    warnings: tuple[WarningSegment, ...] = ()  # coastal watches and warnings
    surge: tuple[WarningSegment, ...] = ()  # storm surge watches and warnings
    radii: tuple[WindRadii, ...] = ()

    def extent(self) -> list[LatLon]:
        """Positions to fit the view around: the cone, or the forecast and track when there is no cone."""
        points = [p for ring in self.cone for p in ring]
        if not points:
            points = [(f.lat, f.lon) for f in self.forecast] + [(t.lat, t.lon) for t in self.best_track]
        if self.center is not None:
            points.append((self.center.lat, self.center.lon))
        return points

    def near_extent(self, hours: int = NEAR_HOURS) -> list[LatLon]:
        """Positions to fit a close view around: the center, the reach of its wind radii and the forecast out to
        `hours`. The cone and the long range outlook are left out, so a storm that recurves stays in the middle."""
        points: list[LatLon] = [(f.lat, f.lon) for f in self.forecast if f.tau is None or f.tau <= hours]
        if self.center is not None:
            points.append((self.center.lat, self.center.lon))
        for wind in self.radii:
            reach = max((max(q) for q in (wind.kt34, wind.kt50, wind.kt64) if q is not None), default=0.0)
            if reach > 0:
                points.extend(
                    destination((wind.lat, wind.lon), bearing, reach) for bearing in (0.0, 90.0, 180.0, 270.0)
                )
        return points


@dataclass(frozen=True)
class OutlookArea:
    """A tropical weather outlook area. risk is Low, Medium or High; label is the chance of formation, such as '40%'."""

    rings: tuple[Ring, ...]
    risk: str
    label: str | None = None


@dataclass(frozen=True)
class StationMark:
    """A buoy or tide gauge. wind_kt colors a buoy by NHC's wind thresholds; stale draws it dim. id is the station id,
    which is also its label on the map; name is for the tooltip."""

    lat: float
    lon: float
    wind_kt: float | None = None
    stale: bool = False
    id: str = ""
    name: str | None = None


@dataclass(frozen=True)
class MapScene:
    """Everything on the map besides the base map: storms, outlook areas, stations and the cursor."""

    storms: tuple[StormScene, ...] = ()
    outlook: tuple[OutlookArea, ...] = ()
    buoys: tuple[StationMark, ...] = ()
    tide_gauges: tuple[StationMark, ...] = ()
    cursor: LatLon | None = None
    distance_unit: str = "nm"  # the unit of the scale bar: nm, mi or km, from the reader's units preset


@dataclass(frozen=True)
class MapOptions:
    """Which layers to draw. land, borders, cone and radii mirror the [map] section of the config file; its glyph_set
    chooses the canvas Mode (ascii for the legacy Windows console)."""

    land: bool = True
    borders: bool = True
    cone: bool = True
    radii: bool = True
    coast: bool = True
    outlook: bool = True
    warnings: bool = True
    track: bool = True
    buoys: bool = True
    tide_gauges: bool = True
    labels: bool = True
    station_labels: bool = False
    places: bool = True  # place names and the scale bar


@dataclass(frozen=True)
class MapStyle:
    """Colors for the parts of the map that carry no meaning of their own. Meaningful colors come from palette."""

    basemap: BasemapStyle = DEFAULT_STYLE
    cone_fill: str = CONE_FILL
    cone_shade: Shade = Shade.SPARSE
    cone_edge: str = CONE_EDGE
    label: str = MAP_LABEL
    place: str = NEUTRAL
    buoy: str = BUOY
    tide_gauge: str = TIDE_GAUGE
    stale: str = STALE
    cursor: str = CURSOR
    forecast_dash: Pattern = FORECAST_DASH


DEFAULT_OPTIONS = MapOptions()
DEFAULT_MAP_STYLE = MapStyle()
EMPTY_SCENE = MapScene()

# ----------------------------------------------------------------------------------------------------------- drawing

_RING_STEPS = 12  # points per quadrant of a wind radii outline, one every 7.5 degrees of bearing
_RISK_SHADES = {"low": Shade.HATCH_LIGHT, "medium": Shade.HATCH_MEDIUM, "high": Shade.HATCH_HEAVY}
_WARNING_ORDER = (
    WatchWarning.TROPICAL_STORM_WATCH,
    WatchWarning.HURRICANE_WATCH,
    WatchWarning.TROPICAL_STORM_WARNING,
    WatchWarning.HURRICANE_WARNING,
)
_SURGE_ORDER = (WatchWarning.SURGE_WATCH, WatchWarning.SURGE_WARNING)


class _Label(NamedTuple):
    cell: tuple[int, int]
    text: str
    color: str
    bold: bool
    centered: bool


def _radii_outline(lat: float, lon: float, quadrants: QuadrantRadii) -> list[LatLon]:
    """A closed outline made of one quarter-circle arc per quadrant. Where neighbouring quadrants differ, the outline
    steps along the radial line between them, as the NHC wind radii polygons do. Coordinates are rounded to a
    meter so the result does not depend on the platform's trigonometry."""
    points: list[LatLon] = []
    for q, radius in enumerate(quadrants):
        for step in range(_RING_STEPS + 1):
            dest = destination((lat, lon), q * 90.0 + step * 90.0 / _RING_STEPS, max(0.0, radius))
            points.append((round(dest[0], 5), round(dest[1], 5)))
    return points


def _centroid(ring: Sequence[tuple[float, float]]) -> tuple[float, float]:
    """Area centroid of a ring in dot coordinates; the mean of the vertices if the ring has no area."""
    area = cx = cy = 0.0
    for (xa, ya), (xb, yb) in zip(ring, [*ring[1:], ring[0]], strict=True):
        cross = xa * yb - xb * ya
        area += cross
        cx += (xa + xb) * cross
        cy += (ya + yb) * cross
    if abs(area) < 1e-9:
        return (sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring))
    return (cx / (3.0 * area), cy / (3.0 * area))


def _draw_label(canvas: Canvas, label: _Label) -> None:
    """Place text beside a cell, trying the right, left, above and below in turn; skip it if nothing is free."""
    col, row = label.cell
    n = len(label.text)
    middle, right, left = col - n // 2, col + 1, col - n
    if label.centered:
        spots = [(middle, row), (middle, row - 1), (middle, row + 1)]
    else:
        spots = [(right, row), (left, row), (middle, row - 1), (middle, row + 1)]
        spots += [(right, row - 1), (right, row + 1), (left, row - 1), (left, row + 1)]
    for c, r in spots:
        if canvas.text_free(c, r, n):
            canvas.text(c, r, label.text, label.color, Priority.LABEL, bold=label.bold)
            return


def _draw_outlook(canvas: Canvas, view: Viewport, areas: Sequence[OutlookArea], labels: list[_Label]) -> None:
    for area in areas:
        color = risk_color(area.risk)
        rings = [view.project_path(ring) for ring in area.rings if len(ring) >= 3]
        if not rings:
            continue
        canvas.fill_polygon(
            rings, color, Priority.OUTLOOK, _RISK_SHADES.get(area.risk.strip().lower(), Shade.HATCH_LIGHT)
        )
        for ring in rings:
            canvas.polyline(ring, color, Priority.OUTLOOK, closed=True)
        if area.label:
            cell = canvas.cell_of(*_centroid(rings[0]))
            if cell is not None:
                labels.append(_Label(cell, area.label, color, True, True))


def _draw_cone(canvas: Canvas, view: Viewport, storm: StormScene, style: MapStyle) -> None:
    rings = [view.project_path(ring) for ring in storm.cone if len(ring) >= 3]
    canvas.fill_polygon(rings, style.cone_fill, Priority.CONE, style.cone_shade)
    for ring in rings:
        canvas.polyline(ring, style.cone_edge, Priority.CONE + 1, closed=True)


def _draw_segments(
    canvas: Canvas, view: Viewport, segments: Sequence[WarningSegment], order: Sequence[WatchWarning], prio: int
) -> None:
    for kind in order:
        for segment in segments:
            if segment.kind is kind:
                cue = WATCH_WARNING_CUES[kind]
                canvas.polyline(view.project_path(segment.points), cue.color, prio, dash=cue.pattern, width=2)


def _draw_tracks(canvas: Canvas, view: Viewport, storm: StormScene, style: MapStyle) -> None:
    """The best track as solid segments and the forecast as dashed ones, each colored by the intensity it reaches."""
    past = view.project_path((t.lat, t.lon) for t in storm.best_track)
    for i in range(1, len(past)):
        canvas.line(*past[i - 1], *past[i], category_color(storm.best_track[i].wind_kt), Priority.TRACK)
    last, center = (storm.best_track[-1] if storm.best_track else None), storm.center
    if last is not None and center is not None and (last.lat, last.lon) != (center.lat, center.lon):
        # The center is newer than the last best-track fix: close the gap with a solid segment (projected together,
        # so a pair across the antimeridian stays in one piece).
        a, b = view.project_path([(last.lat, last.lon), (center.lat, center.lon)])
        canvas.line(*a, *b, category_color(center.wind_kt), Priority.TRACK)
    ahead: list[TrackPoint | ForecastPoint] = list(storm.forecast)
    if storm.center is not None:
        ahead.insert(0, storm.center)
    future = view.project_path((p.lat, p.lon) for p in ahead)
    for i in range(1, len(future)):
        canvas.line(
            *future[i - 1], *future[i], category_color(ahead[i].wind_kt), Priority.TRACK, dash=style.forecast_dash
        )


def _draw_radii(canvas: Canvas, view: Viewport, storm: StormScene, style: MapStyle) -> None:
    for radii in storm.radii:
        for knots, quadrants in ((34, radii.kt34), (50, radii.kt50), (64, radii.kt64)):
            if quadrants is None or not any(quadrants):
                continue
            outline = view.project_path(_radii_outline(radii.lat, radii.lon, quadrants))
            canvas.polyline(outline, category_color(knots), Priority.RADII, dash=RING_PATTERNS[knots], closed=True)


def _draw_stations(
    canvas: Canvas,
    view: Viewport,
    stations: Sequence[StationMark],
    glyph: str,
    base_color: str,
    style: MapStyle,
    labels: list[_Label] | None,
) -> list[tuple[StationMark, Cell]]:
    """Draw the marks; return those that landed on the canvas with their cells."""
    placed: list[tuple[StationMark, Cell]] = []
    for station in stations:
        band = None if station.stale or not storm_force(station.wind_kt) else category_color(station.wind_kt)
        color = style.stale if station.stale else band or base_color
        cell = canvas.marker(
            *view.to_dot(station.lat, station.lon), glyph, color, Priority.STATION, bold=band is not None
        )
        if cell is None:
            continue
        placed.append((station, cell))
        if labels is not None and station.id:
            labels.append(_Label(cell, station.id, style.stale if station.stale else style.label, False, False))
    return placed


def draw_scene(
    canvas: Canvas,
    viewport: Viewport,
    scene: MapScene,
    options: MapOptions = DEFAULT_OPTIONS,
    style: MapStyle = DEFAULT_MAP_STYLE,
) -> Hits:
    """Draw everything above the base map onto a canvas that already holds it (or is blank). Returns where the storms,
    buoys and gauges landed, for clicking and for stepping through them with the keyboard."""
    ensure_matches(canvas, viewport)
    glyphs = canvas.glyphs
    labels: list[_Label] = []  # drawn last, so a label never hides a marker
    point_labels: list[_Label] = []
    station_labels = labels if options.station_labels else None
    if options.cone:
        for storm in scene.storms:
            _draw_cone(canvas, viewport, storm, style)
    if options.outlook:
        _draw_outlook(canvas, viewport, scene.outlook, labels)
    if options.warnings:
        for storm in scene.storms:
            _draw_segments(canvas, viewport, storm.surge, _SURGE_ORDER, Priority.SURGE)
        for storm in scene.storms:
            _draw_segments(canvas, viewport, storm.warnings, _WARNING_ORDER, Priority.WARNING)
    if options.track:
        for storm in scene.storms:
            _draw_tracks(canvas, viewport, storm, style)
    if options.radii:
        for storm in scene.storms:
            _draw_radii(canvas, viewport, storm, style)
    gauges: list[tuple[StationMark, Cell]] = []
    buoys: list[tuple[StationMark, Cell]] = []
    if options.tide_gauges:
        gauges = _draw_stations(
            canvas, viewport, scene.tide_gauges, glyphs.tide, style.tide_gauge, style, station_labels
        )
    if options.buoys:
        buoys = _draw_stations(canvas, viewport, scene.buoys, glyphs.buoy, style.buoy, style, station_labels)
    storm_cells: list[tuple[StormScene, Cell]] = []
    for storm in scene.storms:
        if options.track:
            for point in storm.forecast:
                color = category_color(point.wind_kt)
                cell = canvas.marker(*viewport.to_dot(point.lat, point.lon), glyphs.forecast, color, Priority.MARKER)
                if cell is not None and point.label:
                    point_labels.append(_Label(cell, point.label, style.label, False, False))
        if storm.center is not None:
            color = category_color(storm.center.wind_kt)
            cell = canvas.marker(
                *viewport.to_dot(storm.center.lat, storm.center.lon),
                glyphs.center,
                color,
                Priority.MARKER + 1,
                bold=True,
            )
            if cell is not None:
                storm_cells.append((storm, cell))
                if storm.name:
                    labels.insert(0, _Label(cell, storm.name, color, True, False))
    if options.labels:
        for label in [*labels, *point_labels]:
            _draw_label(canvas, label)
    if options.places:  # last, so a place never takes room a storm or station label wants
        draw_scale_bar(canvas, viewport, scene.distance_unit, style.label)
        draw_places(canvas, viewport, style.place)
    if scene.cursor is not None:
        canvas.marker(*viewport.to_dot(*scene.cursor), glyphs.cursor, style.cursor, Priority.CURSOR, bold=True)
    return _hits(storm_cells, buoys, gauges)


def _hits(
    storms: list[tuple[StormScene, Cell]],
    buoys: list[tuple[StationMark, Cell]],
    gauges: list[tuple[StationMark, Cell]],
) -> Hits:
    """The hit map. Where marks share a cell the one drawn last is on top: storms, then buoys, then gauges. The keyboard
    visits the storms first, then the stations nearest a storm first."""
    marks: list[tuple[Mark, Cell]] = [(Mark("storm", s.id), cell) for s, cell in storms if s.id]
    stations: list[tuple[Mark, Cell, float]] = []
    centers = [(s.center.lat, s.center.lon) for s, _ in storms if s.center is not None]
    groups: tuple[tuple[MarkKind, list[tuple[StationMark, Cell]]], ...] = (("buoy", buoys), ("gauge", gauges))
    for kind, group in groups:
        for station, cell in group:
            if station.id:
                near = min((haversine_nm(c, (station.lat, station.lon)) for c in centers), default=0.0)
                stations.append((Mark(kind, station.id), cell, near))
    drawn = [*marks, *((m, c) for m, c, _ in stations)]
    order = [m for m, _ in marks] + [m for m, _, _ in sorted(stations, key=lambda e: e[2])]
    return Hits(tuple(drawn), tuple(order))


def render_map(
    viewport: Viewport,
    scene: MapScene = EMPTY_SCENE,
    mode: Mode = Mode.BRAILLE,
    options: MapOptions = DEFAULT_OPTIONS,
    style: MapStyle = DEFAULT_MAP_STYLE,
) -> Canvas:
    """The finished map: the cached base map for this viewport with the scene drawn over it."""
    return render_map_hits(viewport, scene, mode, options, style)[0]


def render_map_hits(
    viewport: Viewport,
    scene: MapScene = EMPTY_SCENE,
    mode: Mode = Mode.BRAILLE,
    options: MapOptions = DEFAULT_OPTIONS,
    style: MapStyle = DEFAULT_MAP_STYLE,
) -> tuple[Canvas, Hits]:
    """The finished map and the hit map of its marks."""
    canvas = basemap_canvas(
        viewport, mode, land=options.land, coast=options.coast, borders=options.borders, style=style.basemap
    )
    return canvas, draw_scene(canvas, viewport, scene, options, style)


def scene_bounds(scene: MapScene) -> Bounds | None:
    """Bounds around every storm in a scene, for fitting the view. None when there are no storms."""
    points = [p for storm in scene.storms for p in storm.extent()]
    return bounds_of(points) if points else None
