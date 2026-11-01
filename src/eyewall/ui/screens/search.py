"""Station search: type part of an id or a name and pick a buoy or a tide gauge from the two catalogs.

Enter picks the highlighted station (the caller decides what that means: open a buoy's charts, or pin a station to
the watchlist), Ctrl+P pins it whatever the caller does, Esc leaves.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from eyewall.palette import ACCENT, DIM
from eyewall.ui import stations as st

if TYPE_CHECKING:
    from eyewall.app import EyewallApp


@dataclass(frozen=True, slots=True)
class SearchChoice:
    kind: str
    id: str
    pin: bool


class SearchScreen(ModalScreen[SearchChoice | None]):
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("down", "move(1)", "Next", show=False, priority=True),
        Binding("up", "move(-1)", "Previous", show=False, priority=True),
        Binding("ctrl+p", "pin", "Pin", show=False, priority=True),
    ]

    def __init__(self, *, title: str = "Find a station", pin_only: bool = False) -> None:
        super().__init__()
        self._title = title
        self.pin_only = pin_only
        self.hits: list[st.Hit] = []

    @property
    def eye(self) -> EyewallApp:
        return self.app  # type: ignore[return-value]

    def compose(self) -> ComposeResult:
        with Vertical(id="search-box"):
            yield Input(placeholder="id or name: 41010, canaveral, duck", id="search-input")
            yield OptionList(id="search-results")
            yield Static("", id="search-note")

    def on_mount(self) -> None:
        box = self.query_one("#search-box")
        box.border_title = self._title
        box.border_subtitle = "enter picks, ctrl+p pins, esc closes"
        self.query_one("#search-input", Input).focus()
        store = self.eye.store
        if not store.stations or not store.tide_stations:
            self.query_one("#search-note", Static).update(Text("Loading the station catalogs...", style=DIM))
            self.run_worker(self._load_catalogs(), name="catalogs", exit_on_error=False)
        else:
            self._show()

    async def _load_catalogs(self) -> None:
        failed = await self.eye.ensure_catalogs()
        self._show(failed)

    def _show(self, failed: bool = False) -> None:
        store = self.eye.store
        query = self.query_one("#search-input", Input).value
        self.hits = st.search_stations(store, query)
        results = self.query_one("#search-results", OptionList)
        results.clear_options()
        for hit in self.hits:
            line = Text(no_wrap=True, overflow="ellipsis")
            line.append(f"{st.KIND_LABELS[hit.kind]:<5}", style=DIM)
            line.append(f"{hit.id:<9}", style="bold")
            line.append(hit.name or "(no name)")
            if hit.detail:
                line.append(f"  {hit.detail}", style=DIM)
            results.add_option(Option(line, id=f"{hit.kind}:{hit.id}"))
        if self.hits:
            results.highlighted = 0
        note = self.query_one("#search-note", Static)
        if failed:
            note.update(Text("The station catalogs could not be loaded; try again in a moment.", style=ACCENT))
        elif not query.strip():
            note.update(Text(f"{len(store.stations)} buoys and {len(store.tide_stations)} tide gauges.", style=DIM))
        elif not self.hits:
            note.update(Text("No station matches.", style=DIM))
        else:
            note.update(Text(f"{len(self.hits)} found.", style=DIM))

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        self._show()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self._choose(pin=self.pin_only)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self._choose(pin=self.pin_only)

    def _choose(self, *, pin: bool) -> None:
        index = self.query_one("#search-results", OptionList).highlighted
        if index is None or not 0 <= index < len(self.hits):
            return
        hit = self.hits[index]
        self.dismiss(SearchChoice(hit.kind, hit.id, pin))

    def action_move(self, step: int) -> None:
        results = self.query_one("#search-results", OptionList)
        if step > 0:
            results.action_cursor_down()
        else:
            results.action_cursor_up()

    def action_pin(self) -> None:
        self._choose(pin=True)

    def action_cancel(self) -> None:
        self.dismiss(None)
