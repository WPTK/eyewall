"""The outlook screen: the tropical weather outlook text per basin, a map of its areas by risk, and the watchlist.

This is what there is to look at between storms. The text comes from the NHC outlook products, the shapes from the
graphical outlook, and the watchlist rows from the buoys named in the `[watchlist]` config section.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import DataTable, Static

from eyewall.clock import format_age, format_zulu
from eyewall.models.outlook import OutlookArea
from eyewall.palette import DIM, HEADING, risk_color
from eyewall.ui import adapt, nav
from eyewall.ui import format as fmt
from eyewall.ui import stations as st
from eyewall.ui.chrome import ChromeScreen, FooterBar, TopBar
from eyewall.ui.widgets.map_view import MapPane, MapView
from eyewall.ui.widgets.station_table import StationTable
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
    seen: set[tuple[str, str]] = set()  # the eastern Pacific text repeats the central Pacific areas east of 180
    for text in outlook.texts:
        covered = [b for b in fmt.text_basins(text) if b in eye.basin_view]
        if not covered:
            continue
        areas = [a for a in text.areas if (a.title, a.description) not in seen]
        seen.update((a.title, a.description) for a in text.areas)
        shown = True
        out.append(f"{text.region or ' / '.join(fmt.BASIN_NAMES[b] for b in covered)}\n", style=f"bold {HEADING}")
        if text.issued is not None:
            out.append(f"Issued {format_zulu(text.issued, day=True)}\n", style=DIM)
        if text.active_systems:
            out.append("\n" + fmt.collapse(text.active_systems) + "\n")
        if text.areas:
            for area in areas:
                index = text.areas.index(area) + 1
                _area_text(out, area, fmt.invest_label(area, "", index) + f": {fmt.collapse(area.title)}")
        else:
            out.append("\n" + fmt.collapse(text.summary) + "\n")
        out.append("\n")
    if not shown:
        out.append("No outlook for the enabled basins.", style=DIM)
    return out


WATCHLIST_COLUMNS = ("Buoy", "Name", "Wind", "Pressure", "Age")


def watchlist_rows(eye: EyewallApp) -> list[tuple[str, tuple[Text, ...]]]:
    """The watchlisted buoys: wind, pressure and age, dimmed and marked when a station is not reporting."""
    rows: list[tuple[str, tuple[Text, ...]]] = []
    now, preset = eye.now(), eye.preset
    for entry in st.watchlist_buoys(eye.store):
        station_id = entry.id
        state = st.buoy_state(eye.store, station_id, now)
        obs = st.newest_observation(eye.store, station_id)
        name = st.clean_name(entry.station.name) or MISSING
        if state in ("silent", "dark") or obs is None:
            note = st.NOT_REPORTING if state in ("silent", "dark") else st.WAITING
            cells = (station_id, name, MISSING, MISSING, note)
            rows.append((station_id, tuple(Text(c, style=DIM) for c in cells)))
            continue
        wind = st.wind_kt(obs)
        rows.append(
            (
                station_id,
                (
                    Text(station_id, style="bold"),
                    Text(name),
                    st.banded(preset.fmt_wind(wind), wind),
                    Text(preset.fmt_pressure(obs.pressure_hpa, "hpa")),
                    Text(format_age((now - obs.time).total_seconds())),
                ),
            )
        )
    return rows


class OutlookScreen(ChromeScreen):
    CRUMB = "Outlook"
    NAV_SCOPES = ("outlook",)
    BINDINGS = nav.bindings("outlook")

    def compose(self) -> ComposeResult:
        eye = self.eye
        yield TopBar()
        self.map_view = MapView(mode=eye.map_mode, options=eye.map_options)
        with Horizontal(id="outlook-main"):
            with Vertical(id="outlook-left"):
                with VerticalScroll(id="outlook-scroll"):
                    yield Static("", id="outlook-text")
                yield Static("Watchlist   Enter: charts   w: edit", id="watchlist-title")
                yield StationTable(id="watchlist")
            yield MapPane(self.map_view, id="outlook-map")
        yield FooterBar()

    def on_mount(self) -> None:
        self.query_one("#outlook-left").border_title = "Tropical weather outlook"
        self.refresh_data()

    def refresh_data(self) -> None:
        eye = self.eye
        self.query_one("#outlook-text", Static).update(outlook_text(eye))
        self.query_one("#watchlist", StationTable).set_rows(WATCHLIST_COLUMNS, watchlist_rows(eye))
        scene = adapt.map_scene(eye.store, eye.now(), None)
        points = [p for area in scene.outlook for ring in area.rings for p in ring] or adapt.basin_points(
            eye.basin_view
        )
        self.map_view.set_scene(scene, points)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key.value is not None:
            event.stop()
            self.eye.open_buoy(str(event.row_key.value))

    def action_zoom_in(self) -> None:
        self.map_view.action_zoom_in()

    def action_zoom_out(self) -> None:
        self.map_view.action_zoom_out()

    def action_fit(self) -> None:
        self.map_view.fit()

    def action_mark(self, step: int) -> None:
        self.map_view.action_mark(step)
