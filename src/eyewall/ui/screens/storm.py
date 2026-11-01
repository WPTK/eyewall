"""The Storm screen: one storm in plain words, with the other screens a key away."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll

from eyewall.palette import ACCENT
from eyewall.ui import nav, storm_page
from eyewall.ui.chrome import ChromeScreen, FooterBar, TopBar
from eyewall.ui.widgets.page import Page
from eyewall.ui.widgets.side_panel import Line, View

SMALL_BELOW = (100, 30)  # columns and rows under which the page drops its links and the list of changes


class StormScreen(ChromeScreen):
    NAV_SCOPES = ("storm",)
    BINDINGS = nav.bindings("storm")

    def __init__(self, storm_id: str) -> None:
        super().__init__()
        self.storm_id = storm_id

    def crumb(self) -> str:
        state = self.eye.store.storms.get(self.storm_id)
        return state.storm.name.title() if state is not None else self.storm_id.upper()

    def compose(self) -> ComposeResult:
        yield TopBar()
        with VerticalScroll(id="storm-scroll"):
            yield Page(id="storm-page")
        yield FooterBar()

    def on_mount(self) -> None:
        self.query_one(Page).set_builder(self._lines)
        self.query_one("#storm-scroll", VerticalScroll).focus()
        self.refresh_data()

    # ---- data -------------------------------------------------------------------------------------------------

    def _lines(self, width: int) -> list[Line]:
        eye = self.eye
        state = eye.store.storms.get(self.storm_id)
        if state is None:
            text = Text(f"{self.storm_id.upper()} is no longer active. Press Esc to go back.", style=f"bold {ACCENT}")
            return [Line(text)]
        now = eye.now()
        view = View.of(eye, eye.storm_states())
        small = self.size.width < SMALL_BELOW[0] or self.size.height < SMALL_BELOW[1]
        ctx = storm_page.Context(
            state,
            buoys=len(eye.store.nearby_buoys(self.storm_id, now)),
            gauges=len(eye.store.nearby_tides(self.storm_id, now)),
            small=small,
        )
        return storm_page.page_lines(view, ctx, width)

    def refresh_data(self) -> None:
        self.query_one(Page).repaint()
        self.refresh_bindings()

    # ---- actions ----------------------------------------------------------------------------------------------

    def check_action(self, action: str, _parameters: tuple[object, ...]) -> bool | None:
        if action == "other_storm":
            return len(self.eye.storm_states()) > 1 and self.storm_id in self.eye.store.storms
        if action in ("buoys", "text", "pictures", "chances"):
            return self.storm_id in self.eye.store.storms
        return True

    def action_other_storm(self, step: int) -> None:
        eye = self.eye
        ids = [s.storm.id for s in eye.storm_states()]
        if len(ids) < 2:
            return
        current = ids.index(self.storm_id) if self.storm_id in ids else 0
        self.storm_id = ids[(current + step) % len(ids)]
        eye.selected = self.storm_id
        self.query_one("#storm-scroll", VerticalScroll).scroll_home(animate=False)
        self.refresh_data()
        self.refresh_status()

    def action_buoys(self) -> None:
        self.eye.open_buoys(self.storm_id)

    def action_text(self) -> None:
        self.eye.open_text(self.storm_id)

    def action_chances(self) -> None:
        self.eye.open_text(self.storm_id, "chances")

    def action_pictures(self) -> None:
        self.eye.open_graphics(self.storm_id)
