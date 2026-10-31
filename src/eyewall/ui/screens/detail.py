"""The storm detail screen: one tab per product, refreshed in place as new advisories arrive."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import RenderableType
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.css.query import NoMatches
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
        Binding("left", "tab(-1)", "Previous tab", show=False, priority=True),
        Binding("right", "tab(1)", "Next tab", show=False, priority=True),
        Binding("t", "toggle_text", "tcp/tcm"),
        Binding("p", "pin", "pin"),
        Binding("escape,backspace", "back", "back"),
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
                        yield StationTable(id=f"{tab_id}-table", charts=tab_id == "buoys")
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
        self.call_after_refresh(self._focus_active_pane)

    def _focus_active_pane(self) -> None:
        tabs = self.query_one("#detail-tabs", TabbedContent)
        if tabs.active and not isinstance(self.focused, DataTable | VerticalScroll | OptionList):
            self._focus_pane(tabs.get_pane(tabs.active))

    # ---- data -------------------------------------------------------------------------------------------------

    def refresh_status(self) -> None:
        self.query_one("#detail-status", Static).update(self.eye.status_text(self.size.width, self))

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

    def _set_text(self, tab_id: str, text: RenderableType) -> None:
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
                f"{preset.fmt_distance(nearby.radius_track_nm)} of the track. * = watchlist.",
                style=DIM,
            )
        )
        gauges = st.from_nearby(store.nearby_tides(self.storm_id))
        self.query_one("#tides-table", StationTable).set_rows(st.TIDE_COLUMNS, st.tide_rows(store, gauges, now, preset))
        self.query_one("#tides-note", Static).update(
            Text(
                f"{len(gauges)} gauges near the storm. Residual = observed minus predicted: the surge estimate. "
                "* = watchlist.",
                style=DIM,
            )
        )

    # ---- actions ----------------------------------------------------------------------------------------------

    def action_back(self) -> None:
        self.app.pop_screen()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Keys that do something on one tab only are off, and so out of the footer, on the others."""
        try:
            tabs = self.query_one("#detail-tabs", TabbedContent)
        except NoMatches:  # a key pressed while the screen is still being built
            return True
        tab = (tabs.active or "").removeprefix("tab-")
        if action == "toggle_text":
            return tab == "public"
        if action == "pin":
            return tab in STATION_TABS
        if action == "tab" and parameters:
            return not self._table_can_scroll(
                1 if parameters[0] == 1 else -1
            )  # sideways first, then on to the next tab
        return True

    def _table_can_scroll(self, step: int) -> bool:
        """Whether the focused table has columns off screen in the direction of `step`, so the arrow should scroll."""
        table = self.focused
        if not isinstance(table, DataTable):
            return False
        return table.scroll_x < table.max_scroll_x if step > 0 else table.scroll_x > 0

    def action_tab(self, step: int) -> None:
        ids = [f"tab-{t}" for t, _ in TABS]
        tabs = self.query_one("#detail-tabs", TabbedContent)
        current = ids.index(tabs.active) if tabs.active in ids else 0
        tabs.active = ids[(current + step) % len(ids)]

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        """Land the focus on the tab's table, so the arrows and Enter act on its rows straight away."""
        self.query_one("#graphics-gallery", GalleryPanel).set_active(event.pane.id == "tab-graphics")
        self._focus_pane(event.pane)

    def _focus_pane(self, pane: TabPane) -> None:
        """The gallery's list, or the pane's table or text, whichever it has: the arrows scroll it at once."""
        if pane.id == "tab-graphics":
            pane.query_one(OptionList).focus()
            return
        for content in pane.query("DataTable, VerticalScroll"):
            content.focus()
            return

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
        kind = STATION_TABS[tab_id]
        key = self.query_one(f"#{tab_id}-table", StationTable).current_key()
        if key is not None:
            self.eye.watch_in_background(kind, key, key.upper() not in watchlist_ids(self.eye.config, kind))

    def action_show_tab(self, tab_id: str) -> None:
        self.query_one("#detail-tabs", TabbedContent).active = f"tab-{tab_id}"

    def action_toggle_text(self) -> None:
        self.show_tcm = not self.show_tcm
        self.refresh_data()
