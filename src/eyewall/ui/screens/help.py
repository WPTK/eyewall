"""The help screen: every key, grouped by where it works."""

from __future__ import annotations

from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

HELP: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "Dashboard",
        (
            ("j k  Enter", "previous or next storm; open its detail"),
            ("Tab", "move between the list, the map and the panels"),
            ("1 2 3 a", "Atlantic, East Pacific, Central Pacific, all"),
            ("m  M", "map on or off; full-screen map"),
            ("+ -  arrows  c f", "zoom, pan, center on the storm, fit the cone"),
            ("l  b  g", "map layers; buoys; graphics"),
        ),
    ),
    (
        "Storm detail",
        (
            ("Left Right  1-0", "previous or next tab; jump to a tab"),
            ("t", "on the Advisory tab: public or forecast advisory"),
            ("Enter  p", "open a buoy's charts; pin or unpin a station"),
            ("h  i", "in the charts: range; charts or observation"),
            ("Esc", "back"),
        ),
    ),
    (
        "Anywhere",
        (
            ("O  w  /", "outlook; watchlist; find a station (Ctrl+P pins)"),
            ("S  A", "settings; alert log"),
            ("r  u", "refresh now; cycle units"),
            ("? q", "help; quit"),
        ),
    ),
    (
        "Replay",
        (("space  < >  [ ]", "pause; slower or faster; previous or next advisory"),),
    ),
)


def help_text() -> Table:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold #ffa63d", no_wrap=True)
    table.add_column()
    for title, keys in HELP:
        table.add_row(Text(title, style="bold #8fd3ff"), Text(""))
        for key, text in keys:
            table.add_row(key, text)
    return table


class HelpScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape,question_mark,q", "close", "Close")]

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help-box"):
            yield Static(help_text())

    def action_close(self) -> None:
        self.dismiss()
