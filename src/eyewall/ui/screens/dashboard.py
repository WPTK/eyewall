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
from textual.css.scalar import Unit
from textual.events import Resize
from textual.screen import Screen
from textual.widgets import OptionList, TabbedContent, TabPane

from eyewall.poll import FreshnessState
from eyewall.sources import protocol
from eyewall.ui import adapt
from eyewall.ui import format as fmt
from eyewall.ui.widgets.map_view import MapPane, MapView
from eyewall.ui.widgets.panels import PANEL_KINDS, Panel, StatusBar, has_text
from eyewall.ui.widgets.storm_list import StormList

if TYPE_CHECKING:
    from eyewall.app import EyewallApp

NARROW_BELOW = 110
COMPACT_BELOW = 90
ROW_REFRESH_SECONDS = 30.0
HEADLINE_ROWS = 6  # the least the stacked headline is given: its border and four lines
MIN_PANEL_ROWS = 4  # the least any other stacked panel is given: its border and two lines


class DashboardMap(MapView):
    """The dashboard's map: the keys only it has, listed in the footer while it has the focus."""

    BINDINGS = [
        Binding("c", "screen.center", "center"),
        Binding("l", "screen.layers", "layers"),
    ]


class DashboardScreen(Screen[None]):
    BINDINGS = [
        Binding("j", "cursor(1)", "Next storm", show=False),
        Binding("k", "cursor(-1)", "Previous storm", show=False),
        Binding("enter", "open_detail", "detail"),
        Binding("1", "basin('AL')", "Atlantic", show=False),
        Binding("2", "basin('EP')", "East Pacific", show=False),
        Binding("3", "basin('CP')", "Central Pacific", show=False),
        Binding("a", "basin('')", "All basins", show=False),
        Binding("b", "buoys", "buoys"),
        Binding("m", "toggle_map", "map"),
        Binding("M", "full_map", "Full map", show=False),
        Binding("l", "layers", "Layers", show=False),
        Binding("plus,equals_sign", "zoom_in", "Zoom in", show=False),
        Binding("minus", "zoom_out", "Zoom out", show=False),
        Binding("c", "center", "Center storm", show=False),
        Binding("f", "fit", "Fit storm", show=False),
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
        self.map_view = DashboardMap(mode=eye.map_mode, options=eye.map_options)
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
        self.call_after_refresh(self.fit_stack)

    def fit_stack(self) -> None:
        """Share the stacked column's height between its panels. The headline keeps at least `HEADLINE_ROWS` and every
        other panel at least `MIN_PANEL_ROWS`; when the column is too short for that, panels are dropped from the
        bottom until the rest fit. The others take what their text needs, up to their cap, the shortest first, and an
        even share when there is not enough room. The headline gets the rest, up to what its text needs. Once it has
        all of its text, rows still free go to the panels cut short by their cap. A panel whose text is longer than
        its rows scrolls inside itself."""
        stack = self.query_one("#side-stack")
        headline = stack.query_one(".headline", Panel)  # it always has text
        filled = [p for p in stack.query(Panel) if p.filled and p is not headline]
        if not stack.display or stack.size.height < 1:
            return
        room = (stack.size.height - HEADLINE_ROWS) // MIN_PANEL_ROWS
        others = filled[: max(room, 0)]
        for panel in filled:
            dropped = panel not in others
            panel.dropped = dropped
            panel.display = not dropped
        panels = [headline, *others]
        text_width = stack.size.width - 4  # the border and the padding; a panel that scrolls is cut short anyway
        full: dict[Panel, int] = {}
        wants: dict[Panel, int] = {}
        for panel in panels:
            text_rows = panel.body.get_content_height(stack.size, stack.size, text_width)  # no layout needed
            full[panel] = max(text_rows + 2, MIN_PANEL_ROWS)  # the text and the border
            cap = panel.styles.base.max_height  # the stylesheet's cap, not the lifted one set below
            capped = int(cap.value) if cap is not None and cap.unit == Unit.CELLS else full[panel]
            wants[panel] = max(min(full[panel], capped), MIN_PANEL_ROWS)
        rows = dict.fromkeys(panels, 0)
        left = stack.size.height - HEADLINE_ROWS
        for index, panel in enumerate(sorted(others, key=lambda p: wants[p])):
            rows[panel] = min(wants[panel], max(left, 0) // (len(others) - index))
            left -= rows[panel]
        rows[headline] = min(wants[headline], stack.size.height - sum(rows.values()))
        spare = stack.size.height - sum(rows.values())
        if rows[headline] >= wants[headline]:  # the headline is whole: the cut-short panels may grow
            for panel in others:
                grow = min(spare, full[panel] - rows[panel])
                rows[panel] += grow
                spare -= grow
        for panel, height in rows.items():
            panel.styles.height = panel.styles.max_height = max(height, MIN_PANEL_ROWS)  # lifts the cap when it grew

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
            "ww": fmt.ww_panel(store, selected, eye.glyphs, now),
            "wind": fmt.wind_panel(store, selected, eye.preset),
            "surge": fmt.surge_panel(store, selected),
            "buoys": fmt.buoy_strip(store, selected, now, eye.preset, eye.glyphs),
        }
        for panel in self.query(Panel):
            panel.update(texts[panel.kind])
        tabs = self.query_one("#side-tabs", TabbedContent)
        for kind, text in texts.items():  # a panel with nothing to say is left out, the tab as well
            if kind != "headline":
                (tabs.show_tab if has_text(text) else tabs.hide_tab)(f"tab-{kind}")
        self.call_after_refresh(self.fit_stack)
        scene = adapt.map_scene(store, now, selected)
        self.map_view.set_scene(scene, self._fit_points())

    def _fit_points(self) -> list[tuple[float, float]]:
        eye = self.eye
        state = eye.store.storms.get(eye.selected or "")
        if state is not None:
            points = adapt.storm_scene(state).near_extent()
            if points:
                return points
        return adapt.basin_points(eye.basin_view)

    def refresh_status(self) -> None:
        self.query_one("#status", StatusBar).show(self.eye.status_text(self.size.width, self))

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
        self._relayout()

    def action_full_map(self) -> None:
        self._full_map = not self._full_map
        self._relayout()

    def _relayout(self) -> None:
        """A layout key: the panels are refitted to the new width, and the focus goes where the keys still work."""
        self._apply_layout()
        self.call_after_refresh(self.fit_stack)
        self.call_after_refresh(self._refocus)

    def _refocus(self) -> None:
        """Hiding a focused widget clears the focus; give it to the map when it is shown, else to the storm list."""
        if self.focused is not None:
            return
        map_shown = (
            self._full_map
            or self.has_class("show-map")
            or not (self.has_class("compact") or self.has_class("hide-map"))
        )
        (self.map_view if map_shown else self.query_one("#storms", StormList)).focus()

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
