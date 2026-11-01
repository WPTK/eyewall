"""Palette entries, R (replay, quiet day only), and map-to-list linkage."""

from __future__ import annotations

from typing import Any

from textual.widgets import Input, OptionList

from eyewall.ui import nav
from tests.uat.inventory import helpers
from tests.uat.inventory.checks_keys import DEMO, QUIET, install_exit_hook, snap
from tests.uat.inventory.registry import check
from tests.uat.inventory.worlds import W


async def via_palette(w: W, title: str) -> bool:
    await w.goto("main")
    before = snap(w)
    await w.pilot.press("ctrl+p")
    await w.pilot.pause(0.3)
    palette = helpers.expect_palette(w)
    palette.query_one(Input).value = title
    await w.pilot.pause(0.4)
    await w.pilot.press("enter")
    await w.pilot.pause(0.3)
    await w.settle()
    return before != snap(w)


@check(DEMO)
async def palette_demo(w: W, rec: Any) -> None:
    await helpers.add_second_storm(w)
    install_exit_hook(w)
    titles = sorted({e.menu for e in nav.KEYS if e.menu} - {"Replay Hurricane Erin"})
    for title in [*titles, "Open storm"]:
        item = f"palette:{title}"
        try:
            rec(item, None if await via_palette(w, title) else f"choosing {title!r} in the menu changed nothing")
        except Exception as exc:
            rec(item, f"{type(exc).__name__}: {exc}")
    try:
        await w.goto("main")
        await w.pilot.press("slash")
        await w.pilot.pause(0.3)
        rec("palette:Find station", None if "Palette" in type(w.screen).__name__ else f"/ opened {helpers.top_name(w)}")
    except Exception as exc:
        rec("palette:Find station", f"{type(exc).__name__}: {exc}")


@check(QUIET)
async def replay_from_quiet(w: W, rec: Any) -> None:
    install_exit_hook(w)
    try:
        await w.goto("main")
        before = snap(w)
        await w.press("R")
        await w.pilot.pause(0.5)
        await w.settle()
        rec("key:main:R", None if snap(w) != before else "R on a quiet day did not start the replay")
    except Exception as exc:
        rec("key:main:R", f"{type(exc).__name__}: {exc}")
    try:
        await w.goto("main")
        before = snap(w)
        rec("palette:Replay Hurricane Erin", None if await via_palette(w, "Replay Hurricane Erin") else "choosing the replay in the menu changed nothing")
    except Exception as exc:
        rec("palette:Replay Hurricane Erin", f"{type(exc).__name__}: {exc}")


@check(DEMO)
async def linkage(w: W, rec: Any) -> None:
    """Map and list linkage. The Home side panel lists storms; stations are counts and links, with no rows beside the map."""
    await helpers.add_second_storm(w)
    names = ("claim:link-storm-selection-visible", "claim:link-storm-selection-sticks")
    try:
        await w.goto("main")
        a = w.text()
        first = w.app.selected
        await w.press("j")
        b = w.text()
        moved = w.app.selected
        await w.after_tick()
        rec(names[0], None if a != b else "j moved the selected storm but nothing on screen shows which one is selected")
        rec(names[1], None if w.app.selected == moved != first else "the selected storm changed back after a refresh tick")
    except Exception as exc:
        for n in names:
            rec(n, f"{type(exc).__name__}: {exc}")
    main = await w.goto("main")
    lists = [x for x in main.query(OptionList) if x.display and x.option_count]
    why = "the Home screen has no station or alert list beside the map: clicking a buoy or gauge mark opens its page and highlights no row"
    rec("claim:link-mark-to-row", None if lists else why)
    rec("claim:link-row-to-mark", None if lists else "the Home screen has no list rows to select, so no row can highlight its mark")
    try:
        await w.goto("station_buoy")
        station = w.screen
        lat, lon = station._position()
        await w.press("m")
        await w.after_tick()
        view = helpers.map_of(w).viewport
        near = view is not None and abs(view.center_lat - lat) < 0.5 and abs(view.center_lon - lon) < 0.5
        rec("claim:link-station-to-mark", None if near else f"m on a station page did not centre the map on the station ({lat}, {lon}); centre is {view and (view.center_lat, view.center_lon)}")
    except Exception as exc:
        rec("claim:link-station-to-mark", f"{type(exc).__name__}: {exc}")
