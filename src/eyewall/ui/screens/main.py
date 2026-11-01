"""The main screen: the map, with the named storms and the watches and warnings beside it or under it.

The map is the largest thing on screen at every size. Three layouts, chosen by the terminal's size, each drop whole
items rather than clip them:

- small (under 100 columns or 30 rows, 80x24 and up): the map fills the screen, with a one-line storm summary and one
  line of warnings under it. Everything else is a key away.
- medium (100x30 and up): the map with a column of storm cards, warnings, what NHC is watching and the stations near
  the storm beside it.
- large (160x40 and up): the same column, wider, with fuller cards.

With nothing active the same places hold the outlook areas, your stations and the replay offer instead.
"""

from __future__ import annotations

from enum import StrEnum

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.events import Resize
from textual.widgets import Static

from eyewall.clock import format_age
from eyewall.sources import protocol
from eyewall.state.events import current_adv
from eyewall.state.store import StormState
from eyewall.ui import adapt, nav
from eyewall.ui.chrome import ChromeScreen, FooterBar, TopBar
from eyewall.ui.widgets import side_info, storm_cards, warning_list
from eyewall.ui.widgets.map_view import MapPane, MapView
from eyewall.ui.widgets.side_panel import Block, Line, SidePanel, View
from eyewall.ui.words import storm as storm_words

REFRESH_SECONDS = 30.0  # the ages on the cards move without a new poll
MEDIUM_FROM = (100, 30)  # columns and rows at which the column beside the map fits
LARGE_FROM = (160, 40)
STRIP_ROWS = 4  # the most the strip under the map takes on a small terminal


