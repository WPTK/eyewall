"""The outlook screen: the tropical weather outlook text per basin, a map of its areas by risk, and the watchlist.

This is what there is to look at between storms. The text comes from the NHC outlook products, the shapes from the
graphical outlook, and the watchlist rows from the buoys named in the `[watchlist]` config section.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Static

from eyewall.clock import format_age, format_zulu
from eyewall.models.outlook import OutlookArea
from eyewall.palette import risk_color
from eyewall.ui import adapt
from eyewall.ui import format as fmt
from eyewall.ui.theme import DIM
from eyewall.ui.widgets.map_view import MapPane, MapView
from eyewall.units import MISSING

if TYPE_CHECKING:
    from eyewall.app import EyewallApp


def _area_text(out: Text, area: OutlookArea, label: str) -> None:
    out.append(f"\n{label}", style="bold")
    if area.invest_id:
        out.append(f"  ({area.invest_id})", style=DIM)
    out.append("\n")
    out.append(fmt.collapse(area.description) + "\n")
    for name, chance in (("48 hours", area.chance_48h), ("7 days", area.chance_7d)):
        if chance is not None:
            out.append(f"  {name}: ", style=DIM)
            out.append(f"{chance.risk or '--'}, {fmt.chance_text(chance)}\n", style=risk_color(chance.risk))


def outlook_text(eye: EyewallApp) -> Text:
    """The outlook of every enabled basin, as laid out on the screen."""
    out = Text()
    outlook = eye.store.outlook
    if outlook is None:
        out.append("Waiting for the tropical weather outlook.", style=DIM)
        return out
    shown = False
    for text in outlook.texts:
        covered = [b for b in fmt.text_basins(text) if b in eye.basin_view]
        if not covered:
            continue
        shown = True
        out.append(f"{text.region or ' / '.join(fmt.BASIN_NAMES[b] for b in covered)}\n", style="bold #8fd3ff")
        if text.issued is not None:
            out.append(f"Issued {format_zulu(text.issued, day=True)}\n", style=DIM)
        if text.active_systems:
            out.append("\n" + fmt.collapse(text.active_systems) + "\n")
        if text.areas:
            for index, area in enumerate(text.areas, start=1):
                _area_text(out, area, fmt.invest_label(area, "", index) + f": {fmt.collapse(area.title)}")
        else:
            out.append("\n" + fmt.collapse(text.summary) + "\n")
        out.append("\n")
    if not shown:
        out.append("No outlook for the enabled basins.", style=DIM)
    return out


def watchlist_rows(eye: EyewallApp) -> list[tuple[str, ...]]:
    rows: list[tuple[str, ...]] = []
    now, preset = eye.now(), eye.preset
    for station_id in eye.config.watchlist.ndbc:
        station = eye.store.stations.get(station_id)
        latest = eye.store.latest.get(station_id)
        series = eye.store.series.get(station_id)
        obs = series.latest if series and series.latest else (latest.observation if latest else None)
        wind = None if obs is None or obs.wind_speed_mps is None else obs.wind_speed_mps / 0.514444
        age = MISSING if obs is None else format_age((now - obs.time).total_seconds())
        rows.append(
            (
                station_id,
                station.name if station else MISSING,
                preset.fmt_wind(wind),
                preset.fmt_pressure(None if obs is None else obs.pressure_hpa, "hpa"),
                age,
            )
        )
    return rows


class OutlookScreen(Screen[None]):
    BINDINGS = [
        Binding("escape,O", "back", "Back"),
        Binding("plus,equals_sign", "zoom_in", "Zoom in", show=False),
        Binding("minus", "zoom_out", "Zoom out", show=False),
        Binding("f", "fit", "Fit", show=False),
    ]

    @property
    def eye(self) -> EyewallApp:
        return self.app  # type: ignore[return-value]

    def compose(self) -> ComposeResult:
        eye = self.eye
        self.map_view = MapView(mode=eye.map_mode, options=eye.map_options)
        with Horizontal(id="outlook-main"):
            with Vertical(id="outlook-left"):
                with VerticalScroll(id="outlook-scroll"):
                    yield Static("", id="outlook-text")
                yield Static("Watchlist", id="watchlist-title")
                yield DataTable(id="watchlist", zebra_stripes=True, cursor_type="row")
            yield MapPane(self.map_view, id="outlook-map")
        yield Static("", id="outlook-status")

    def on_mount(self) -> None:
        table = self.query_one("#watchlist", DataTable)
        table.add_columns("Buoy", "Name", "Wind", "Pressure", "Age")
        self.query_one("#outlook-left").border_title = "Tropical weather outlook"
        self.refresh_data()
        self.refresh_status()

    def refresh_status(self) -> None:
        self.query_one("#outlook-status", Static).update(self.eye.status_text(self.size.width))

    def refresh_data(self) -> None:
        eye = self.eye
        self.query_one("#outlook-text", Static).update(outlook_text(eye))
        table = self.query_one("#watchlist", DataTable)
        table.clear()
        for cells in watchlist_rows(eye):
            table.add_row(*cells)
        scene = adapt.map_scene(eye.store, eye.now(), None)
        points = [p for area in scene.outlook for ring in area.rings for p in ring] or adapt.basin_points(
            eye.basin_view
        )
        self.map_view.set_scene(scene, points)

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_zoom_in(self) -> None:
        self.map_view.action_zoom_in()

    def action_zoom_out(self) -> None:
        self.map_view.action_zoom_out()

    def action_fit(self) -> None:
        self.map_view.fit()
