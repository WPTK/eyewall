"""Small helpers the checks share: snapshots of observable state and assertions that say what was seen."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from textual.command import CommandPalette

from eyewall.ui.screens.main import MainScreen
from eyewall.ui.widgets.map_view import MapView
from tests.uat.inventory.worlds import W


def stack_names(w: W) -> list[str]:
    return [type(s).__name__ for s in w.app.screen_stack]


def top_name(w: W) -> str:
    return type(w.screen).__name__


def expect_top(w: W, name: str, why: str = "") -> None:
    assert top_name(w) == name, f"expected {name} on top {why}, got {stack_names(w)}"


def expect_palette(w: W) -> CommandPalette:
    assert isinstance(w.screen, CommandPalette), f"expected the menu, got {stack_names(w)}"
    return w.screen


def main_of(w: W) -> MainScreen:
    for screen in w.app.screen_stack:
        if isinstance(screen, MainScreen):
            return screen
    raise AssertionError("no main screen in the stack")


def map_of(w: W) -> MapView:
    return main_of(w).map_view


def toasts(w: W) -> str:
    return " | ".join(f"{n.message}#{id(n)}" for n in w.app._notifications)


def clear_toasts(w: W) -> None:
    w.app.clear_notifications()


async def add_second_storm(w: W) -> str:
    """Put a second storm in the store (a copy of the first, renamed and moved) so storm-to-storm keys can be tested.
    Returns its id. Nothing polls in the replay, so it stays until the test ends."""
    store = w.app.store
    first = next(iter(store.storms.values()))
    twin_id = "al062025"
    if twin_id not in store.storms:
        storm = replace(
            first.storm,
            id=twin_id,
            name="FERNAND",
            bin_number="AT6",
            lat=(first.storm.lat or 30.0) + 4.0,
            lon=(first.storm.lon or -70.0) - 6.0,
            intensity_kt=45,
        )
        store.storms[twin_id] = replace(first, storm=storm)
    main = main_of(w)
    main.refresh_data()
    await w.settle()
    return twin_id


def lone_mark(view: MapView, kind: str) -> tuple[Any, tuple[int, int]]:
    """A mark of this kind that no other mark is within a cell of, and its cell."""
    for mark, cell in view.hits.drawn:
        if mark.kind == kind and view.hits.at(*cell) == (mark,):
            return mark, cell
    raise AssertionError(f"no lone {kind} mark on the map (drawn: {[m for m, _ in view.hits.drawn]})")


def crowded_cell(view: MapView) -> tuple[int, int]:
    for r in range(view.size.height):
        for c in range(view.size.width):
            if len(view.hits.at(c, r)) > 1:
                return c, r
    raise AssertionError("no overlapping marks")


def empty_cell(view: MapView) -> tuple[int, int]:
    for r in range(view.size.height - 3, -1, -1):
        for c in range(view.size.width):
            if not view.hits.at(c, r):
                return c, r
    raise AssertionError("no empty map cell")
