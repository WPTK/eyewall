"""The storm detail tabs, buoy charts and tide gauges."""

from __future__ import annotations

import pytest

from eyewall.ui.screens.buoy_detail import BuoyDetailScreen
from eyewall.ui.screens.detail import TABS, StormDetailScreen
from eyewall.ui.stations import RANGES_H

MARKERS = {
    "summary": "Position",
    "forecast": "TAU",
    "public": "Advisory 38",
    "discussion": "Discussion 38",
    "probs": "Cumulative chance",
    "ww": "Storm Surge Warning",
    "buoys": "buoys within",
    "tides": "gauges near",
    "graphics": "Cone, 5 day",
    "history": "Best track",
}


@pytest.mark.parametrize(("index", "tab"), [(i, t) for i, (t, _) in enumerate(TABS)], ids=[t for t, _ in TABS])
async def test_every_detail_tab(journey, size, index, tab) -> None:
    async with journey(size) as j:
        await j.keys("enter")
        assert isinstance(j.screen, StormDetailScreen)
        await j.keys(str((index + 1) % 10))
        assert j.tab() == tab
        j.see("ERIN", MARKERS[tab])
        await j.shot(f"tab-{tab}")


async def test_detail_tab_keys_and_advisory_toggle(journey, size) -> None:
    async with journey(size) as j:
        await j.keys("enter", "right")
        assert j.tab() == "forecast"
        await j.keys("left", "left")
        assert j.tab() == "history"  # wraps round
        await j.keys("3")
        before = j.text()
        await j.keys("t")
        assert j.text() != before
        await j.shot("forecast-advisory-text")
        await j.keys("t")
        after = j.text()
        changed = [
            (a, b)
            for a, b in zip(before.splitlines(), after.splitlines(), strict=False)
            if a != b and set(a + b) - set("━╸╺ ")  # the tab underline is animated; leave it out
        ]
        assert not changed, f"toggling twice changed the screen: {changed}"
        await j.keys("escape")
        assert not isinstance(j.screen, StormDetailScreen)


async def test_buoy_list_charts_ranges_and_pin(journey, size) -> None:
    async with journey(size) as j:
        app = j.app
        await j.keys("b")
        assert isinstance(j.screen, StormDetailScreen) and j.tab() == "buoys"
        await j.shot("buoy-list")
        await j.keys("enter")
        assert isinstance(j.screen, BuoyDetailScreen)
        station = j.screen.station_id
        j.see("Pressure (", "Wind and gust (", "Wave height (", f"{RANGES_H[0]} h")
        await j.shot("charts-24h")
        for hours in (*RANGES_H[1:], RANGES_H[0]):
            await j.keys("h")
            assert f"{hours} h" in j.text().splitlines()[0]
            await j.shot(f"range-{hours}h")
        if size[0] < 110:
            await j.keys("i")
            j.see("Observed")
            await j.shot("observation")
            await j.keys("i")
        watched = station in app.config.watchlist.ndbc
        await j.keys("p")
        await j.settle()
        assert (station in app.config.watchlist.ndbc) != watched
        await j.shot("pin-toggled")
        await j.keys("p")
        await j.settle()
        assert (station in app.config.watchlist.ndbc) == watched
        await j.keys("u")
        await j.shot("units-cycled")
        await j.keys("escape")
        assert isinstance(j.screen, StormDetailScreen)


async def test_tide_gauges_list_and_pin(journey, size) -> None:
    async with journey(size) as j:
        app = j.app
        await j.keys("enter", "8")
        assert j.tab() == "tides"
        j.see("Residual")
        await j.shot("tide-list")
        before = set(app.config.watchlist.coops)
        await j.keys("p")
        await j.settle()
        assert set(app.config.watchlist.coops) != before
        await j.shot("tide-pinned")
        await j.keys("p")
        await j.settle()
        assert set(app.config.watchlist.coops) == before
