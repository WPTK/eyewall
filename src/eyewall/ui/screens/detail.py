"""The storm detail screen: one tab per product, refreshed in place as new advisories arrive."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, OptionList, Static, TabbedContent, TabPane

from eyewall.config import watchlist_ids
from eyewall.ui import format as fmt
from eyewall.ui import products
from eyewall.ui import stations as st
from eyewall.ui.theme import DIM
from eyewall.ui.widgets.gallery import GalleryPanel
from eyewall.ui.widgets.station_table import StationTable

if TYPE_CHECKING:
    from eyewall.app import EyewallApp

# (tab id, title). Buoys and Tides are station tables, Graphics is the image gallery.
TABS: tuple[tuple[str, str], ...] = (
    ("summary", "Summary"),
    ("forecast", "Forecast"),
    ("public", "Advisory"),
    ("discussion", "Discussion"),
    ("probs", "Probs"),
    ("ww", "Warn"),
    ("buoys", "Buoys"),
    ("tides", "Tides"),
    ("graphics", "Graphics"),
    ("history", "History"),
)
TABLE_TABS = ("forecast", "probs", "history")
STATION_TABS = {"buoys": "ndbc", "tides": "coops"}  # tab id -> watchlist kind


class StormDetailScreen(Screen[None]):
    BINDINGS = [
        Binding("escape,backspace", "back", "Back"),
        Binding("left", "tab(-1)", "Previous tab", show=False, priority=True),
        Binding("right", "tab(1)", "Next tab", show=False, priority=True),
        Binding("t", "toggle_text", "TCP/TCM"),
        Binding("p", "pin", "Pin station"),
        *[
            Binding(str((i + 1) % 10), f"show_tab('{tab_id}')", title, show=False)
            for i, (tab_id, title) in enumerate(TABS)
        ],
    ]

    def __init__(self, storm_id: str, tab: str | None = None) -> None:
        super().__init__()
        self.storm_id = storm_id
        self._first_tab = tab
        self.show_tcm = False

    @property
    def eye(self) -> EyewallApp:
        return self.app  # type: ignore[return-value]

    def compose(self) -> ComposeResult:
        yield Static("", id="detail-title")
        with TabbedContent(id="detail-tabs"):
            for tab_id, title in TABS:
                with TabPane(title, id=f"tab-{tab_id}"):
                    if tab_id in STATION_TABS:
                        yield Static("", id=f"{tab_id}-note", classes="note")
                        yield StationTable(id=f"{tab_id}-table")
                    elif tab_id == "graphics":
                        yield GalleryPanel(self.storm_id, id="graphics-gallery")
                    elif tab_id in TABLE_TABS:
                        yield Static("", id=f"{tab_id}-note", classes="note")
                        yield DataTable(id=f"{tab_id}-table", zebra_stripes=True, cursor_type="row")
                    else:
                        with VerticalScroll():
                            yield Static("", id=f"{tab_id}-text", classes="detail-text")
        yield Static("", id="detail-status")

    def on_mount(self) -> None:
        if self._first_tab in dict(TABS):
            self.query_one("#detail-tabs", TabbedContent).active = f"tab-{self._first_tab}"
        self.refresh_data()
        self.refresh_status()

    # ---- data -------------------------------------------------------------------------------------------------

    def refresh_status(self) -> None:
        self.query_one("#detail-status", Static).update(self.eye.status_text(self.size.width))

    def _set_table(self, tab_id: str, table: products.Table, note: str) -> None:
        widget = self.query_one(f"#{tab_id}-table", DataTable)
        columns, rows = table
        row = widget.cursor_row
        widget.clear(columns=True)
        widget.add_columns(*columns)
        for cells in rows:
            widget.add_row(*cells)
        if rows:
            widget.move_cursor(row=min(row, len(rows) - 1))
        self.query_one(f"#{tab_id}-note", Static).update(Text(note, style=DIM))

    def _set_text(self, tab_id: str, text: Text) -> None:
        self.query_one(f"#{tab_id}-text", Static).update(text)

    def refresh_data(self) -> None:
        eye = self.eye
        state = eye.store.storms.get(self.storm_id)
        title = self.query_one("#detail-title", Static)
        if state is None:
            title.update(
                Text(f" {self.storm_id.upper()} is no longer active. Press Esc to go back.", style="bold #ffa63d")
            )
            return
        now, preset, tz, g = eye.now(), eye.preset, eye.local_tz, eye.glyphs
        storm = state.storm
        head = Text(no_wrap=True, overflow="ellipsis")
        head.append(f" {fmt.class_label(storm)} ", style=f"bold {fmt.storm_color(storm)}")
        head.append(f"{storm.name.upper()}", style="bold")
        head.append(f"  {preset.fmt_wind(storm.intensity_kt)}  {preset.fmt_pressure(storm.pressure_mb)}", style=DIM)
        title.update(head)
        self._set_text("summary", products.summary(state, now, preset, tz))
        self._set_table("forecast", products.forecast_table(state, preset, tz), products.forecast_note(state))
        text = products.forecast_advisory(state, preset) if self.show_tcm else products.public_advisory(state, g)
        self._set_text("public", text)
        self._set_text("discussion", products.discussion(state, g))
        self._set_table("probs", products.wind_probabilities(state), products.probabilities_note(state))
        self._set_text("ww", products.watches_warnings(eye.store, state, g))
        self._set_table("history", products.history_table(state, preset), "Best track, newest first.")
        self._refresh_stations()
        self.query_one("#graphics-gallery", GalleryPanel).refresh_data()

    def _refresh_stations(self) -> None:
        eye = self.eye
        store, now, preset = eye.store, eye.now(), eye.preset
        buoys = st.from_nearby(store.nearby_buoys(self.storm_id))
        self.query_one("#buoys-table", StationTable).set_rows(
            st.BUOY_COLUMNS, st.buoy_rows(store, buoys, now, preset, eye.glyphs)
        )
        nearby = store.config.nearby
        self.query_one("#buoys-note", Static).update(
            Text(
                f"{len(buoys)} buoys within {preset.fmt_distance(nearby.radius_now_nm)} or "
                f"{preset.fmt_distance(nearby.radius_track_nm)} of the track. Enter: charts. p: pin. * = watchlist.",
                style=DIM,
            )
        )
        gauges = st.from_nearby(store.nearby_tides(self.storm_id))
        self.query_one("#tides-table", StationTable).set_rows(st.TIDE_COLUMNS, st.tide_rows(store, gauges, now, preset))
        self.query_one("#tides-note", Static).update(
            Text(
                f"{len(gauges)} gauges near the storm. Residual = observed minus predicted: the surge estimate. "
                "p: pin. * = watchlist.",
                style=DIM,
            )
        )

    # ---- actions ----------------------------------------------------------------------------------------------

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_tab(self, step: int) -> None:
        ids = [f"tab-{t}" for t, _ in TABS]
        tabs = self.query_one("#detail-tabs", TabbedContent)
        current = ids.index(tabs.active) if tabs.active in ids else 0
        tabs.active = ids[(current + step) % len(ids)]

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        """Land the focus on the tab's table, so the arrows and Enter act on its rows straight away."""
        gallery = self.query_one("#graphics-gallery", GalleryPanel)
        gallery.set_active(event.pane.id == "tab-graphics")
        for table in event.pane.query(StationTable):
            table.focus()
            break
        if event.pane.id == "tab-graphics":
            gallery.query_one(OptionList).focus()

    def on_screen_suspend(self) -> None:
        self.query_one("#graphics-gallery", GalleryPanel).set_active(False)

    def on_screen_resume(self) -> None:
        tabs = self.query_one("#detail-tabs", TabbedContent)
        self.query_one("#graphics-gallery", GalleryPanel).set_active(tabs.active == "tab-graphics")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "buoys-table" and event.row_key.value is not None:
            event.stop()
            self.eye.open_buoy(str(event.row_key.value))

    def action_pin(self) -> None:
        tabs = self.query_one("#detail-tabs", TabbedContent)
        tab_id = (tabs.active or "").removeprefix("tab-")
        kind = STATION_TABS.get(tab_id)
        if kind is None:
            self.eye.notify("Pin works on the Buoys and Tides tabs: move to a row and press p.", timeout=4)
            return
        key = self.query_one(f"#{tab_id}-table", StationTable).current_key()
        if key is not None:
            self.eye.watch_in_background(kind, key, key.upper() not in watchlist_ids(self.eye.config, kind))

    def action_show_tab(self, tab_id: str) -> None:
        self.query_one("#detail-tabs", TabbedContent).active = f"tab-{tab_id}"

    def action_toggle_text(self) -> None:
        tabs = self.query_one("#detail-tabs", TabbedContent)
        if tabs.active == "tab-public":
            self.show_tcm = not self.show_tcm
        else:
            tabs.active = "tab-public"
        self.refresh_data()
