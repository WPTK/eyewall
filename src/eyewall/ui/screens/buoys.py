"""The Buoys and gauges screen: the stations near the selected storm, and the stations you follow."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.css.query import NoMatches
from textual.widgets import OptionList, Static, Tab, Tabs

from eyewall.palette import DIM
from eyewall.sources import protocol
from eyewall.ui import nav, station_view
from eyewall.ui.chrome import ChromeScreen, FooterBar, TopBar
from eyewall.ui.widgets.station_list import StationList

NEAR, YOURS = "near", "yours"


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


class BuoysScreen(ChromeScreen):
    CRUMB = "Buoys and gauges"
    NAV_SCOPES = ("buoys",)
    BINDINGS = nav.bindings("buoys")

    def __init__(self, storm_id: str | None, tab: str | None = None) -> None:
        super().__init__()
        self.storm_id = storm_id
        self.tab = YOURS if storm_id is None or tab == YOURS else NEAR
        self.sort_index = 0

    @property
    def tab_ids(self) -> list[str]:
        return [NEAR, YOURS] if self.storm_id is not None else [YOURS]

    def compose(self) -> ComposeResult:
        yield TopBar()
        tabs = [Tab(self._near_label(), id=f"t-{NEAR}")] if self.storm_id is not None else []
        yield Tabs(*tabs, Tab("Your stations", id=f"t-{YOURS}"), active=f"t-{self.tab}", id="buoys-tabs")
        yield Static("", id="buoys-head")
        yield StationList(id="buoys-list")
        yield Static("", id="buoys-empty")
        yield FooterBar()

    def on_mount(self) -> None:
        self.query_one(StationList).focus()
        self.refresh_data()

    def _near_label(self) -> str:
        state = self.eye.store.storms.get(self.storm_id or "")
        return f"Near {state.storm.name.title()}" if state is not None and state.storm.name else "Near the storm"

    # ---- data -------------------------------------------------------------------------------------------------

    def refresh_data(self) -> None:
        eye = self.eye
        store, now, preset, g, tz = eye.store, eye.now(), eye.preset, eye.glyphs, eye.local_tz
        ascii_ = eye.config.map.glyph_set == "ascii"
        mode = station_view.SORTS[self.sort_index]
        failed = eye.poller.freshness(protocol.BUOYS).state.value == "error"
        if self.tab == NEAR:
            storm = store.storms.get(self.storm_id or "")
            rows = station_view.near_rows(store, self.storm_id or "", now, preset, g, tz, ascii_) if storm else []
            buoys = sum(1 for r in rows if r.kind == station_view.BUOY)
            gauges = len(rows) - buoys
            name = storm.storm.name.title() if storm is not None and storm.storm.name else "the storm"
            if storm is None:
                head = f"{(self.storm_id or '').upper()} is no longer active."
            elif rows:
                parts = [_plural(buoys, "buoy")] if buoys else []
                if gauges:
                    parts.append(_plural(gauges, "tide gauge"))
                head = f"{' and '.join(parts)} near {name}."
            else:
                head = f"No buoys or tide gauges are near {name}."
            empty = ""
        else:
            rows = station_view.followed_rows(store, now, preset, g, tz, ascii_)
            if rows:
                head = f"You follow {_plural(len(rows), 'station')}."
                empty = ""
            else:
                head = "You are not following any stations."
                empty = "Open a buoy or tide gauge and press f to follow it. Press / to find one by name or number."
        if rows:
            head += f" Sorted by {mode}. * means you follow it."
            if failed:
                head += " Buoy data unavailable."
        ordered = station_view.sort_rows(rows, mode)
        self.query_one(StationList).set_rows(ordered, preset)
        self.query_one(StationList).display = bool(ordered)
        self.query_one("#buoys-head", Static).update(Text(head, style="bold"))
        empty_note = self.query_one("#buoys-empty", Static)
        empty_note.display = bool(empty)
        empty_note.update(Text(empty, style=DIM))
        self._label_tabs(len(station_view.followed_rows(store, now, preset, g, tz, ascii_)))
        self.refresh_bindings()

    def _label_tabs(self, followed: int) -> None:
        try:
            self.query_one(f"#t-{YOURS}", Tab).label = f"Your stations ({followed})"
            if self.storm_id is not None:
                self.query_one(f"#t-{NEAR}", Tab).label = self._near_label()
        except Exception:  # a tab being rebuilt; the next refresh labels it
            return

    # ---- events and actions -----------------------------------------------------------------------------------

    def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        event.stop()
        tab = (event.tab.id or "").removeprefix("t-")
        if tab in self.tab_ids and tab != self.tab:
            self.tab = tab
            self.refresh_data()
        self.query_one(StationList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        key = event.option.id or ""
        kind, _, station_id = key.partition(":")
        if station_id:
            self.eye.open_station(kind, station_id)

    def check_action(self, action: str, _parameters: tuple[object, ...]) -> bool | None:
        if action == "switch":
            return len(self.tab_ids) > 1
        if action in ("follow", "sort"):
            try:
                return bool(self.query_one(StationList).rows)
            except NoMatches:
                return False
        return True

    def action_switch(self) -> None:
        ids = self.tab_ids
        new = ids[(ids.index(self.tab) + 1) % len(ids)]
        self.query_one(Tabs).active = f"t-{new}"

    def action_sort(self) -> None:
        self.sort_index = (self.sort_index + 1) % len(station_view.SORTS)
        self.refresh_data()
        self.notify(f"Sorted by {station_view.SORTS[self.sort_index]}.", timeout=2)

    def action_follow(self) -> None:
        row = self.query_one(StationList).current_row()
        if row is None:
            self.notify("Highlight a station first.", timeout=3)
            return
        self.eye.watch_in_background(row.kind, row.id, not row.followed)

    def action_search(self) -> None:
        self.eye.action_search()
