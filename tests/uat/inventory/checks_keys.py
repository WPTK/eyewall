"""Per-key checks: press each advertised key on every screen that advertises it and require an observable change.

"Observable" is the snapshot below: the screen stack, the screen text, the focused widget's own state, the app's
unit/basin/replay settings, the map viewport and marked mark, and the toasts. A key that changes none of them is dead.
Keys that are documented to do nothing in a place (back at the root) are listed in NOOP_OK with the reason.
"""

from __future__ import annotations

from typing import Any

from textual.widgets import DataTable, Input, OptionList, Select, SelectionList, Switch, Tabs

from tests.uat.inventory import helpers
from tests.uat.inventory.inventory import CHROME_SCREENS, DIALOGS, interactive_widgets, observe, static_key_items
from tests.uat.inventory.registry import World, check
from tests.uat.inventory.worlds import W

GOTO = {
    "main": "main",
    "storm": "storm",
    "text": "text",
    "buoys": "buoys_near",
    "station": "station_buoy",
    "alerts": "alerts",
    "graphics": "graphics",
    "help": "help",
    "feeds": "feeds",
    "settings": "settings",
    "layers": "layers",
}
NOOP_OK = {
    ("main", "escape"): "back at the root has nothing to go back to",
    ("main", "backspace"): "back at the root has nothing to go back to",
    ("main", "m"): "already on the map",
    ("main", "q"): "quits (recorded by the exit hook)",
}
NOOP_OK_ANY = {"q": "q quits only from the root screen; elsewhere it does nothing"}
NOOP_OK[("graphics", "g")] = "already on the pictures"
NOOP_OK[("station", "tab")] = "README: only on a short screen, where the charts do not all fit"
DEMO = World("demo", (120, 30))
QUIET = World("quiet", (120, 30))


def widget_state(widget: Any) -> Any:
    if isinstance(widget, OptionList):
        return ("opt", widget.highlighted, widget.option_count)
    if isinstance(widget, Tabs):
        return ("tabs", widget.active)
    if isinstance(widget, DataTable):
        return ("table", widget.cursor_coordinate, widget.row_count)
    if isinstance(widget, Input):
        return ("input", widget.value)
    if isinstance(widget, Select):
        return ("select", widget.value, widget.expanded)
    if isinstance(widget, Switch):
        return ("switch", widget.value)
    if isinstance(widget, SelectionList):
        return ("sel", widget.highlighted, tuple(widget.selected))
    return None


def snap(w: W) -> tuple[Any, ...]:
    app = w.app
    try:
        view = helpers.map_of(w)
        mapstate = (view.viewport, view.focused_mark, view.cursor)
    except Exception:
        mapstate = None
    sels = tuple(widget_state(x) for x in interactive_widgets(w.screen))
    return (
        tuple(helpers.stack_names(w)),
        w.text(),
        sels,
        app.units,
        app.basin_filter,
        app.paused,
        app.speed_index,
        mapstate,
        helpers.toasts(w),
        getattr(app, "exits", 0),
        app.selected,
    )


async def ensure(w: W, screen: str) -> None:
    """Open the screen unless it is already on top (a key that leaves it sends the next item back through goto)."""
    expected = (CHROME_SCREENS | DIALOGS)[screen]
    depth = 1 if screen == "main" else 2
    if type(w.screen) is expected and len(w.app.screen_stack) == depth and not w.screen.query("MarkChooser"):
        return
    await w.goto(GOTO[screen])
    observe(w, GOTO[screen])


def install_exit_hook(w: W) -> None:
    app = w.app
    app.exits = 0  # type: ignore[attr-defined]

    def fake_exit(*a: Any, **k: Any) -> None:
        app.exits += 1  # type: ignore[attr-defined]

    app.exit = fake_exit  # type: ignore[method-assign]


@check(DEMO)
async def keys_demo(w: W, rec: Any) -> None:
    install_exit_hook(w)
    await helpers.add_second_storm(w)
    items = sorted(i for i in static_key_items() if i.split(":")[1] in GOTO)
    for item in items:
        _, screen, key = item.split(":", 2)
        if screen == "main" and key == "R":
            continue
        reason = NOOP_OK.get((screen, key)) or (NOOP_OK_ANY.get(key) if screen != "main" else None)
        try:
            await ensure(w, screen)
            if len(w.app.storm_states()) < 2:
                await helpers.add_second_storm(w)  # `r` and the replay keys reload the store and drop the extra storm
            if screen == "main":
                # an earlier key (1, 2, 3) must not leave the storms hidden (and `a` needs a filter to clear)
                w.app.basin_filter = None
                if helpers.main_of(w)._full_map and key != "M":
                    helpers.main_of(w).action_full_map()
                w.app.selected = w.storm_id
                if key == "a":
                    await w.press("1")
            before = snap(w)
            await w.press(key)
            after = snap(w)
            if before == after and not reason:
                rec(item, f"pressing {key!r} on {screen} changed nothing observable ({helpers.stack_names(w)}, selected {w.app.selected}, storms {len(w.app.storm_states())})")
            else:
                rec(item)
        except Exception as exc:
            rec(item, f"{type(exc).__name__}: {exc}")
