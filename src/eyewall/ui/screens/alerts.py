"""The alert log: every event the alert rules let through this session, newest first."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.events import Resize
from textual.widgets import DataTable, Static

from eyewall.ui import format as fmt
from eyewall.ui import nav
from eyewall.ui.chrome import ChromeScreen, FooterBar, TopBar

if TYPE_CHECKING:
    from eyewall.models.events import Event


class AlertLogScreen(ChromeScreen):
    CRUMB = "Alerts"
    NAV_SCOPES = ("alerts",)
    BINDINGS = nav.bindings("alerts")

    def compose(self) -> ComposeResult:
        yield TopBar()
        yield DataTable(id="alert-table", zebra_stripes=True, cursor_type="row")
        yield Static("", id="alert-empty")
        yield FooterBar()

    HEADERS = ("Time (Z)", "Event", "Storm", "Message")
    _built_width: int | None = None

    def on_mount(self) -> None:
        self.refresh_data()

    def on_resize(self, event: Resize) -> None:
        if self._message_width(self._rows()) != self._built_width:
            self.refresh_data()

    def _newest_first(self) -> list[Event]:
        """The log by the time of the event, newest first. The log itself is in arrival order, and a buoy reading can
        arrive after an advisory that is later than it; the sort is stable, so equal times stay newest arrival first."""
        return sorted(self.eye.alert_log, key=lambda event: event.time, reverse=True)

    def _rows(self) -> list[tuple[str, Text, str, str]]:
        return [
            (
                f"{event.time:%b %d %H:%M}",
                Text(fmt.event_title(event), style=fmt.SEVERITY_COLORS[event.severity]),
                (event.storm_id or "--").upper(),
                event.message,
            )
            for event in self._newest_first()
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
        empty = self.query_one("#alert-empty", Static)
        empty.update("No alerts yet this session.")
        empty.display = not self.eye.alert_log
