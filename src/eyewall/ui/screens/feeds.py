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


def _detail(app: EyewallApp, feed: str) -> str:
    """What to say beside a feed's state, in plain words: how old it is, or why it failed and when it will try again."""
    fresh = app.poller.freshness(feed)
    if fresh.state is FreshnessState.ERROR:
        retry = f"retrying in {format_age(app.poller.seconds_until(feed))}"
        reason = fresh.reason or "the feed could not be read"
        return f"{reason}, {retry}" + (f"; last good copy {format_age(fresh.age)} ago" if fresh.age is not None else "")
    if fresh.age is None:
        return "no data yet"
    if fresh.from_cache:
        return "saved copy, the network is not answering"  # the age of a cached answer is not known
    return f"{format_age(fresh.age)} old"


def feeds_text(app: EyewallApp) -> Table:
    g = app.glyphs
    glyphs = {
        FreshnessState.FRESH: g.fresh,
        FreshnessState.STALE: g.stale,
        FreshnessState.ERROR: g.error,
        FreshnessState.LOADING: g.loading,
    }
    table = Table.grid(padding=(0, 2), expand=True)
    table.add_column(no_wrap=True)
    table.add_column(no_wrap=True)
    table.add_column(ratio=1)  # the detail wraps; it is the only column that does
    for feed in protocol.FEEDS:
        fresh = app.poller.freshness(feed)
        label = FEED_LABELS[feed]
        if not app.poller.active(feed):
            table.add_row(Text(f"  {label}", style=DIM), Text("not polled now", style=DIM), "")
            continue
        cue = FRESHNESS_CUES[fresh.state.value]
        word = "cached" if fresh.from_cache else cue.word
        table.add_row(
            Text(f"{glyphs[fresh.state]} {label}", style=cue.style()),
            Text(word, style=cue.style()),
            Text(_detail(app, feed), style=DIM),
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
    out = Table.grid(expand=True)
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

    def on_mount(self) -> None:
        self.query_one("#feeds-box").border_subtitle = "Esc closes"

    def refresh_status(self) -> None:
        self.query_one("#feeds-text", Static).update(feeds_text(self.app))  # type: ignore[arg-type]

    def action_close(self) -> None:
        self.dismiss()
