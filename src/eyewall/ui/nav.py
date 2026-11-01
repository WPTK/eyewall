"""The key table, and the command palette that reads it.

`KEYS` is the one list of keys the interface advertises. The bindings of the app, the screens and the widgets are built
from it (`bindings`), the footer reads it for labels and order (`ui.chrome`), the help screen prints it (`help_rows`)
and the menu lists its entries (`EyewallCommands`). A key that is not here has no footer item and no help line, and a
test fails when a key is here without a binding, so the four cannot drift apart.

An entry names the scope that owns the binding. A scope is a screen or a widget class that lists it in `NAV_SCOPES`;
the app owns `app` and `replay`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from textual.binding import Binding
from textual.command import DiscoveryHit, Hit, Provider

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
    footer when its binding is active. `menu` is its title in the command palette, empty for none. `bind` is False for
    an entry the owner binds itself because its actions differ (the tab digits)."""

    scope: str
    keys: str
    action: str
    label: str
    help: str | None = ""
    shown: str = ""
    footer: bool = False
    menu: str = ""
    bind: bool = True
    priority: bool = False

    @property
    def key_list(self) -> list[str]:
        return self.keys.split(",")


# What each scope's section is called in the help. Scopes that share a title share a section.
TITLES: dict[str, str] = {
    "dashboard": "Dashboard",
    "storm_list": "Dashboard",
    "dashboard_map": "Map",
    "map": "Map",
    "detail": "Storm detail",
    "stations": "Storm detail",
    "buoy": "Buoy charts",
    "watch": "Watchlist",
    "outlook": "Outlook",
    "gallery": "Graphics",
    "alerts": "Alert log",
    "app": "Anywhere",
    "replay": "Replay",
}

