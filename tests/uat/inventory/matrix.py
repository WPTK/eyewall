"""The state matrix: states x screens x sizes, one app launch per (state, size), every screen visited inside it.

Sizes: every state at 120x30; the two states people live in (demo, quiet) also at 80x24, 100x30, 200x50 and 280x70.
Dialogs that do not depend on app state (settings, layers, menus, chooser) are visited in the demo state only."""

from __future__ import annotations

from eyewall.ui.widgets.map_view import MapView
from tests.uat.inventory.inventory import observe
from tests.uat.inventory.registry import World
from tests.uat.inventory.rules import violations
from tests.uat.inventory.worlds import SIZES, STATES, W, launch

STATE_SCREENS = (
    "main",
    "full_map",
    "storm",
    "text",
    "buoys_near",
    "buoys_yours",
    "station_buoy",
    "station_gauge",
    "alerts",
    "graphics",
    "help",
    "feeds",
)
DEMO_ONLY = ("settings", "layers", "palette", "search")
EXTRA_SIZE_SCREENS = ("main", "full_map", "storm", "buoys_near", "station_buoy", "alerts")  # the layout-sensitive ones
BASE_SIZE = (120, 30)
WORLDS = [World(s, BASE_SIZE) for s in STATES] + [
    World(s, size) for s in ("demo", "quiet") for size in SIZES if size != BASE_SIZE and (s == "demo" or size[0] in (80, 200))
]
def screens_of(world: World) -> tuple[str, ...]:
    if world.size != BASE_SIZE:
        return EXTRA_SIZE_SCREENS
    return (*STATE_SCREENS, *(DEMO_ONLY if world.state == "demo" else ()))

CELLS = [
    (w.state, name, w.size) for w in WORLDS for name in (*screens_of(w), "chooser")
]
_CACHE: dict[World, dict[str, list[tuple[str, str]] | str]] = {}


async def open_chooser(w: W) -> bool:
    """Click a map cell where several marks overlap; True when the chooser dialog opened."""
    main = await w.goto("main")
    view = main.query_one(MapView)
    for r in range(view.size.height):
        for c in range(view.size.width):
            if len(view.hits.at(c, r)) > 1:
                await w.click(view, (c, r))
                return type(w.screen).__name__ == "MarkChooser"
    return False


async def results_for(world: World) -> dict[str, list[tuple[str, str]] | str]:
    """screen name -> violations (or a skip note as a string) for every screen in this state at this size."""
    if world in _CACHE:
        return _CACHE[world]
    out: dict[str, list[tuple[str, str]] | str] = {}
    async with launch(world) as w:
        for name in screens_of(world):
            try:
                await w.goto(name)
                observe(w, name)
                out[name] = violations(w, name)
            except Exception as exc:
                out[name] = [("crash", f"{type(exc).__name__}: {exc}")]
        try:
            if await open_chooser(w):
                out["chooser"] = violations(w, "chooser")
            else:
                out["chooser"] = "no overlapping marks in this state"
        except Exception as exc:
            out["chooser"] = [("crash", f"{type(exc).__name__}: {exc}")]
    _CACHE[world] = out
    from tests.uat.inventory.runner import save_dynamic

    save_dynamic(f"matrix-{world.id}")
    return out
