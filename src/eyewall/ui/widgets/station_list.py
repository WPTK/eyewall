"""The list of stations on the Buoys and gauges screen: two lines each, Enter or a click opens one."""

from __future__ import annotations

from collections.abc import Sequence

from textual import events
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from eyewall.ui import nav
from eyewall.ui.station_view import Row, row_text
from eyewall.units import Preset


class StationList(OptionList):
    """Rows come from `set_rows`; an option's id is the row's key (`ndbc:41047`)."""

    NAV_SCOPES = ("stations",)
    BINDINGS = nav.bindings("stations")

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._rows: list[Row] = []
        self._preset: Preset | None = None

    @property
    def rows(self) -> list[Row]:
        return self._rows

    def current_row(self) -> Row | None:
        index = self.highlighted
        return self._rows[index] if index is not None and 0 <= index < len(self._rows) else None

    def current_key(self) -> str | None:
        row = self.current_row()
        return None if row is None else row.key

    def set_rows(self, rows: Sequence[Row], preset: Preset) -> None:
        """Replace the rows, keeping the highlight on the same station when it is still there."""
        keep = self.current_key()
        self._rows, self._preset = list(rows), preset
        self._fill(keep)

    def _fill(self, keep: str | None = None) -> None:
        preset = self._preset
        width = max(self.size.width - 2 - self.scrollbar_size_vertical, 20)
        self.clear_options()
        if preset is None:
            return
        self.add_options([Option(row_text(r, width, preset), id=r.key) for r in self._rows])
        if self._rows:
            keys = [r.key for r in self._rows]
            self.highlighted = keys.index(keep) if keep in keys else 0

    def on_resize(self, event: events.Resize) -> None:
        self._fill(self.current_key())
