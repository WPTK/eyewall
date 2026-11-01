"""The map widget: M3's canvas painted line by line, with layer toggles, zoom, pan and fit.

`MapView` owns a `Viewport` and a `MapScene`. The base map comes from `render_map`, which already picks the detailed
Natural Earth data below `basemap.DETAIL_SWITCH` degrees per dot and the coarse copy above it; the widget only reports
which one is showing. The rendered rows are kept until something changes, so scrolling the storm list costs nothing.
"""

from __future__ import annotations

from dataclasses import replace

from rich.cells import cell_len
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.strip import Strip
from textual.widget import Widget
from textual.widgets import Static

from eyewall.geo import LatLon
from eyewall.palette import (
    DIM,
    HEADING,
    PATTERN_SAMPLES,
    RING_KNOTS,
    RING_PATTERNS,
    WATCH_WARNING_CUES,
    Pattern,
    WatchWarning,
    category_color,
)
from eyewall.render.basemap import is_detailed
from eyewall.render.canvas import ASCII_GLYPHS, UNICODE_GLYPHS, Mode
from eyewall.render.layers import DEFAULT_MAP_STYLE, EMPTY_SCENE, MapOptions, MapScene, render_map
from eyewall.render.projection import Viewport
from eyewall.ui.adapt import basin_points
from eyewall.ui.widgets.strips import blank, canvas_strips

ZOOM_STEP = 2.0
PAN_FRACTION = 8  # an arrow key moves the view by 1/8 of its size
LAYER_NAMES: dict[str, str] = {
    "land": "Land fill",
    "coast": "Coastline",
    "borders": "Country and state borders",
    "cone": "Forecast cone",
    "track": "Track and forecast points",
    "radii": "Wind radii",
    "warnings": "Watches and warnings",
    "outlook": "Outlook areas",
    "buoys": "Buoys",
    "tide_gauges": "Tide gauges",
    "labels": "Storm and point labels",
    "places": "Place names and scale bar",
    "station_labels": "Station labels",
}