K = Key
KEYS: tuple[Key, ...] = (
    # ---- the dashboard ----
    K("dashboard", "j", "cursor(1)", "next storm"),
    K("dashboard", "k", "cursor(-1)", "previous storm"),
    K("dashboard", "enter", "open_detail", "detail", "previous or next storm; open its detail", footer=True),
    K("dashboard", "tab", "app.focus_next", "focus", "move between the list, the map and the panels", bind=False),
    K("dashboard", "1", "basin('AL')", "Atlantic"),
    K("dashboard", "2", "basin('EP')", "East Pacific"),
    K("dashboard", "3", "basin('CP')", "Central Pacific"),
    K("dashboard", "a", "basin('')", "all basins", "Atlantic, East Pacific, Central Pacific, all"),
    K("dashboard", "b", "buoys", "buoys", "buoys near the storm (the watchlist when there is none)", footer=True),
    K("dashboard", "m", "toggle_map", "map", "map on or off", footer=True),
    K("dashboard", "M", "full_map", "full map", "full-screen map; Esc leaves it"),
    K("dashboard", "l", "layers", "layers", None),
    K("dashboard", "plus,equals_sign", "zoom_in", "zoom", None, shown="+/-"),
    K("dashboard", "minus", "zoom_out", "zoom out", None),
    K("dashboard", "c", "center", "center", None),
    K("dashboard", "f", "fit", "fit", None),
    K("dashboard", "n", "mark(1)", "next mark", None),
    K("dashboard", "N", "mark(-1)", "previous mark", None),
    K("storm_list", "enter", "select", "detail", None, footer=True),
    # ---- the map ----
    K("map", "plus,equals_sign", "zoom_in", "zoom", "zoom in", shown="+/-", footer=True),
    K("map", "minus", "zoom_out", "zoom out", "zoom out"),
    K("map", "left", "pan(-1, 0)", "pan left"),
    K("map", "right", "pan(1, 0)", "pan right"),
    K("map", "up", "pan(0, -1)", "pan up"),
    K("map", "down", "pan(0, 1)", "pan down", "pan the map (or drag it)"),
    K("map", "f", "screen.fit", "fit", "fit the storm", footer=True),
    K("map", "n", "mark(1)", "next mark"),
    K("map", "N", "mark(-1)", "previous mark", "next or previous storm, buoy or gauge"),
    K("map", "enter", "open_mark", "open", "open the marked storm, buoy or gauge (or click it)", footer=True),
    K("map", "escape", "clear_mark", "clear", "clear the mark"),
    K("dashboard_map", "c", "screen.center", "center", "center on the storm", footer=True),
    K("dashboard_map", "l", "screen.layers", "layers", "map layers", footer=True),
    # ---- storm detail ----
    K("detail", "left", "tab(-1)", "previous tab", priority=True),
    K("detail", "right", "tab(1)", "next tab", "previous or next tab", priority=True),
    K("detail", "1,2,3,4,5,6,7,8,9,0", "show_tab", "tab", "jump to a tab", shown="1-0", bind=False),
    K("detail", "t", "toggle_text", "tcp/tcm", "on the Advisory tab: public or forecast advisory", footer=True),
    K("detail", "p", "pin", "pin", "on the Buoys and Tides tabs: pin or unpin a station", footer=True),
    K("stations", "enter", "select_cursor", "charts", "open a buoy's charts", footer=True),
    # ---- buoy charts ----
    K("buoy", "h", "range", "range", "change the time range", footer=True),
    K("buoy", "p", "pin", "pin", "pin or unpin this buoy", footer=True),
    K("buoy", "i", "toggle_info", "info", "charts or latest observation, on a narrow terminal"),
    # ---- watchlist ----
    K("watch", "a", "add", "add", "add a station", footer=True),
    K("watch", "d,delete", "remove", "remove", "remove the selected station", shown="d", footer=True),
    K("watch", "tab", "other_table", "other table", "switch between buoys and gauges", footer=True, priority=True),
    K("watch", "w", "back", "back", None),
    # ---- outlook ----
    K("outlook", "O", "back", "back", None),
    K("outlook", "plus,equals_sign", "zoom_in", "zoom", None, shown="+/-"),
    K("outlook", "minus", "zoom_out", "zoom out", None),
    K("outlook", "f", "fit", "fit", None),
    K("outlook", "n", "mark(1)", "next mark", None),
    K("outlook", "N", "mark(-1)", "previous mark", None),
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
    K("app", "O", "outlook", "outlook", "tropical weather outlook", menu="Open the tropical weather outlook"),
    K("app", "w", "watchlist", "watchlist", "the buoy and tide gauge watchlist", menu="Open the watchlist"),
    K("app", "slash", "search", "find", "find a buoy or tide gauge by name or id", menu="Find a buoy or tide gauge"),
    K("app", "g", "graphics", "graphics", "graphics for the selected storm", menu="Open the selected storm's graphics"),
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
    """The menu: every action and screen in the key table, the active storms, and stations by name or id."""

    @property
    def eye(self) -> EyewallApp:
        return self.app  # type: ignore[return-value]

    def _runner(self, action: str) -> Callable[[], Any]:
        app = self.eye

        async def run() -> None:
            await app.run_action(action)

        return run

    def _commands(self) -> list[tuple[str, Callable[[], Any], str]]:
        app = self.eye
        found: list[tuple[str, Callable[[], Any], str]] = []
        for entry in KEYS:
            if entry.menu and entry.scope in ("app", "replay") and app.check_action(entry.action.split("(")[0], ()):
                found.append((entry.menu, self._runner(entry.action), f"{footer_name(entry)}  {entry.help or ''}"))
        for storm_id in app.store.storms:
            found.append(
                (_storm_title(app, storm_id), lambda sid=storm_id: app.open_detail(sid), "the storm's detail page")  # type: ignore[misc]
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
        app = self.eye
        if len(query.strip()) < 2:
            return
        if not (app.store.stations and app.store.tide_stations) and not app.catalogs_asked:
            app.catalogs_asked = True  # once: a failed fetch is not repeated on every keystroke
            await app.ensure_catalogs()
        for rank, hit in enumerate(st.search_stations(app.store, query, limit=12)):
            kind = st.KIND_LABELS[hit.kind]
            title = f"{kind.title()} {hit.id} {' '.join(hit.name.split())}".strip()
            run: Callable[[], Any] = (
                (lambda sid=hit.id: app.open_buoy(sid))  # type: ignore[misc]
                if hit.kind == "ndbc"
                else (lambda sid=hit.id: app.notify(app.gauge_summary(sid), timeout=6))  # type: ignore[misc]
            )
            yield Hit(max(0.05, 0.6 - rank * 0.01), title, run, text=title, help=hit.detail or None)


__all__ = [
    "BACK",
    "KEYS",
    "PINNED",
    "QUIT",
    "TITLES",
    "EyewallCommands",
    "Key",
    "bindings",
    "find",
    "footer_name",
    "help_rows",
    "key_name",
    "scope_keys",
    "tokens_of",
]
