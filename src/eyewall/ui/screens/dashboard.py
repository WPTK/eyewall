"""The dashboard: storm list, map, and the headline, warnings, wind, surge and buoy panels, with the status bar below.

Wide terminals (110 columns and up) show the panels stacked beside the map. Narrower ones fold them into tabs, and below
90 columns the map is hidden until `m` brings it back in place of the panels.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.events import Resize
from textual.screen import Screen
from textual.widgets import OptionList, TabbedContent, TabPane

from eyewall.poll import FreshnessState
from eyewall.sources import protocol
from eyewall.ui import adapt
from eyewall.ui import format as fmt
from eyewall.ui.widgets.map_view import MapPane, MapView
from eyewall.ui.widgets.panels import PANEL_KINDS, Panel, StatusBar
from eyewall.ui.widgets.storm_list import StormList

if TYPE_CHECKING:
    from eyewall.app import EyewallApp

NARROW_BELOW = 110
COMPACT_BELOW = 90
ROW_REFRESH_SECONDS = 30.0


class DashboardScreen(Screen[None]):
    BINDINGS = [
        Binding("j", "cursor(1)", "Next storm", show=False),
        Binding("k", "cursor(-1)", "Previous storm", show=False),
        Binding("enter", "open_detail", "Detail"),
        Binding("1", "basin('AL')", "Atlantic", show=False),
        Binding("2", "basin('EP')", "East Pacific", show=False),
        Binding("3", "basin('CP')", "Central Pacific", show=False),
        Binding("a", "basin('')", "All basins", show=False),
        Binding("b", "buoys", "Buoys"),
        Binding("m", "toggle_map", "Map"),
        Binding("M", "full_map", "Full map", show=False),
        Binding("l", "layers", "Layers"),
        Binding("plus,equals_sign", "zoom_in", "Zoom in", show=False),
        Binding("minus", "zoom_out", "Zoom out", show=False),
        Binding("c", "center", "Center storm", show=False),
        Binding("f", "fit", "Fit cone", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._map_toggled = False
        self._full_map = False

    # ---- layout -----------------------------------------------------------------------------------------------

    @property
    def eye(self) -> EyewallApp:
        return self.app  # type: ignore[return-value]

    def compose(self) -> ComposeResult:
        eye = self.eye
        self.map_view = MapView(mode=eye.map_mode, options=eye.map_options)
        with Horizontal(id="main"):
            yield StormList(id="storms")
            yield MapPane(self.map_view, id="map-pane")
            with VerticalScroll(id="side-stack"):
                for kind, title, _ in PANEL_KINDS:
                    yield Panel(kind, title)
            with TabbedContent(id="side-tabs"):
                for kind, title, short in PANEL_KINDS:
                    with TabPane(short, id=f"tab-{kind}"):
                        yield Panel(kind, title)
        yield StatusBar(id="status")

    def on_mount(self) -> None:
        self.query_one("#storms", StormList).border_title = "Storms"
        self.set_interval(ROW_REFRESH_SECONDS, self.refresh_data)
        self.refresh_data()
        self.refresh_status()

    def on_resize(self, event: Resize) -> None:
        self._apply_layout(event.size.width)
        self.refresh_status()

    def _apply_layout(self, width: int | None = None) -> None:
        width = self.size.width if width is None else width
        narrow, compact = width < NARROW_BELOW, width < COMPACT_BELOW
        self.set_class(narrow, "narrow")
        self.set_class(compact, "compact")
        self.set_class(self._map_toggled and compact, "show-map")
        self.set_class(self._map_toggled and not compact, "hide-map")
        self.set_class(self._full_map, "full-map")

    # ---- data -------------------------------------------------------------------------------------------------

    def refresh_data(self) -> None:
        """Rebuild the list and everything that follows the selection."""
        eye = self.eye
        unreachable = eye.poller.freshness(protocol.STORMS).state is FreshnessState.ERROR
        rows = fmt.build_rows(eye.store, eye.basin_view, eye.now(), eye.preset, eye.glyphs, unreachable=unreachable)
        eye.selected = self.query_one("#storms", StormList).set_rows(rows, eye.selected)
        self.refresh_selection()

    def refresh_selection(self) -> None:
        """Update the panels and the map for the selected storm or invest."""
        eye = self.eye
        store, selected, now = eye.store, eye.selected, eye.now()
        texts: dict[str, Text] = {
            "headline": fmt.headline_panel(store, selected, eye.basin_view),
            "ww": fmt.ww_panel(store, selected, eye.glyphs),
            "wind": fmt.wind_panel(store, selected, eye.preset),
            "surge": fmt.surge_panel(store, selected),
            "buoys": fmt.buoy_strip(store, selected, now, eye.preset, eye.glyphs),
        }
        for panel in self.query(Panel):
            panel.update(texts[panel.kind])
        tabs = self.query_one("#side-tabs", TabbedContent)
        if texts["surge"]:
            tabs.show_tab("tab-surge")
        else:
            tabs.hide_tab("tab-surge")
        scene = adapt.map_scene(store, now, selected)
        self.map_view.set_scene(scene, self._fit_points())

    def _fit_points(self) -> list[tuple[float, float]]:
        eye = self.eye
        state = eye.store.storms.get(eye.selected or "")
        if state is not None:
            points = adapt.storm_scene(state).extent()
            if points:
                return points
        return adapt.basin_points(eye.basin_view)

    def refresh_status(self) -> None:
        self.query_one("#status", StatusBar).show(self.eye.status_text(self.size.width))

    # ---- events -----------------------------------------------------------------------------------------------

    def on_storm_list_picked(self, event: StormList.Picked) -> None:
        if event.row_id != self.eye.selected:
            self.eye.selected = event.row_id
            self.refresh_selection()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.action_open_detail()

    # ---- actions ----------------------------------------------------------------------------------------------

    def action_cursor(self, step: int) -> None:
        storm_list = self.query_one("#storms", StormList)
        if step > 0:
            storm_list.action_cursor_down()
        else:
            storm_list.action_cursor_up()

    def action_open_detail(self) -> None:
        eye = self.eye
        if eye.selected in eye.store.storms:
            eye.open_detail(eye.selected)
        elif eye.selected:
            eye.notify("Invests have no detail page; the outlook (O) has the full text.", timeout=4)

    def action_buoys(self) -> None:
        """The Buoys tab of the selected storm, or the watchlist when there is no storm to look at."""
        eye = self.eye
        if eye.selected in eye.store.storms:
            eye.open_detail(eye.selected, "buoys")
        else:
            eye.action_watchlist()

    def action_basin(self, code: str) -> None:
        self.eye.basin_filter = code or None
        self.refresh_data()
        self.map_view.fit()

    def action_toggle_map(self) -> None:
        self._map_toggled = not self._map_toggled
        self._apply_layout()

    def action_full_map(self) -> None:
        self._full_map = not self._full_map
        self._apply_layout()

    def action_layers(self) -> None:
        self.eye.open_layers()

    def action_zoom_in(self) -> None:
        self.map_view.action_zoom_in()

    def action_zoom_out(self) -> None:
        self.map_view.action_zoom_out()

    def action_center(self) -> None:
        state = self.eye.store.storms.get(self.eye.selected or "")
        if state is not None and state.storm.lat is not None and state.storm.lon is not None:
            self.map_view.center_on((state.storm.lat, state.storm.lon))

    def action_fit(self) -> None:
        self.map_view.fit()
