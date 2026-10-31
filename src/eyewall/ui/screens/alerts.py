"""The alert log: every event the alert rules let through this session, newest first."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.events import Resize
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
        self.refresh_data()

    def on_resize(self, event: Resize) -> None:
        self.refresh_data()

    def refresh_data(self) -> None:
        """Rebuild the table. The message column takes the width the other columns leave, and long messages wrap."""
        table = self.query_one("#alert-table", DataTable)
        log = self.eye.alert_log
        rows = [
            (
                f"{event.time:%b %d %H:%M}",
                Text(fmt.event_title(event), style=fmt.SEVERITY_COLORS[event.severity]),
                (event.storm_id or "--").upper(),
                event.message,
            )
            for event in log
        ]
        headers = ("Time (Z)", "Event", "Storm", "Message")
        fixed = [max([len(headers[i])] + [len(str(row[i])) for row in rows]) for i in range(3)]
        # Each column has a cell of padding either side; the scrollbar takes one more column.
        message_width = max(20, self.size.width - sum(fixed) - 2 * len(headers) - 1)
        table.clear(columns=True)
        for header, width in zip(headers, (*fixed, message_width), strict=True):
            table.add_column(header, width=width)
        for time, title, storm, message in rows:
            table.add_row(time, title, storm, Text(message), height=None)
        self.query_one("#alert-empty", Static).update("" if log else "No alerts yet this session.")

    def action_back(self) -> None:
        self.app.pop_screen()
