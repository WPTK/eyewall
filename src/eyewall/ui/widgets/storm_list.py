"""The storm list: rows grouped by basin, with headers and quiet rows that cannot be picked."""

from __future__ import annotations

from textual.binding import Binding
from textual.message import Message
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from eyewall.ui.format import Row


class StormList(OptionList):
    """Cyclones, PTCs and invests per basin. Highlighting a row selects it; Enter on a storm opens its detail."""

    BINDINGS = [Binding("enter", "select", "detail")]  # the screen opens the detail on the selection

    class Picked(Message):
        """The highlighted row changed to a storm, PTC or invest."""

        def __init__(self, row_id: str) -> None:
            super().__init__()
            self.row_id = row_id

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._rows: list[Row] = []
        self._signature: tuple[tuple[str, str], ...] = ()
        self._current: str | None = None  # the row the app already treats as selected

    @property
    def rows(self) -> list[Row]:
        return self._rows

    def row_at(self, index: int | None) -> Row | None:
        return self._rows[index] if index is not None and 0 <= index < len(self._rows) else None

    @property
    def highlighted_row(self) -> Row | None:
        return self.row_at(self.highlighted)

    def set_rows(self, rows: list[Row], selected: str | None) -> str | None:
        """Show the rows, keep `selected` highlighted if it is still there, and return the id that ends up selected.

        Nothing is rebuilt when the text is unchanged, so a poll that brings nothing new does not move the cursor.
        """
        signature = tuple((r.id, r.text.plain) for r in rows)
        if signature != self._signature:
            self._signature = signature
            self._rows = rows
            self.clear_options()
            self.add_options([Option(r.text, id=r.id, disabled=not r.selectable) for r in rows])
        return self._restore(selected)

    def _restore(self, selected: str | None) -> str | None:
        ids = [r.id for r in self._rows]
        if selected in ids and self._rows[ids.index(selected)].selectable:
            target: int | None = ids.index(selected)
        else:
            target = next((i for i, r in enumerate(self._rows) if r.selectable), None)
        if target is not None and self.highlighted != target:
            self.highlighted = target
        # Textual delivers the highlight events of a rebuild later, so they cannot be told apart by a flag. The handler
        # instead ignores any highlight that lands on the row already selected.
        self._current = None if target is None else ids[target]
        return self._current

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        row = self.row_at(event.option_index)
        if row is not None and row.selectable and row.id != self._current:
            self._current = row.id
            self.post_message(self.Picked(row.id))
