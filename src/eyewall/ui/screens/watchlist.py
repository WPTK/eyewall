"""The watchlist: the buoys and tide gauges polled whether or not a storm is near, with add, remove and the charts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Static

from eyewall.palette import HEADING
from eyewall.ui import stations as st
from eyewall.ui.screens.search import SearchChoice, SearchScreen
from eyewall.ui.widgets.station_table import StationTable

if TYPE_CHECKING:
    from eyewall.app import EyewallApp


class WatchlistScreen(Screen[None]):
    BINDINGS = [
        Binding("a", "add", "add"),
        Binding("d,delete", "remove", "remove"),
        Binding("tab", "other_table", "other table", priority=True),
        Binding("escape,w", "back", "back"),
    ]

    @property
    def eye(self) -> EyewallApp:
        return self.app  # type: ignore[return-value]

    def compose(self) -> ComposeResult:
        with Vertical(id="watch-main"):
            yield Static("", id="watch-buoy-title", classes="watch-title")
            yield StationTable(id="watch-buoys")
            yield Static("", id="watch-tide-title", classes="watch-title")
            yield StationTable(id="watch-tides", charts=False)
        yield Static("", id="watch-status")

    def on_mount(self) -> None:
        self.query_one("#watch-buoys").focus()
        self.refresh_data()
        self.refresh_status()

    def refresh_status(self) -> None:
        self.query_one("#watch-status", Static).update(self.eye.status_text(self.size.width, self))

    def refresh_data(self) -> None:
        eye = self.eye
        store, now, preset = eye.store, eye.now(), eye.preset
        buoys, gauges = st.watchlist_buoys(store), st.watchlist_gauges(store)
        self.query_one("#watch-buoy-title", Static).update(Text(f" Buoys ({len(buoys)})", style=f"bold {HEADING}"))
        self.query_one("#watch-tide-title", Static).update(
            Text(f" Tide gauges ({len(gauges)})", style=f"bold {HEADING}")
        )
        columns = st.BUOY_COLUMNS[:2] + st.BUOY_COLUMNS[4:11]
        rows = [(key, cells[:2] + cells[4:11]) for key, cells in st.buoy_rows(store, buoys, now, preset, eye.glyphs)]
        self.query_one("#watch-buoys", StationTable).set_rows(columns, rows)
        tide_columns = st.TIDE_COLUMNS[:2] + st.TIDE_COLUMNS[4:10]
        tide_rows = [(key, cells[:2] + cells[4:10]) for key, cells in st.tide_rows(store, gauges, now, preset)]
        self.query_one("#watch-tides", StationTable).set_rows(tide_columns, tide_rows)

    def _focused(self) -> StationTable:
        focused = self.focused
        return focused if isinstance(focused, StationTable) else self.query_one("#watch-buoys", StationTable)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "watch-buoys" and event.row_key.value is not None:
            event.stop()
            self.eye.open_buoy(str(event.row_key.value))

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_other_table(self) -> None:
        other = "#watch-tides" if self.focused is self.query_one("#watch-buoys") else "#watch-buoys"
        self.query_one(other).focus()

    def action_add(self) -> None:
        def added(choice: SearchChoice | None) -> None:
            if choice is not None:
                self.eye.watch_in_background(choice.kind, choice.id, True)

        self.app.push_screen(SearchScreen(title="Add to the watchlist", pin_only=True), added)

    def action_remove(self) -> None:
        table = self._focused()
        key = table.current_key()
        if key is not None:
            kind = "ndbc" if table.id == "watch-buoys" else "coops"
            self.eye.watch_in_background(kind, key, False)
