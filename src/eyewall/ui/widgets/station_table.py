"""A table of stations keyed by id: rebuilt only when its text changes, and the cursor stays on the same station."""

from __future__ import annotations

from collections.abc import Sequence

from rich.cells import cell_len
from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.widgets import DataTable

NAME = "Name"
NAME_MIN = 10  # the Name column never shrinks below this; past it the table scrolls sideways
NAME_MAX = 48
PADDING = 2  # a column's cell padding, both sides


def _cut(cell: Text, width: int) -> Text:
    text = cell.plain
    if cell_len(text) <= width:
        return cell
    return Text(text[: max(1, width - 1)] + "…", style=cell.style)


class StationTable(DataTable[Text]):
    """Rows are keyed by station id. The Name column takes the width the other columns leave (between `NAME_MIN` and
    `NAME_MAX`) and cuts a longer name with an ellipsis, so the table fits its area at every terminal size.
    `set_rows` compares the new text with what is shown and does nothing when it is the same (units, ages and values
    that did not change), so a poll that changes nothing costs nothing and never moves the cursor; when it does change,
    the cursor follows the station it was on."""

    BINDINGS = [Binding("enter", "select_cursor", "charts")]

    def __init__(self, *, id: str | None = None, charts: bool = True) -> None:
        super().__init__(id=id, zebra_stripes=True, cursor_type="row")
        self.charts = charts  # Enter opens a buoy's charts; a gauge row has nothing to open
        self._signature: object = None
        self._keys: list[str] = []
        self._columns: tuple[str, ...] = ()
        self._rows: tuple[tuple[str, tuple[Text, ...]], ...] = ()
        self._name_width: int | None = None

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
        self._columns, self._rows = tuple(columns), tuple(rows)
        self._name_width = self._fit()
        self._build()

    def on_resize(self, event: events.Resize) -> None:
        width = self._fit()
        if width != self._name_width and self._rows:
            self._name_width = width
            self._build()

    def _fit(self) -> int | None:
        """The Name column's width: what is left of the table's width after the other columns, within its limits."""
        if NAME not in self._columns or self.size.width < 1:
            return None
        at = self._columns.index(NAME)
        others = 0
        for index, label in enumerate(self._columns):
            if index != at:
                cells = (cell_len(cells[index].plain) for _, cells in self._rows)
                others += max(cell_len(label), *cells, 0) + PADDING
        longest = max((cell_len(cells[at].plain) for _, cells in self._rows), default=0)
        room = self.size.width - others - PADDING
        return min(max(longest, len(NAME)), max(NAME_MIN, min(room, NAME_MAX)))  # never wider than the longest name

    def _build(self) -> None:
        keep = self.current_key()
        at = self._columns.index(NAME) if NAME in self._columns else None
        width = self._name_width
        self.clear(columns=True)
        for index, label in enumerate(self._columns):
            self.add_column(label, width=width if index == at and width is not None else None)
        for key, cells in self._rows:
            if at is not None and width is not None:
                cells = (*cells[:at], _cut(cells[at], width), *cells[at + 1 :])
            self.add_row(*cells, key=key)
        self._keys = [key for key, _ in self._rows]
        if keep in self._keys:
            self.move_cursor(row=self._keys.index(keep), animate=False)
        elif self._keys:
            self.move_cursor(row=min(self.cursor_row, len(self._keys) - 1), animate=False)