class MapView(Widget, can_focus=True):
    """A terminal map. Arrow keys pan while it has focus; the zoom and fit keys are also bound by the screen."""

    BINDINGS = [
        Binding("plus,equals_sign", "zoom_in", "zoom", key_display="+/-"),
        Binding("minus", "zoom_out", "zoom out", show=False),
        Binding("f", "screen.fit", "fit"),
        Binding("left", "pan(-1, 0)", "Pan left", show=False),
        Binding("right", "pan(1, 0)", "Pan right", show=False),
        Binding("up", "pan(0, -1)", "Pan up", show=False),
        Binding("down", "pan(0, 1)", "Pan down", show=False),
    ]

    class Changed(Message):
        """The view moved or the scene was replaced; the legend under the map reads the new state."""

    def __init__(
        self,
        *,
        mode: Mode = Mode.BRAILLE,
        options: MapOptions | None = None,
        fit_default: list[LatLon] | None = None,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self.mode = mode
        self.options = options or MapOptions()
        self.scene: MapScene = EMPTY_SCENE
        self.cursor: LatLon | None = None
        self.auto_fit = True
        self._fit_points: list[LatLon] = fit_default or basin_points(())
        self._fit_key: tuple[LatLon, ...] = ()
        self._viewport: Viewport | None = None
        self._strips: list[Strip] | None = None

    # ---- state ------------------------------------------------------------------------------------------------

    @property
    def viewport(self) -> Viewport | None:
        return self._viewport

    @property
    def detailed(self) -> bool:
        """True when this zoom draws the full 10 m coastline rather than the coarse whole-basin copy."""
        return self._viewport is not None and is_detailed(self._viewport)

    def set_scene(self, scene: MapScene, fit: list[LatLon] | None = None) -> None:
        """Replace what is drawn. The view re-fits when `fit` changed, unless the user has zoomed or panned."""
        self.scene = scene
        if fit:
            key = tuple(fit)
            if key != self._fit_key:
                self._fit_key = key
                self._fit_points = list(fit)
                if self.auto_fit:
                    self._viewport = None
        self._invalidate()

    def set_options(self, options: MapOptions) -> None:
        self.options = options
        self._invalidate()

    def set_mode(self, mode: Mode) -> None:
        if mode is not self.mode:
            self.mode = mode
            self._viewport = None
            self._invalidate()

    def _invalidate(self) -> None:
        self._strips = None
        self.refresh()
        self.post_message(self.Changed())

    def _ensure_viewport(self) -> Viewport | None:
        width, height = self.size.width, self.size.height
        if width < 1 or height < 1:
            return None
        view = self._viewport
        if view is None:
            self._viewport = Viewport.fit_points(
                self._fit_points, width, height, dots_x=self.mode.dots_x, dots_y=self.mode.dots_y
            )
        elif (view.cols, view.rows) != (width, height):
            self._viewport = view.resized(width, height)
            if self.auto_fit:
                self._viewport = None
                return self._ensure_viewport()
        return self._viewport

    # ---- drawing ----------------------------------------------------------------------------------------------

    def _distance_unit(self) -> str:
        """The distance unit of the reader's units preset, for the scale bar."""
        preset = getattr(self.app, "preset", None)
        return preset.distance if preset is not None else "nm"

    def _build(self) -> list[Strip]:
        view = self._ensure_viewport()
        if view is None:
            return []
        scene = replace(self.scene, cursor=self.cursor, distance_unit=self._distance_unit())
        canvas = render_map(view, scene, self.mode, self.options, DEFAULT_MAP_STYLE)
        return canvas_strips(canvas, view.cols)

    def render_line(self, y: int) -> Strip:
        if self._strips is None:
            self._strips = self._build()
        if 0 <= y < len(self._strips):
            return self._strips[y]
        return blank(self.size.width)

    def on_resize(self, event: events.Resize) -> None:
        self._strips = None
        self._ensure_viewport()
        self.refresh()
        self.post_message(self.Changed())

    # ---- actions ----------------------------------------------------------------------------------------------

    def _move(self, view: Viewport) -> None:
        self.auto_fit = False
        self._viewport = view
        self._invalidate()

    def zoom(self, factor: float, anchor: tuple[float, float] | None = None) -> None:
        view = self._ensure_viewport()
        if view is not None:
            self._move(view.zoom(factor, anchor))

    def action_zoom_in(self) -> None:
        self.zoom(ZOOM_STEP)

    def action_zoom_out(self) -> None:
        self.zoom(1.0 / ZOOM_STEP)

    def action_pan(self, dx: int, dy: int) -> None:
        view = self._ensure_viewport()
        if view is not None:
            self._move(view.pan_cells(dx * max(1, view.cols // PAN_FRACTION), dy * max(1, view.rows // PAN_FRACTION)))

    def center_on(self, point: LatLon | None) -> None:
        """Move the view to a position, keeping the zoom."""
        view = self._ensure_viewport()
        if view is not None and point is not None:
            self._move(view.centered_on(*point))

    def fit(self) -> None:
        """Show the whole fit set (the selected storm's cone, or the basins) again."""
        self.auto_fit = True
        self._viewport = None
        self._invalidate()

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        self.zoom(ZOOM_STEP, self._dot_of(event.x, event.y))
        event.stop()

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        self.zoom(1.0 / ZOOM_STEP, self._dot_of(event.x, event.y))
        event.stop()

    def on_click(self, event: events.Click) -> None:
        view = self._ensure_viewport()
        if view is not None:
            self.cursor = view.to_geo(*self._dot_of(event.x, event.y))
            self._invalidate()

    def _dot_of(self, x: int, y: int) -> tuple[float, float]:
        return (x * self.mode.dots_x + self.mode.dots_x / 2.0, y * self.mode.dots_y + self.mode.dots_y / 2.0)

    # ---- legend -----------------------------------------------------------------------------------------------

    def _pattern_key(self) -> list[list[tuple[str, str]]]:
        """Names the line patterns on the map: the wind rings by strength, then watch, warning and surge lines. Only
        what the scene draws is listed, so the key reads the same without color."""
        ascii_mode = self.mode is Mode.ASCII
        storms = self.scene.storms

        def sample(pattern: Pattern) -> str:
            return PATTERN_SAMPLES[pattern][1 if ascii_mode else 0]

        items: list[list[tuple[str, str]]] = []
        if self.options.radii:
            drawn = {
                knots
                for storm in storms
                for radii in storm.radii
                for knots, quadrants in ((34, radii.kt34), (50, radii.kt50), (64, radii.kt64))
                if quadrants is not None and any(quadrants)
            }
            for knots in RING_KNOTS:
                if knots in drawn:
                    ring = [(f" {knots}kt ", DIM), (sample(RING_PATTERNS[knots]), category_color(knots))]
                    items.append([(" rings", DIM), *ring] if not items else ring)
        if self.options.warnings:
            kinds = {segment.kind for storm in storms for segment in (*storm.warnings, *storm.surge)}
            first = True
            for kind in WatchWarning:
                if kind in kinds:
                    cue = WATCH_WARNING_CUES[kind]
                    parts = [(f" {cue.short} ", DIM), (sample(cue.pattern), cue.color)]
                    items.append([(" lines", DIM), *parts] if first else parts)
                    first = False
        return items

    def legend(self, width: int) -> Text:
        """The marks, then the zoom and the cursor. Items that do not fit the width go on the next line."""
        glyphs = ASCII_GLYPHS if self.mode is Mode.ASCII else UNICODE_GLYPHS
        self._ensure_viewport()
        items: list[list[tuple[str, str]]] = []
        for mark, name in (
            (glyphs.center, "storm"),
            (glyphs.forecast, "forecast"),
            (glyphs.buoy, "buoy"),
            (glyphs.tide, "gauge"),
        ):
            items.append([(f" {mark} ", "bold"), (name, DIM)])
        view = self._viewport
        if view is not None and width >= 60:
            items.append(
                [
                    (f"  {view.deg_per_dot:.2f} deg/dot ", DIM),
                    ("10m coast" if is_detailed(view) else "overview", HEADING),
                ]
            )
        if self.cursor is not None and width >= 80:
            lat, lon = self.cursor
            items.append(
                [(f"  {abs(lat):.2f}{'N' if lat >= 0 else 'S'} {abs(lon):.2f}{'E' if lon >= 0 else 'W'}", DIM)]
            )
        out = Text(no_wrap=True, overflow="ellipsis")
        _flow(out, items, width)
        key = self._pattern_key()
        if key:  # on its own rows, so the cursor joining the line above never changes how many rows the legend takes
            out.append("\n")
            _flow(out, key, width)
        return out


def _flow(out: Text, items: list[list[tuple[str, str]]], width: int) -> None:
    """Append items to a line, moving any that do not fit the width to the next one."""
    used = 0
    for item in items:
        size = sum(cell_len(text) for text, _ in item)
        if used and used + size > width:
            out.append("\n")
            used = 0
        for text, style in item:
            out.append(text, style=style)
        used += size


class MapPane(Vertical):
    """A map with a one-line legend under it."""

    def __init__(self, view: MapView, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.view = view
        self.legend = Static("", classes="legend")

    def compose(self) -> ComposeResult:
        yield self.view
        yield self.legend

    def on_map_view_changed(self, event: MapView.Changed) -> None:
        text = self.view.legend(self.size.width)
        self.legend.update(text)
        self.legend.styles.height = text.plain.count("\n") + 1
