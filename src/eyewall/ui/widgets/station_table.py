"""A table of stations keyed by id: rebuilt only when its text changes, and the cursor stays on the same station."""

from __future__ import annotations

from collections.abc import Sequence

from rich.text import Text
from textual.binding import Binding
from textual.widgets import DataTable


class StationTable(DataTable[Text]):
    """Rows are keyed by station id. `set_rows` compares the new text with what is shown and does nothing when it is the
    same (units, ages and values that did not change), so a poll that changes nothing costs nothing and never moves the
    cursor; when it does change, the cursor follows the station it was on."""

    BINDINGS = [Binding("enter", "select_cursor", "charts")]

    def __init__(self, *, id: str | None = None, charts: bool = True) -> None:
        super().__init__(id=id, zebra_stripes=True, cursor_type="row")
        self.charts = charts  # Enter opens a buoy's charts; a gauge row has nothing to open
        self._signature: object = None
        self._keys: list[str] = []

    def check_action(self, action: str, _parameters: tuple[object, ...]) -> bool | None:
        return self.charts or action != "select_cursor"

    @property
    def keys(self) -> list[str]:
        return list(self._keys)

    def current_key(self) -> str | None:
        """The id of the station under the cursor, or None for an empty table."""
        if not self._keys:
            return None
        row = self.cursor_row
        return self._keys[row] if 0 <= row < len(self._keys) else None

    def set_rows(self, columns: Sequence[str], rows: Sequence[tuple[str, tuple[Text, ...]]]) -> None:
        signature = (tuple(columns), tuple((key, tuple((c.plain, str(c.style)) for c in cells)) for key, cells in rows))
        if signature == self._signature:
            return
        self._signature = signature
        keep = self.current_key()
        self.clear(columns=True)
        self.add_columns(*columns)
        for key, cells in rows:
            self.add_row(*cells, key=key)
        self._keys = [key for key, _ in rows]
        if keep in self._keys:
            self.move_cursor(row=self._keys.index(keep), animate=False)
        elif self._keys:
            self.move_cursor(row=min(self.cursor_row, len(self._keys) - 1), animate=False)
