"""The eyewall input inventory: every key, clickable and palette entry the interface offers, collected from the code and
from the running screens (see `registry.py` for the pattern).

Item ids:

- `key:<screen>:<key>`                     a binding on a screen (nav.KEYS scopes, literal BINDINGS of dialogs)
- `key:<screen>:<Widget>:<key>`            a key a built-in widget on that screen answers to (list up/down/enter ...)
- `click:footer:<screen>:<action>`         a footer cell, `click:crumb:<screen>:<i>`, `click:slot:<screen>`, `click:topbar:...`
- `click:link:<screen>:<panel>:<action>`   a link in the side panel, strip or a page
- `click:tab:<screen>:<id>`, `click:row:<screen>:<Widget>`, `click:widget:<screen>:<Widget>:<id>`
- `click:mark:<kind>` and the other map gestures
- `palette:<title>`                        a command-palette entry
- `claim:<id>`                             a README claim (see claims.py)

Static items come from the key table and class attributes; dynamic ones (footer cells, links, rows, tabs) from the
screens as they are drawn in `INVENTORY_WORLDS`.
"""

from __future__ import annotations

import inspect
import re
import typing
from typing import Any

from textual.binding import Binding
from textual.command import CommandPalette
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import (
    DataTable,
    Input,
    OptionList,
    Select,
    SelectionList,
    Switch,
    Tab,
    Tabs,
)

from eyewall.render.hits import MarkKind
from eyewall.ui import nav
from eyewall.ui.chrome import ChromeScreen, FooterBar, TopBar
from eyewall.ui.screens.alerts import AlertLogScreen
from eyewall.ui.screens.buoys import BuoysScreen
from eyewall.ui.screens.feeds import FeedsScreen
from eyewall.ui.screens.graphics import GraphicsScreen
from eyewall.ui.screens.help import HelpScreen
from eyewall.ui.screens.layers import LayerMenu
from eyewall.ui.screens.main import MainMap, MainScreen
from eyewall.ui.screens.nhc_text import NhcTextScreen
from eyewall.ui.screens.settings import SettingsScreen
from eyewall.ui.screens.station import FollowLine, StationScreen
from eyewall.ui.screens.storm import StormScreen
from eyewall.ui.widgets.gallery import GalleryPanel
from eyewall.ui.widgets.map_view import MapView, MarkChooser
from eyewall.ui.widgets.page import Page
from eyewall.ui.widgets.side_panel import SidePanel
from eyewall.ui.widgets.station_list import StationList
from tests.uat.inventory.worlds import W

# The screens that carry the chrome (top bar, footer). The names are the ones `W.goto` uses.
CHROME_SCREENS: dict[str, type[Screen[Any]]] = {
    "main": MainScreen,
    "storm": StormScreen,
    "text": NhcTextScreen,
    "buoys": BuoysScreen,
    "station": StationScreen,
    "alerts": AlertLogScreen,
    "graphics": GraphicsScreen,
}
DIALOGS: dict[str, type[Screen[Any]]] = {
    "help": HelpScreen,
    "feeds": FeedsScreen,
    "settings": SettingsScreen,
    "layers": LayerMenu,
    "chooser": MarkChooser,
}
# which goto name shows which inventory screen name
SCREEN_OF = {
    "main": "main",
    "full_map": "main",
    "storm": "storm",
    "text": "text",
    "buoys_near": "buoys",
    "buoys_yours": "buoys",
    "station_buoy": "station",
    "station_gauge": "station",
    "alerts": "alerts",
    "graphics": "graphics",
    "help": "help",
    "feeds": "feeds",
    "settings": "settings",
    "layers": "layers",
}
IMPLICIT_KEYS = {"up", "down", "left", "right", "enter", "space"}
INTERACTIVE: tuple[type[Widget], ...] = (OptionList, Tabs, DataTable, Input, Select, Switch, SelectionList)


def hosted(screen: type[Screen[Any]]) -> list[type[Widget]]:
    """Widget classes with their own key scopes that the screen composes (found from its compose source)."""
    source = inspect.getsource(screen.compose) if "compose" in screen.__dict__ else ""
    candidates = [MainMap, MapView, StationList, GalleryPanel]
    return [c for c in candidates if c.__name__ in source]


def scopes_of(screen: type[Screen[Any]]) -> set[str]:
    out = set(getattr(screen, "NAV_SCOPES", ()))
    for widget in hosted(screen):
        out |= set(getattr(widget, "NAV_SCOPES", ()))
    return out