class Tier(StrEnum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


def tier_for(width: int, height: int) -> Tier:
    """The layout for a terminal of this size."""
    if width < MEDIUM_FROM[0] or height < MEDIUM_FROM[1]:
        return Tier.SMALL
    if width >= LARGE_FROM[0] and height >= LARGE_FROM[1]:
        return Tier.LARGE
    return Tier.MEDIUM


def lead_text(view: View) -> Text:
    """The one sentence at the top: what is happening, or that nothing is."""
    if not view.storms_known:
        word = "Storm data unavailable." if protocol.STORMS in view.failed else f"Checking for storms{view.g.ellipsis}"
        return Text(word, style="bold")
    if view.storms_old:
        # The feed has stopped answering: never say "no storms" (or a storm's state) as if it were current.
        reason = _old_reason(view)
        if not view.states:
            return Text(f"Storm data unavailable ({reason}).", style="bold")
        note = f" Storm data is not updating ({reason})."
    else:
        note = ""
    if not view.states:
        return Text(storm_words.nothing_active(view.basins).text, style="bold")
    if len(view.states) == 1:
        text = storm_words.storm_lead(view.states[0], view.preset).text
    else:
        text = storm_words.several_storms(view.states).text
    pending = warning_list.unread(view)
    if pending:
        text += " " + _unread_sentence(pending, len(view.states))
    return Text(text + note, style="bold")


def _old_reason(view: View) -> str:
    """Why the storm data is old, in the words the health slot uses; the age only when it is known and worth saying."""
    if view.storms_cached:
        return "offline, cached"
    ago = (
        f", last update {format_age(view.storms_age)} ago"
        if view.storms_age is not None and view.storms_age >= 60
        else ""
    )
    return f"storms feed failing{ago}"


def _unread_sentence(pending: list[StormState], total: int) -> str:
    if total == 1:
        adv = current_adv(pending[0].storm)
        return (
            f"Its watches and warnings are not yet read for advisory {adv}."
            if adv
            else "Its watches and warnings are not yet read."
        )
    names = [s.storm.name.title() if s.storm.name else s.storm.id.upper() for s in pending]
    return f"Watches and warnings are not yet read for {', '.join(names)}."


def side_blocks(view: View, width: int) -> list[Block]:
    """The column beside the map, most important first."""
    if not view.storms_known:
        return []
    if view.states:
        return [
            *storm_cards.card_blocks(view, width),
            *warning_list.blocks(view, width),
            *side_info.areas_block(view, width, priority=5),
            *side_info.near_block(view, width, priority=6),
        ]
    return [
        *side_info.areas_block(view, width, priority=0),
        *side_info.replay_block(view, width, priority=1),
        *side_info.stations_block(view, width, priority=2),
    ]


def strip_blocks(view: View, width: int) -> list[Block]:
    """The strip under the map on a small terminal."""
    if not view.storms_known:
        return []
    if not view.states:
        return side_info.quiet_strip(view, width)
    out: list[Block] = []
    storm_line = storm_cards.strip_line(view, width)
    if storm_line is not None:
        out.append(Block((storm_line,), 0))
    unread = warning_list.unread_lines(view, width)
    if unread:  # one unread storm is named; any more are counted, so the strip never grows past one line for them
        out.append(Block((unread[0],), 0))
    if len(unread) > 1:
        more = Text(f"+{len(unread) - 1} more {view.g.crumb}", style="underline", no_wrap=True)
        out.append(Block((Line(more, unread[1].action),), 0))
    warnings = warning_list.strip_line(view, width)
    if warnings is not None:
        found = warning_list.items(view)
        # Priority 1 goes first when the strip is short; it is then never silent: `N watches and warnings >`.
        out.append(
            Block(
                (warnings,),
                1,
                group="warnings",
                more=warnings.action,
                noun=("watch or warning", "watches and warnings"),
                count=max(len(found), 1),
            )
        )
    return out


class MainMap(MapView):
    """The main screen's map: the keys only it has, listed in the footer while it has the focus."""

    NAV_SCOPES = ("main_map", "map")
    BINDINGS = nav.bindings("main_map")


class MainScreen(ChromeScreen):
    CRUMB = "Home"
    NAV_SCOPES = ("main",)
    BINDINGS = nav.bindings("main")

    def __init__(self) -> None:
        super().__init__()
        self._full_map = False
        self.tier = Tier.SMALL
        self.states: tuple[StormState, ...] = ()

    @property
    def quiet(self) -> bool:
        """Nothing is active and the map is not full screen: the footer lists only what there is to do."""
        return not self.states and not self._full_map

    # ---- layout -----------------------------------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        eye = self.eye
        yield TopBar()
        yield Static("", id="lead")
        self.map_view = MainMap(mode=eye.map_mode, options=eye.map_options)
        with Horizontal(id="body"):
            yield MapPane(self.map_view, id="map-pane")
            yield SidePanel(id="side")
        yield SidePanel(id="strip", fill=False, max_rows=STRIP_ROWS)
        yield FooterBar()

    def on_mount(self) -> None:
        self.query_one("#side", SidePanel).set_builder(lambda width: side_blocks(self._view(), width))
        self.query_one("#strip", SidePanel).set_builder(lambda width: strip_blocks(self._view(), width))
        self._apply_tier(self.size.width, self.size.height)
        self.set_interval(REFRESH_SECONDS, self._paint)
        self.map_view.focus()
        self.refresh_data()

    def on_resize(self, event: Resize) -> None:
        self._apply_tier(event.size.width, event.size.height)

    def _apply_tier(self, width: int, height: int) -> None:
        self.tier = tier_for(width, height)
        for tier in Tier:
            self.set_class(self.tier is tier, f"tier-{tier.value}")
        self.set_class(self._full_map, "full-map")
        self._paint()

    # ---- data -------------------------------------------------------------------------------------------------

    def _view(self) -> View:
        return View.of(self.eye, self.states, rich=self.tier is Tier.LARGE)

    def refresh_data(self) -> None:
        """Take the storms from the store, keep the selection on one that is still there, and redraw."""
        eye = self.eye
        self.states = eye.storm_states()
        ids = [s.storm.id for s in self.states]
        if eye.selected not in ids:
            eye.selected = ids[0] if ids else None
        self.map_view.set_scene(adapt.map_scene(eye.store, eye.now(), eye.selected), self._fit_points())
        self._paint()

    def _paint(self) -> None:
        if not self.is_attached:
            return
        view = self._view()
        self.query_one("#lead", Static).update(lead_text(view))
        self.query_one("#side", SidePanel).repaint()
        self.query_one("#strip", SidePanel).repaint()

    def _fit_points(self) -> list[tuple[float, float]]:
        eye = self.eye
        state = eye.store.storms.get(eye.selected or "")
        if state is not None:
            points = adapt.storm_scene(state).near_extent()
            if points:
                return points
        return adapt.quiet_points(eye.basin_view)

    # ---- actions ----------------------------------------------------------------------------------------------

    def action_cursor(self, step: int) -> None:
        """j and k: the next or previous storm, which the map then shows with its stations."""
        eye = self.eye
        ids = [s.storm.id for s in self.states]
        if len(ids) < 2 or eye.selected not in ids:
            return
        eye.selected = ids[(ids.index(eye.selected) + step) % len(ids)]
        self.refresh_data()
        self.map_view.fit()

    def action_outlook(self) -> None:
        """`O`: the tropical weather outlook text, every area with its exact chances."""
        eye = self.eye
        eye.open_text(eye.selected, "outlook")

    def action_open_storm(self) -> None:
        self.eye.open_storm(self.eye.selected)

    def action_buoys(self) -> None:
        """The stations near the selected storm, or Your stations when there is no storm to look at."""
        self.eye.open_buoys(self.eye.selected)

    def action_text(self) -> None:
        """The NHC text for the selected storm, or the outlook when there is no storm."""
        self.eye.open_text(self.eye.selected)

    def action_basin(self, code: str) -> None:
        self.eye.basin_filter = code or None
        self.refresh_data()
        self.map_view.fit()

    def can_go_back(self) -> bool:
        """Esc leaves the full-screen map; on the plain main screen there is nothing to go back to."""
        return self._full_map

    def go_back(self) -> None:
        self.action_full_map()

    def show_map(self) -> None:
        """`m` from another screen lands here: the map, with its panels."""
        if self._full_map:
            self.action_full_map()

    def action_full_map(self) -> None:
        self._full_map = not self._full_map
        self.set_class(self._full_map, "full-map")
        self.refresh_status()  # Esc is back, or nothing to go back to, depending on this

    def action_layers(self) -> None:
        self.eye.open_layers()

    def action_zoom_in(self) -> None:
        self.map_view.action_zoom_in()

    def action_zoom_out(self) -> None:
        self.map_view.action_zoom_out()

    def action_center(self) -> None:
        state = self.eye.store.storms.get(self.eye.selected or "")
        if state is not None and state.storm.lat is not None and state.storm.lon is not None:
            self.map_view.center_on((state.storm.lat, state.storm.lon))

    def action_fit(self) -> None:
        self.map_view.fit()

    def action_mark(self, step: int) -> None:
        self.map_view.action_mark(step)
