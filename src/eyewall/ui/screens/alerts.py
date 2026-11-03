"""The alert log: every event the alert rules let through this session, newest first."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.events import Resize
from textual.widgets import DataTable, Static

from eyewall.models.events import Severity
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
    _built_keys: list[str] = []

    def on_mount(self) -> None:
        self.refresh_data()

    def on_resize(self, event: Resize) -> None:
        if self._message_width(self._rows()) != self._built_width:
            self.refresh_data()

    def _newest_first(self) -> list[Event]:
        """The log by the time of the event, newest first. The log itself is in arrival order, and a buoy reading can
        arrive after an advisory that is later than it; the sort is stable, so equal times stay newest arrival first."""
        return sorted(self.eye.alert_log, key=lambda event: event.time, reverse=True)

    @staticmethod
    def _event_cell(event: Event) -> Text:
        """The event's title. A warning is bold and starts with a mark, so under NO_COLOR, where red and amber both
        turn to grey, the urgent rows are the heaviest ones instead of the faintest."""
        if event.severity is Severity.WARNING:
            return Text(f"! {fmt.event_title(event)}", style=f"bold {fmt.SEVERITY_COLORS[event.severity]}")
        return Text(fmt.event_title(event), style=fmt.SEVERITY_COLORS[event.severity])

    def _rows(self) -> list[tuple[str, Text, str, str]]:
        return [
            (
                f"{event.time:%b %d %H:%M}",
                self._event_cell(event),
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

    def _row_keys(self) -> list[str]:
        """One key per row, in table order. Event keys can repeat, so the repeat gets its place in the log appended."""
        seen: set[str] = set()
        keys: list[str] = []
        for event in self._newest_first():
            key = event.key if event.key not in seen else f"{event.key}#{len(keys)}"
            seen.add(key)
            keys.append(key)
        return keys

    def refresh_data(self) -> None:
        """Bring the table up to date. The message column takes the width the other columns leave, and long messages
        wrap. A poll that changes nothing leaves the table alone; when rows or the width change it is rebuilt and the
        cursor stays on the same event with the scroll where it was."""
        table = self.query_one("#alert-table", DataTable)
        rows = self._rows()
        keys = self._row_keys()
        width = self._message_width(rows)
        empty = self.query_one("#alert-empty", Static)
        empty.update("No alerts yet this session.")
        empty.display = not self.eye.alert_log
        if width == self._built_width and keys == self._built_keys:
            return
        old_keys, row, scroll = self._built_keys, table.cursor_row, table.scroll_y
        kept = old_keys[row] if row < len(old_keys) else None
        self._built_width, self._built_keys = width, keys
        table.clear(columns=True)
        for header, column_width in zip(self.HEADERS, (*self._fixed_widths(rows), width), strict=True):
            table.add_column(header, width=column_width)
        for key, (time, title, storm, message) in zip(keys, rows, strict=True):
            table.add_row(time, title, storm, Text(message), height=None, key=key)
        if kept in keys:
            table.move_cursor(row=keys.index(kept), animate=False)
        elif keys:
            table.move_cursor(row=min(row, len(keys) - 1), animate=False)
        table.call_after_refresh(table.scroll_to, y=scroll, animate=False, immediate=True)