def literal_keys(cls: type[Screen[Any]]) -> list[str]:
    out: list[str] = []
    for binding in getattr(cls, "BINDINGS", []):
        if isinstance(binding, Binding):
            out += binding.key.split(",")
    return out


def static_key_items() -> set[str]:
    items: set[str] = set()
    for name, cls in CHROME_SCREENS.items():
        scopes = scopes_of(cls)
        for entry in nav.KEYS:
            if entry.scope in scopes or entry.scope in ("app", "replay"):
                for key in entry.key_list:
                    items.add(f"key:{name}:{key}")
    for name, cls in DIALOGS.items():
        for key in literal_keys(cls):
            items.add(f"key:{name}:{key}")
    return items


def widget_keys(widget: Widget) -> set[str]:
    return set(type(widget)._merged_bindings.key_to_bindings) & IMPLICIT_KEYS  # type: ignore[attr-defined]


def interactive_widgets(screen: Screen[Any]) -> list[Widget]:
    return [w for w in screen.query("*") if isinstance(w, INTERACTIVE) and w.display]


def widget_name(widget: Widget) -> str:
    return type(widget).__name__


def normalise(action: str) -> str:
    """A link action without the storm id, so one line per kind of link."""
    return re.sub(r"(open:)[a-z]{2}\d{6}", r"\1storm", action)


def collect_screen(w: W, name: str) -> set[str]:
    """Dynamic items on the screen showing now (which `W.goto(name)` opened)."""
    screen = w.screen
    shown = SCREEN_OF.get(name, name)
    items: set[str] = set()
    if isinstance(screen, ChromeScreen):
        for bar in screen.query(FooterBar):
            for target in bar.row.targets if bar.row else ():
                items.add(f"click:footer:{shown}:{target.action}")
        for bar in screen.query(TopBar):
            for target in bar.row.targets if bar.row else ():
                if target.action.startswith("app:crumb"):
                    items.add(f"click:crumb:{shown}:{target.action}")
                elif target.action == "app:feeds":
                    items.add(f"click:slot:{shown}")
                else:
                    items.add(f"click:topbar:{shown}:{target.action}")
        for panel in screen.query(SidePanel):
            for line in panel._state.lines:
                if line.action:
                    items.add(f"click:link:{shown}:{panel.id}:{normalise(line.action)}")
        for page in screen.query(Page):
            for line in page._lines:
                if line.action:
                    items.add(f"click:link:{shown}:{page.id}:{normalise(line.action)}")
        for follow in screen.query(FollowLine):
            items.add(f"click:widget:{shown}:FollowLine:{follow.id}")
    if isinstance(screen, CommandPalette):
        return items  # the menu has its own entries (palette:...), not rows to click
    for widget in interactive_widgets(screen):
        kind = widget_name(widget)
        if isinstance(widget, Tabs):
            for tab in widget.query(Tab):
                items.add(f"click:tab:{shown}:{tab.id}")
        elif isinstance(widget, OptionList | DataTable | SelectionList):
            items.add(f"click:row:{shown}:{kind}")
        else:
            items.add(f"click:widget:{shown}:{kind}:{widget.id}")
        for key in widget_keys(widget):
            items.add(f"key:{shown}:{kind}:{key}")
    return items


MARK_KINDS = tuple(typing.get_args(MarkKind))
MAP_GESTURES = ("chooser", "empty", "drag", "wheel", "hover")


def static_click_items() -> set[str]:
    items = {f"click:mark:{kind}" for kind in MARK_KINDS}
    items |= {f"click:mark:{g}" for g in MAP_GESTURES}
    return items


def palette_items() -> set[str]:
    items = {f"palette:{entry.menu}" for entry in nav.KEYS if entry.menu}
    items |= {"palette:Open storm", "palette:Find station"}
    return items


DYNAMIC: set[str] = set()  # filled by every `observe` call: the screens as the checks and the matrix see them


def observe(w: W, name: str) -> set[str]:
    """Collect the dynamic items of the screen showing now and remember them in the inventory."""
    found = collect_screen(w, name)
    DYNAMIC.update(found)
    return found


def full_inventory() -> set[str]:
    from tests.uat.inventory import claims

    return static_key_items() | static_click_items() | palette_items() | set(DYNAMIC) | claims.items()
