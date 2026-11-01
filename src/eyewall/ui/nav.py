"""The key table, and the command palette that reads it.

`KEYS` is the one list of keys the interface advertises. The bindings of the app, the screens and the widgets are built
from it (`bindings`), the footer reads it for labels and order (`ui.chrome`), the help screen prints it (`help_rows`)
and the menu lists its entries (`EyewallCommands`). A key that is not here has no footer item and no help line, and a
test fails when a key is here without a binding, so the four cannot drift apart.

An entry names the scope that owns the binding. A scope is a screen or a widget class that lists it in `NAV_SCOPES`;
the app owns `app` and `replay`.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from textual.binding import Binding
from textual.command import CommandPalette, DiscoveryHit, Hit, Provider
from textual.screen import ModalScreen

from eyewall.ui import format as fmt
from eyewall.ui import stations as st

if TYPE_CHECKING:
    from eyewall.app import EyewallApp


@dataclass(frozen=True, slots=True)
class Key:
    """One advertised key.

    `keys` is Textual's comma list. `label` is the footer word. `help` is the help sentence: empty merges the key into
    the next row that has one (so `j k Enter` is one row), None leaves it out of the help because another entry
    documents the same key. `shown` replaces the spelled keys in the footer and help (`+/-`). `footer` puts it in the
    footer when its binding is active. `busy` keeps it out of the footer on a quiet main screen (no storm, so nothing to
    zoom to, fit or read): it stays in the help and the menu. `menu` is its title in the command palette, empty for
    none. `bind` is False for an entry the owner binds itself because its actions differ (the tab digits)."""

    scope: str
    keys: str
    action: str
    label: str
    help: str | None = ""
    shown: str = ""
    footer: bool = False
    busy: bool = False
    menu: str = ""
    bind: bool = True
    priority: bool = False

    @property
    def key_list(self) -> list[str]:
        return self.keys.split(",")


# What each scope's section is called in the help. Scopes that share a title share a section.
TITLES: dict[str, str] = {
    "main": "Map",
    "main_map": "Map",
    "map": "Map",
    "storm": "Storm",
    "text": "NHC text",
    "buoys": "Buoys and gauges",
    "stations": "Buoys and gauges",
    "station": "Station",
    "gallery": "Pictures",
    "alerts": "Alert log",
    "app": "Anywhere",
    "replay": "Replay",
}

K = Key
KEYS: tuple[Key, ...] = (
    # ---- the main screen ----
    K("main", "j", "cursor(1)", "next storm"),
    K("main", "k", "cursor(-1)", "previous storm"),
    K("main", "enter", "open_storm", "open", "previous or next storm; open its page", footer=True),
    K("main", "1", "basin('AL')", "Atlantic"),
    K("main", "2", "basin('EP')", "East Pacific"),
    K("main", "3", "basin('CP')", "Central Pacific"),
    K("main", "a", "basin('')", "all basins", "Atlantic, East Pacific, Central Pacific, all"),
    K(
        "main",
        "b",
        "buoys",
        "buoys",
        "buoys and tide gauges near the storm (Your stations when there is none)",
        footer=True,
        menu="Open buoys and gauges",
    ),
    K(
        "main",
        "t",
        "text",
        "NHC text",
        "the National Hurricane Center's text for the storm (the outlook when there is none)",
        footer=True,
        busy=True,
        menu="Open the NHC text",
    ),
    K(
        "main",
        "O",
        "outlook",
        "outlook",
        "the tropical weather outlook text: each area and its chances",
        menu="Open NHC's outlook",
    ),
    K("main", "M", "full_map", "full map", "full-screen map; Esc leaves it"),
    K(
        "main",
        "R",
        "app.start_replay",
        "replay",
        "replay Hurricane Erin on these screens (only when nothing is active)",
        footer=True,
        menu="Replay Hurricane Erin",
    ),
    K("main", "l", "layers", "layers", None),
    K("main", "plus,equals_sign", "zoom_in", "zoom", None, shown="+/-"),
    K("main", "minus", "zoom_out", "zoom out", None),
    K("main", "c", "center", "center", None),
    K("main", "f", "fit", "fit", None),
    K("main", "n", "mark(1)", "next mark", None),
    K("main", "N", "mark(-1)", "previous mark", None),
    # ---- the map ----
    K("map", "plus,equals_sign", "zoom_in", "zoom", "zoom in", shown="+/-", footer=True, busy=True),
    K("map", "minus", "zoom_out", "zoom out", "zoom out"),
    K("map", "left", "pan(-1, 0)", "pan left"),
    K("map", "right", "pan(1, 0)", "pan right"),
    K("map", "up", "pan(0, -1)", "pan up"),
    K("map", "down", "pan(0, 1)", "pan down", "pan the map (or drag it)"),
    K("map", "f", "screen.fit", "fit", "fit the storm", footer=True, busy=True),
    K("map", "n", "mark(1)", "next mark"),
    K("map", "N", "mark(-1)", "previous mark", "next or previous storm, buoy or gauge"),
    K("map", "enter", "open_mark", "open", "open the marked storm, buoy or gauge (or click it)", footer=True),
    K("map", "escape", "clear_mark", "clear", "clear the mark"),
    K("main_map", "c", "screen.center", "center", "center on the storm", footer=True, busy=True),
    K("main_map", "l", "screen.layers", "layers", "map layers", footer=True, busy=True),
    # ---- storm ----
    K("storm", "b", "buoys", "buoys", "buoys and tide gauges near this storm", footer=True),
    K("storm", "t", "text", "text", "the NHC text: advisory, discussion, forecast, wind chances", footer=True),
    K("storm", "g", "pictures", "pictures", None, footer=True),
    K("storm", "p", "chances", "chances", "the chance of storm-force wind at named places", footer=True),
    K("storm", "left", "other_storm(-1)", "previous storm", None, priority=True),
    K(
        "storm",
        "right",
        "other_storm(1)",
        "next storm",
        "previous or next storm",
        shown="left/right",
        footer=True,
        priority=True,
    ),
    # ---- NHC text ----
    K("text", "left", "tab(-1)", "previous product", None, priority=True),
    K(
        "text",
        "right",
        "tab(1)",
        "next product",
        "previous or next product; page up and down scroll",
        shown="left/right",
        footer=True,
        priority=True,
    ),
    # ---- buoys and gauges ----
    K("stations", "enter", "select", "open", "open the highlighted station (or click it)", footer=True),
    K("buoys", "f", "follow", "follow", "follow or stop following the highlighted station", footer=True),
    K("buoys", "s", "sort", "sort", "change the order: nearest, strongest wind, name", footer=True),
    K(
        "buoys",
        "tab",
        "switch",
        "switch",
        "switch between the storm's stations and Your stations",
        footer=True,
        priority=True,
    ),
    K("buoys", "slash", "search", "find", None, footer=True),
    # ---- station ----
    K("station", "f", "follow", "follow", "follow or stop following this station", footer=True),
    K("station", "h", "range", "24/48/72 h", "show 24, 48 or 72 hours", footer=True),
    K("station", "r", "view", "readings", "switch between the charts and the table of readings", footer=True),
    K(
        "station",
        "tab",
        "next_chart",
        "more charts",
        "when the screen is too short for every chart, show the next one",
        priority=True,
    ),
    K("station", "m", "show_on_map", "map", "show this station on the map", footer=True),
    K("station", "i", "about", "about winds", "how buoy winds differ from the storm's winds", footer=True),
    # ---- alert log ----
    K("alerts", "A", "back", "back", None),
    # ---- graphics ----
    K("gallery", "o", "open_url", "open", "open the picture's address in a browser", footer=True),
    K("gallery", "y", "copy_url", "copy URL", "copy the picture's address", footer=True),
    K("gallery", "left_square_bracket", "step(-1)", "previous frame", "step through a loop", shown="[ ]", footer=True),
    K("gallery", "right_square_bracket", "step(1)", "next frame", None),
    K("gallery", "space", "toggle_loop", "play/pause", "play or pause a loop", footer=True),
    # ---- anywhere ----
    K("app", "question_mark", "help", "help", "this list", menu="Help: every key"),
    K(
        "app",
        "ctrl+p",
        "command_palette",
        "menu",
        "the menu: every screen, action, storm and station",
        shown="^p",
        priority=True,
    ),
    K("app", "escape,backspace", "back", "back", "go back one screen; closes a dialog; leaves the full-screen map"),
    K("app", "q", "quit_top", "quit", "quit, from the first screen only"),
    K("app", "m", "map", "map", "go to the map", menu="Go to the map"),
    K("app", "D", "feeds", "feeds", "feed health: each feed, its age and the next refresh", menu="Show feed health"),
    K("app", "slash", "search", "find", "find a buoy or tide gauge by name or id", menu="Find a buoy or tide gauge"),
    K("app", "g", "graphics", "pictures", "pictures for the selected storm", menu="Open the selected storm's pictures"),
    K("app", "A", "alerts", "alerts", "alert log", menu="Open the alert log"),
    K("app", "S", "settings", "settings", "settings", menu="Open settings"),
    K("app", "r", "refresh", "refresh", "refresh every feed now", menu="Refresh every feed"),
    K("app", "u", "units", "units", "cycle the units", menu="Cycle the units"),
    # ---- replay ----
    K("replay", "space", "play_pause", "pause", "pause or resume", menu="Pause or resume the replay"),
    K("replay", "less_than_sign", "speed(-1)", "slower", menu="Replay slower"),
    K("replay", "greater_than_sign", "speed(1)", "faster", "slower or faster", menu="Replay faster"),
    K("replay", "left_square_bracket", "step(-1)", "previous advisory", menu="Previous advisory"),
    K("replay", "right_square_bracket", "step(1)", "next advisory", "previous or next advisory", menu="Next advisory"),
)

# The pinned footer group. Back and quit take turns in the last place: back everywhere but the first screen.
PINNED = ("help", "command_palette")
BACK, QUIT = "back", "quit_top"

KEY_NAMES = {
    "escape": "esc",
    "question_mark": "?",
    "plus": "+",
    "minus": "-",
    "slash": "/",
    "equals_sign": "=",
    "less_than_sign": "<",
    "greater_than_sign": ">",
    "left_square_bracket": "[",
    "right_square_bracket": "]",
    "delete": "del",
    "backspace": "bksp",
    "ctrl+p": "^p",
    "space": "space",
}
HELP_NAMES = {
    "escape": "Esc",
    "ctrl+p": "Ctrl+P",
    "backspace": "Backspace",
    "delete": "Delete",
    "enter": "Enter",
    "tab": "Tab",
    "space": "Space",
    "left": "Left",
    "right": "Right",
    "up": "Up",
    "down": "Down",
}


def key_name(key: str) -> str:
    """How one key reads in the footer."""
    return KEY_NAMES.get(key, key)


def footer_name(entry: Key) -> str:
    return entry.shown or key_name(entry.key_list[0])


def tokens_of(entry: Key) -> list[str]:
    """The key words an entry puts on a help row: its `shown` text, else each key spelled for reading."""
    if entry.shown:
        return entry.shown.split()
    return [HELP_NAMES.get(k, KEY_NAMES.get(k, k)) for k in entry.key_list]


def scope_keys(scope: str) -> list[Key]:
    return [k for k in KEYS if k.scope == scope]


def bindings(*scopes: str) -> list[Binding | tuple[str, str] | tuple[str, str, str]]:
    """Textual bindings for the entries of these scopes (not shown by Textual: the chrome draws the footer)."""
    return [
        Binding(k.keys, k.action, k.label, show=False, priority=k.priority)
        for scope in scopes
        for k in scope_keys(scope)
        if k.bind
    ]


def find(key: str, action: str, scopes: tuple[str, ...]) -> Key | None:
    """The entry for a binding found in a node that owns these scopes."""
    for entry in KEYS:
        if entry.scope in scopes and entry.action == action and key in entry.key_list:
            return entry
    return None


def help_rows() -> list[tuple[str, list[tuple[str, str]]]]:
    """The help: (section title, [(keys, sentence)]) in table order. An entry without a sentence joins the next one's
    row; one with None is documented elsewhere."""
    sections: dict[str, list[tuple[str, str]]] = {}
    pending: list[str] = []
    last_title = ""
    for entry in KEYS:
        title = TITLES[entry.scope]
        if title != last_title:
            pending, last_title = [], title
        if entry.help is None:
            continue
        pending.extend(tokens_of(entry))
        if entry.help:
            sections.setdefault(title, []).append(("  ".join(pending), entry.help))
            pending = []
    return list(sections.items())


# ---- the command palette ------------------------------------------------------------------------------------------


def _storm_title(app: EyewallApp, storm_id: str) -> str:
    state = app.store.storms[storm_id]
    return f"Open storm {state.storm.name.title()} ({fmt.class_label(state.storm)})"


class EyewallCommands(Provider):
    """The menu: every action and screen in the key table, and the active storms."""

    @property
    def eye(self) -> EyewallApp:
        return self.app  # type: ignore[return-value]

    def _runner(self, entry: Key) -> Callable[[], Any]:
        app = self.eye

        async def run() -> None:
            # A main-screen action is run on the main screen, wherever the menu was opened from.
            namespace = next((s for s in app.screen_stack if "main" in getattr(s, "NAV_SCOPES", ())), None)
            if entry.scope == "main" and namespace is not None:
                await app.run_action(entry.action, namespace)
            else:
                await app.run_action(entry.action)

        return run

    def _blocked(self) -> bool:
        """A dialog is open under the menu: its commands would be refused or stack over it, so none are offered."""
        below = [s for s in self.eye.screen_stack if not isinstance(s, CommandPalette)]
        return bool(below) and isinstance(below[-1], ModalScreen)

    def _commands(self) -> list[tuple[str, Callable[[], Any], str]]:
        app = self.eye
        found: list[tuple[str, Callable[[], Any], str]] = []
        if self._blocked():
            return found
        for entry in KEYS:
            name = entry.action.removeprefix("app.").split("(")[0]
            if entry.menu and entry.scope in ("app", "main", "replay") and app.check_action(name, ()):
                found.append((entry.menu, self._runner(entry), f"{footer_name(entry)}  {entry.help or ''}"))
        for storm_id in app.store.storms:
            found.append(
                (_storm_title(app, storm_id), lambda sid=storm_id: app.open_storm(sid), "the storm in plain words")  # type: ignore[misc]
            )
        return found

    async def discover(self) -> AsyncIterator[DiscoveryHit]:
        for title, command, help_text in self._commands():
            yield DiscoveryHit(title, command, help=help_text)

    async def search(self, query: str) -> AsyncIterator[Hit]:
        matcher = self.matcher(query)
        for title, command, help_text in self._commands():
            score = matcher.match(title)
            if score > 0:
                yield Hit(score, matcher.highlight(title), command, text=title, help=help_text)
        if self._blocked():
            return
        async for hit in StationCommands.station_hits(self.eye, query):
            yield hit


class StationCommands(Provider):
    """`/`: the menu with only stations in it. It opens at the stations you follow; a name or number finds any."""

    @property
    def eye(self) -> EyewallApp:
        return self.app  # type: ignore[return-value]

    def _opener(self, kind: str, station_id: str) -> Callable[[], Any]:
        app = self.eye
        return lambda: app.open_station(kind, station_id)

    async def discover(self) -> AsyncIterator[DiscoveryHit]:
        app = self.eye
        followed = [("ndbc", e.id, e.station.name) for e in st.watchlist_buoys(app.store)]
        followed += [("coops", e.id, e.station.name) for e in st.watchlist_gauges(app.store)]
        for kind, station_id, name in followed:
            title = f"{KIND_WORDS[kind]} {station_id} {st.clean_name(name)}".strip()
            yield DiscoveryHit(title, self._opener(kind, station_id), help="you follow this station")

    async def search(self, query: str) -> AsyncIterator[Hit]:
        async for hit in self.station_hits(self.eye, query):
            yield hit

    @staticmethod
    async def station_hits(app: EyewallApp, query: str) -> AsyncIterator[Hit]:
        """Stations whose name or number match: shared by `/` and the main menu (Ctrl+P)."""
        if len(query.strip()) < 2:
            return
        if not (app.store.stations and app.store.tide_stations):
            if app.catalogs_task is None:  # one fetch for the session: a failure is not repeated on every keystroke
                app.catalogs_task = asyncio.ensure_future(app.ensure_catalogs())
            # Each keystroke cancels the previous search; the shield keeps that from cancelling the shared fetch.
            await asyncio.shield(app.catalogs_task)
        for rank, hit in enumerate(st.search_stations(app.store, query, limit=12)):
            title = f"{KIND_WORDS[hit.kind]} {hit.id} {' '.join(hit.name.split())}".strip()
            yield Hit(
                max(0.05, 0.6 - rank * 0.01),
                title,
                lambda kind=hit.kind, sid=hit.id: app.open_station(kind, sid),
                text=title,
                help=hit.detail or None,
            )


KIND_WORDS = {"ndbc": "Buoy", "coops": "Gauge"}


__all__ = [
    "BACK",
    "KEYS",
    "PINNED",
    "QUIT",
    "TITLES",
    "EyewallCommands",
    "Key",
    "StationCommands",
    "bindings",
    "find",
    "footer_name",
    "help_rows",
    "key_name",
    "scope_keys",
    "tokens_of",
]
