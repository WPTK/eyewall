"""The feed list: each feed's health, its age and the next refresh. The top bar's health slot, or `D`, opens it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from eyewall.clock import format_age
from eyewall.palette import DIM, FRESHNESS_CUES, HEADING
from eyewall.poll import FreshnessState
from eyewall.sources import protocol
from eyewall.ui.chrome import FEED_LABELS

if TYPE_CHECKING:
    from eyewall.app import EyewallApp


def feeds_text(app: EyewallApp) -> Table:
    g = app.glyphs
    glyphs = {
        FreshnessState.FRESH: g.fresh,
        FreshnessState.STALE: g.stale,
        FreshnessState.ERROR: g.error,
        FreshnessState.LOADING: g.loading,
    }
    table = Table.grid(padding=(0, 2))
    for _ in range(4):
        table.add_column(no_wrap=True)
    for feed in protocol.FEEDS:
        fresh = app.poller.freshness(feed)
        label = FEED_LABELS[feed]
        if not app.poller.active(feed):
            table.add_row(Text(f"  {label}", style=DIM), Text("not polled now", style=DIM), "", "")
            continue
        cue = FRESHNESS_CUES[fresh.state.value]
        word = "cached" if fresh.from_cache else cue.word
        table.add_row(
            Text(f"{glyphs[fresh.state]} {label}", style=cue.style()),
            Text(word, style=cue.style()),
            Text(f"{format_age(fresh.age)} old" if fresh.age is not None else "no data yet", style=DIM),
            Text(fresh.error or "", style=DIM),
        )
    notes = Text()
    wait = app.poller.seconds_until_next()
    if wait is not None:
        notes.append(f"Next refresh in {format_age(wait)}.\n", style=DIM)
    if app.poller.away:
        notes.append(
            "Idle: no keys or mouse for a while, so the feeds poll more slowly until you touch one.\n", style=DIM
        )
    if app.alert_log:
        notes.append(f"{len(app.alert_log)} alerts this session; A opens the alert log.\n", style=DIM)
    out = Table.grid()
    out.add_column()
    out.add_row(Text("Feeds", style=f"bold {HEADING}"))
    out.add_row(table)
    out.add_row(notes)
    return out


class FeedsScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape,D", "close", "Close")]

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="feeds-box"):
            yield Static(feeds_text(self.app), id="feeds-text")  # type: ignore[arg-type]

    def refresh_status(self) -> None:
        self.query_one("#feeds-text", Static).update(feeds_text(self.app))  # type: ignore[arg-type]

    def action_close(self) -> None:
        self.dismiss()
