"""The NHC text screen: each product as NHC issued it, one tab per product, with its issue time and a stale banner."""

from __future__ import annotations

from rich.console import RenderableType
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static, Tab, Tabs

from eyewall.palette import DIM, FRESHNESS_CUES
from eyewall.poll import FreshnessState
from eyewall.sources import protocol
from eyewall.ui import nav, nhc_text
from eyewall.ui.chrome import ChromeScreen, FooterBar, TopBar


class NhcTextScreen(ChromeScreen):
    CRUMB = "NHC text"
    NAV_SCOPES = ("text",)
    BINDINGS = nav.bindings("text")

    def __init__(self, storm_id: str | None, tab: str | None = None) -> None:
        super().__init__()
        self.storm_id = storm_id
        self.tabs: tuple[tuple[str, str], ...] = nhc_text.TABS if storm_id else (("outlook", "Outlook"),)
        self.tab = tab if tab in [t for t, _ in self.tabs] else nhc_text.first_tab(storm_id is not None)

    def compose(self) -> ComposeResult:
        yield TopBar()
        yield Tabs(
            *(Tab(title, id=f"t-{tab_id}") for tab_id, title in self.tabs), active=f"t-{self.tab}", id="text-tabs"
        )
        yield Static("", id="text-head")
        yield Static("", id="text-stale")
        with VerticalScroll(id="text-scroll"):
            yield Static("", id="text-body")
        yield FooterBar()

    def on_mount(self) -> None:
        self.query_one("#text-scroll", VerticalScroll).focus()
        self.refresh_data()

    def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        event.stop()
        tab = (event.tab.id or "").removeprefix("t-")
        if tab and tab != self.tab:
            self.tab = tab
            self.query_one("#text-scroll", VerticalScroll).scroll_home(animate=False)
        self.refresh_data()

    # ---- data -------------------------------------------------------------------------------------------------

    def _feed_old(self, feed: str) -> tuple[bool, float | None]:
        fresh = self.eye.poller.freshness(feed)
        return fresh.state in (FreshnessState.ERROR, FreshnessState.STALE), fresh.age

    def refresh_data(self) -> None:
        eye = self.eye
        now, tz, g = eye.now(), eye.local_tz, eye.glyphs
        body: RenderableType
        if self.tab == "outlook":
            old, _ = self._feed_old(protocol.OUTLOOK)
            header = nhc_text.outlook_header(eye.store.outlook, now, tz, g, feed_old=old)
            body = nhc_text.outlook_body(eye.store.outlook, eye.basin_view)
        else:
            state = eye.store.storms.get(self.storm_id or "")
            if state is None:
                header = nhc_text.Header(Text(f"{(self.storm_id or '').upper()} is no longer active.", style=DIM))
                body = Text("Press Esc to go back.", style=DIM)
            else:
                old, age = self._feed_old(protocol.STORMS)
                header = nhc_text.storm_header(state, self.tab, now, tz, g, feed_old=old, feed_age=age)
                body = nhc_text.storm_body(state, self.tab, eye.preset, tz, g)
        self.query_one("#text-head", Static).update(header.text)
        banner = self.query_one("#text-stale", Static)
        banner.display = header.stale is not None
        if header.stale is not None:
            banner.update(Text(header.stale, style=FRESHNESS_CUES["stale"].style()))
        self.query_one("#text-body", Static).update(body)

    # ---- actions ----------------------------------------------------------------------------------------------

    def check_action(self, action: str, _parameters: tuple[object, ...]) -> bool | None:
        if action == "tab":
            return len(self.tabs) > 1
        return True

    def action_tab(self, step: int) -> None:
        ids = [t for t, _ in self.tabs]
        new = ids[(ids.index(self.tab) + step) % len(ids)]
        self.query_one(Tabs).active = f"t-{new}"
