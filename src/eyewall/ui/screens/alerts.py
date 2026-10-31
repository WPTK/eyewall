"""The alert log: every event the alert rules let through this session, newest first."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Static

from eyewall.ui import format as fmt

if TYPE_CHECKING:
    from eyewall.app import EyewallApp


class AlertLogScreen(Screen[None]):
    BINDINGS = [Binding("escape,A", "back", "Back")]

    @property
    def eye(self) -> EyewallApp:
        return self.app  # type: ignore[return-value]

    def compose(self) -> ComposeResult:
        yield DataTable(id="alert-table", zebra_stripes=True, cursor_type="row")
        yield Static("", id="alert-empty")

    def on_mount(self) -> None:
        self.query_one("#alert-table", DataTable).add_columns("Time (Z)", "Event", "Storm", "Message")
        self.refresh_data()

    def refresh_data(self) -> None:
        table = self.query_one("#alert-table", DataTable)
        table.clear()
        log = self.eye.alert_log
        for event in log:
            storm = (event.storm_id or "--").upper()
            title = Text(fmt.event_title(event), style=fmt.SEVERITY_COLORS[event.severity])
            table.add_row(f"{event.time:%b %d %H:%M}", title, storm, event.message)
        self.query_one("#alert-empty", Static).update("" if log else "No alerts yet this session.")

    def action_back(self) -> None:
        self.app.pop_screen()
