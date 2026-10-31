"""The storm detail screen: one tab per product, refreshed in place as new advisories arrive."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Static, TabbedContent, TabPane

from eyewall.ui import format as fmt
from eyewall.ui import products
from eyewall.ui.theme import DIM

if TYPE_CHECKING:
    from eyewall.app import EyewallApp

# (tab id, title). Summary through Watches and warnings read the store; the three placeholders are filled by M6 and M7.
TABS: tuple[tuple[str, str], ...] = (
    ("summary", "Summary"),
    ("forecast", "Forecast"),
    ("public", "Public Advisory"),
    ("discussion", "Discussion"),
    ("probs", "Wind Probs"),
    ("ww", "Warnings"),
    ("buoys", "Buoys"),
    ("tides", "Tides"),
    ("graphics", "Graphics"),
    ("history", "History"),
)
PLACEHOLDERS = {
    "buoys": "Buoys near this storm arrive with the observations screens in 0.6.0.",
    "tides": "Tide gauges near this storm arrive with the observations screens in 0.6.0.",
    "graphics": "The graphics gallery arrives in 0.7.0.",
}
TABLE_TABS = ("forecast", "probs", "history")


class StormDetailScreen(Screen[None]):
    BINDINGS = [
        Binding("escape,backspace", "back", "Back"),
        Binding("left", "tab(-1)", "Previous tab", show=False),
        Binding("right", "tab(1)", "Next tab", show=False),
        Binding("t", "toggle_text", "TCP/TCM"),
        *[
            Binding(str((i + 1) % 10), f"show_tab('{tab_id}')", title, show=False)
            for i, (tab_id, title) in enumerate(TABS)
        ],
    ]

    def __init__(self, storm_id: str) -> None:
        super().__init__()
        self.storm_id = storm_id
        self.show_tcm = False

    @property
    def eye(self) -> EyewallApp:
        return self.app  # type: ignore[return-value]

    def compose(self) -> ComposeResult:
        yield Static("", id="detail-title")
        with TabbedContent(id="detail-tabs"):
            for tab_id, title in TABS:
                with TabPane(title, id=f"tab-{tab_id}"):
                    if tab_id in TABLE_TABS:
                        yield Static("", id=f"{tab_id}-note", classes="note")
                        yield DataTable(id=f"{tab_id}-table", zebra_stripes=True, cursor_type="row")
                    else:
                        with VerticalScroll():
                            yield Static(PLACEHOLDERS.get(tab_id, ""), id=f"{tab_id}-text", classes="detail-text")
        yield Static("", id="detail-status")

    def on_mount(self) -> None:
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

    # ---- actions ----------------------------------------------------------------------------------------------

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_tab(self, step: int) -> None:
        ids = [f"tab-{t}" for t, _ in TABS]
        tabs = self.query_one("#detail-tabs", TabbedContent)
        current = ids.index(tabs.active) if tabs.active in ids else 0
        tabs.active = ids[(current + step) % len(ids)]

    def action_show_tab(self, tab_id: str) -> None:
        self.query_one("#detail-tabs", TabbedContent).active = f"tab-{tab_id}"

    def action_toggle_text(self) -> None:
        tabs = self.query_one("#detail-tabs", TabbedContent)
        if tabs.active == "tab-public":
            self.show_tcm = not self.show_tcm
        else:
            tabs.active = "tab-public"
        self.refresh_data()
