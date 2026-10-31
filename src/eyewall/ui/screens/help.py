"""The help screen: every key, grouped by where it works."""

from __future__ import annotations

from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from eyewall.ui.theme import DIM

HELP: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "Dashboard",
        (
            ("j / k", "next and previous storm in the list, wherever the focus is"),
            ("Enter", "open the storm detail"),
            ("Tab", "move between the list, the map and the panels"),
            ("1  2  3  a", "Atlantic, East Pacific, Central Pacific, all basins"),
            ("m", "show or hide the map (below 90 columns it replaces the panels)"),
            ("M", "full-screen map"),
            ("l", "choose the map layers"),
            ("+  -", "zoom in and out (the mouse wheel too)"),
            ("arrows", "pan the map once it has focus (click it, or Tab to it); on the list they move the cursor"),
            ("c  f", "center on the storm; fit the cone again"),
        ),
    ),
    (
        "Storm detail",
        (
            ("Left / Right", "previous and next tab"),
            ("1 ... 9  0", "jump to a tab"),
            ("t", "on the advisory tab, switch between the public advisory and the forecast advisory"),
            ("Esc", "back to the dashboard"),
        ),
    ),
    (
        "Anywhere",
        (
            ("O", "outlook: the text, the areas and the watchlist"),
            ("A", "alert log"),
            ("r", "refresh every feed now"),
            ("u", "cycle the units: nautical, us, metric"),
            ("?", "this help"),
            ("q", "quit"),
        ),
    ),
    (
        "Replay",
        (
            ("space", "pause and resume"),
            ("<  >", "slower and faster"),
            ("[  ]", "previous and next advisory"),
        ),
    ),
)


def help_text() -> Table:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold #ffa63d", no_wrap=True)
    table.add_column()
    for title, keys in HELP:
        table.add_row(Text(""), Text(""))
        table.add_row(Text(title, style="bold #8fd3ff"), Text(""))
        for key, text in keys:
            table.add_row(key, text)
    return table


class HelpScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape,question_mark,q", "close", "Close")]

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help-box"):
            yield Static(help_text())
            yield Static(Text("\nEsc closes this window.", style=DIM))

    def action_close(self) -> None:
        self.dismiss()
