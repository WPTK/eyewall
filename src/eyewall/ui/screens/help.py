"""The help screen: every key, grouped by where it works."""

from __future__ import annotations

from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from eyewall.palette import ACCENT, FRESHNESS_CUES, HEADING
from eyewall.ui import nav


def top_bar_notes() -> tuple[tuple[str, str], ...]:
    """What the health slot in the top bar can say, with the glyphs it uses."""
    cues = FRESHNESS_CUES
    return (
        (f"{cues['fresh'].glyph} data ok 3m", "every feed is current; the age is the storms feed's"),
        (f"{cues['stale'].glyph} 2 feeds late", "some feeds are older than they should be"),
        (f"{cues['error'].glyph} 2 feeds failing", "a feed could not be fetched; the rest keep polling"),
        (f"{cues['error'].glyph} offline, cached", "showing saved data until the network returns"),
        (f"{cues['loading'].glyph} checking", "the first fetch has not finished"),
        ("click it, or D", "the list of feeds, their ages and the next refresh"),
    )


NOT_OFFICIAL = (
    "eyewall is not an official forecast or warning. For decisions about life or property, "
    "follow the National Hurricane Center and your local emergency officials."
)


def help_text() -> Table:
    table = Table.grid(padding=(0, 2))
    table.add_column(style=f"bold {ACCENT}", no_wrap=True)
    table.add_column()
    for title, rows in [*nav.help_rows(), ("Top bar", top_bar_notes())]:
        table.add_row(Text(title, style=f"bold {HEADING}"), Text(""))
        for key, text in rows:
            table.add_row(key, text)
    table.add_row(Text(""), Text(""))
    table.add_row(Text("Not official", style=f"bold {HEADING}"), Text(""))
    table.add_row("", NOT_OFFICIAL)
    return table


class HelpScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape,question_mark", "close", "Close")]

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help-box"):
            yield Static(help_text())

    def action_close(self) -> None:
        self.dismiss()
