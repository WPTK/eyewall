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

    HEADERS = ("Time (Z)", "Event", "Storm", "Message")
    _built_width: int | None = None

    def on_mount(self) -> None:
        self.refresh_data()

    def on_resize(self, event: Resize) -> None:
        if self._message_width(self._rows()) != self._built_width:
            self.refresh_data()

    def _rows(self) -> list[tuple[str, Text, str, str]]:
        return [
            (
                f"{event.time:%b %d %H:%M}",
                Text(fmt.event_title(event), style=fmt.SEVERITY_COLORS[event.severity]),
                (event.storm_id or "--").upper(),
                event.message,
            )
            for event in self.eye.alert_log
        ]

    def _fixed_widths(self, rows: list[tuple[str, Text, str, str]]) -> list[int]:
        return [max([len(self.HEADERS[i])] + [len(str(row[i])) for row in rows]) for i in range(3)]

    def _message_width(self, rows: list[tuple[str, Text, str, str]]) -> int:
        """What the other columns leave: a cell of padding either side of each, and one column for the scrollbar."""
        return max(20, self.size.width - sum(self._fixed_widths(rows)) - 2 * len(self.HEADERS) - 1)

    def refresh_data(self) -> None:
        """Rebuild the table. The message column takes the width the other columns leave, and long messages wrap."""
        table = self.query_one("#alert-table", DataTable)
        rows = self._rows()
        self._built_width = self._message_width(rows)
        table.clear(columns=True)
        for header, width in zip(self.HEADERS, (*self._fixed_widths(rows), self._built_width), strict=True):
            table.add_column(header, width=width)
        for time, title, storm, message in rows:
            table.add_row(time, title, storm, Text(message), height=None)
        self.query_one("#alert-empty", Static).update("" if self.eye.alert_log else "No alerts yet this session.")

    def action_back(self) -> None:
        self.app.pop_screen()
