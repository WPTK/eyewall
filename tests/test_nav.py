"""The key table is the one list of keys: every entry has a binding, a help row and a place it is shown."""

from __future__ import annotations

from collections import Counter

import pytest
from rich.console import Console
from textual.binding import Binding
from textual.screen import Screen

from eyewall.app import EyewallApp
from eyewall.ui import nav
from eyewall.ui.screens.alerts import AlertLogScreen
from eyewall.ui.screens.buoy_detail import BuoyDetailScreen
from eyewall.ui.screens.dashboard import DashboardMap, DashboardScreen
from eyewall.ui.screens.detail import StormDetailScreen
from eyewall.ui.screens.help import help_text
from eyewall.ui.screens.outlook import OutlookScreen
from eyewall.ui.screens.watchlist import WatchlistScreen
from eyewall.ui.widgets.gallery import GalleryPanel
from eyewall.ui.widgets.map_view import MapView
from eyewall.ui.widgets.station_table import StationTable
from eyewall.ui.widgets.storm_list import StormList

OWNERS: dict[str, type] = {
    "app": EyewallApp,
    "replay": EyewallApp,
    "dashboard": DashboardScreen,
    "dashboard_map": DashboardMap,
    "map": MapView,
    "storm_list": StormList,
    "detail": StormDetailScreen,
    "stations": StationTable,
    "buoy": BuoyDetailScreen,
    "watch": WatchlistScreen,
    "outlook": OutlookScreen,
    "alerts": AlertLogScreen,
    "gallery": GalleryPanel,
}


def own_keys(cls: type) -> dict[str, list[str]]:
    """The keys a class binds itself, with the actions they run."""
    keys: dict[str, list[str]] = {}
    for binding in cls.__dict__.get("BINDINGS", []):
        assert isinstance(binding, Binding)
        for key in binding.key.split(","):
            keys.setdefault(key, []).append(binding.action)
    return keys


def test_every_scope_has_an_owner_and_a_help_title() -> None:
    scopes = {entry.scope for entry in nav.KEYS}
    assert scopes <= set(OWNERS) and scopes <= set(nav.TITLES)


@pytest.mark.parametrize("entry", nav.KEYS, ids=lambda e: f"{e.scope}:{e.keys}:{e.action}")
def test_every_key_in_the_table_has_a_binding_on_its_owner(entry: nav.Key) -> None:
    owner = OWNERS[entry.scope]
    bound = own_keys(Screen if entry.action.startswith("app.") else owner)  # Tab is the screen's own
    for key in entry.key_list:
        assert key in bound, f"{owner.__name__} does not bind {key!r}"
        if entry.bind or entry.action.startswith("app."):
            assert entry.action in bound[key], f"{owner.__name__} binds {key!r} to {bound[key]}, not {entry.action}"


@pytest.mark.parametrize("entry", [e for e in nav.KEYS if e.bind], ids=lambda e: f"{e.scope}:{e.action}")
def test_every_bound_action_exists_on_its_owner(entry: nav.Key) -> None:
    name = entry.action.split("(")[0]
    if name.startswith(("screen.", "app.")):
        return  # runs on the screen or the app, which the other tests cover
    owner = OWNERS[entry.scope]
    candidates = [owner]
    if entry.scope in ("dashboard", "outlook"):
        candidates.append(MapView)  # these screens pass map keys on to their map
    assert any(hasattr(cls, f"action_{name}") for cls in candidates), f"{owner.__name__} has no action_{name}"


def test_no_key_is_listed_twice_in_a_scope() -> None:
    seen = Counter((e.scope, k) for e in nav.KEYS for k in e.key_list)
    assert [pair for pair, n in seen.items() if n > 1] == []


def test_only_bound_entries_can_be_in_the_footer() -> None:
    assert all(e.bind for e in nav.KEYS if e.footer)


def test_every_key_in_the_table_appears_on_a_help_row() -> None:
    rows = nav.help_rows()
    words = {word for _, section in rows for keys, _ in section for word in keys.split()}
    for entry in nav.KEYS:
        assert set(nav.tokens_of(entry)) <= words, f"{entry.scope}:{entry.keys} is not in the help"


def test_the_help_screen_prints_the_table_rows() -> None:
    console = Console(width=120, record=True, color_system=None)
    console.print(help_text())
    text = console.export_text()
    for _, section in nav.help_rows():
        for keys, sentence in section:
            assert keys in text and sentence in text
    assert "Top bar" in text and "data ok" in text and "feeds late" in text


def test_the_pinned_keys_are_help_menu_and_back_or_quit() -> None:
    app_actions = {e.action for e in nav.KEYS if e.scope == "app"}
    assert {*nav.PINNED, nav.BACK, nav.QUIT} <= app_actions
    names = {e.action: nav.footer_name(e) for e in nav.KEYS if e.scope == "app"}
    assert (names["help"], names["command_palette"], names["back"], names["quit_top"]) == ("?", "^p", "esc", "q")


def test_ctrl_p_is_a_priority_binding_so_the_menu_opens_from_a_text_field() -> None:
    bound = [b for b in EyewallApp.BINDINGS if isinstance(b, Binding) and b.action == "command_palette"]
    assert len(bound) == 1 and bound[0].priority and bound[0].key == "ctrl+p"
