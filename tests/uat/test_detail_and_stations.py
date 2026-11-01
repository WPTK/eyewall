"""The Storm screen, the NHC text tabs, the buoys and gauges list and the station pages."""

from __future__ import annotations

import pytest

from eyewall.ui.nhc_text import STORM_TABS
from eyewall.ui.screens.buoys import BuoysScreen
from eyewall.ui.screens.nhc_text import NhcTextScreen
from eyewall.ui.screens.station import StationScreen
from eyewall.ui.screens.storm import StormScreen
from eyewall.ui.stations import RANGES_H
from eyewall.ui.widgets.station_list import StationList


async def test_the_storm_screen_reads_in_plain_words(journey, size) -> None:
    async with journey(size) as j:
        await j.keys("enter")
        assert isinstance(j.screen, StormScreen)
        j.see("IN EFFECT", "WHAT THIS MEANS")
        await j.shot("storm")
        await j.keys("escape")
        assert not isinstance(j.screen, StormScreen)


@pytest.mark.parametrize("tab", STORM_TABS)
async def test_every_text_tab(journey, size, tab) -> None:
    async with journey(size) as j:
        await j.keys("enter", "t")
        assert isinstance(j.screen, NhcTextScreen)
        for _ in range(len(STORM_TABS)):
            if j.screen.tab == tab:
                break
            await j.keys("right")
        assert j.screen.tab == tab
        j.see("ERIN")
        await j.shot(f"text-{tab}")


async def test_text_tab_keys_wrap_round(journey, size) -> None:
    async with journey(size) as j:
        await j.keys("enter", "t")
        first = j.screen.tab
        await j.keys("left")
        assert j.screen.tab != first
        await j.keys("right")
        assert j.screen.tab == first
        await j.keys("escape")
        assert isinstance(j.screen, StormScreen)


async def test_buoy_list_charts_ranges_and_follow(journey, size) -> None:
    async with journey(size) as j:
        app = j.app
        await j.keys("enter", "b")
        assert isinstance(j.screen, BuoysScreen)
        await j.shot("buoy-list")
        await j.keys("enter")
        assert isinstance(j.screen, StationScreen)
        station = j.screen.station_id
        j.see(station, f"{RANGES_H[0]} h")
        await j.shot("charts-24h")
        for hours in (*RANGES_H[1:], RANGES_H[0]):
            await j.keys("h")
            assert f"{hours} h" in " ".join(j.text().splitlines()[:6])
            await j.shot(f"range-{hours}h")
        await j.keys("i")
        assert "average over about 8 minutes" in " ".join(j.text().split())
        await j.shot("about-buoy-winds")
        await j.keys("i", "r")
        await j.shot("readings")
        await j.keys("r")
        followed = station in app.config.watchlist.ndbc + app.config.watchlist.coops
        await j.keys("f")
        await j.settle()
        assert (station in app.config.watchlist.ndbc + app.config.watchlist.coops) != followed
        await j.shot("follow-toggled")
        await j.keys("f")
        await j.settle()
        assert (station in app.config.watchlist.ndbc + app.config.watchlist.coops) == followed
        await j.keys("u")
        await j.shot("units-cycled")
        await j.keys("escape")
        assert isinstance(j.screen, BuoysScreen)


async def test_tide_gauge_page_and_follow(journey, size) -> None:
    async with journey(size) as j:
        app = j.app
        await j.keys("enter", "b")
        stations = j.screen.query_one(StationList)
        gauge = next(r for r in stations.rows if r.kind == "coops")
        stations.highlighted = [r.key for r in stations.rows].index(gauge.key)
        await j.settle()
        await j.shot("gauge-in-list")
        await j.keys("enter")
        assert isinstance(j.screen, StationScreen) and not j.screen.is_buoy
        await j.settle()
        await j.shot("gauge-page")
        before = set(app.config.watchlist.coops)
        await j.keys("f")
        await j.settle()
        assert set(app.config.watchlist.coops) != before
        await j.keys("f")
        await j.settle()
        assert set(app.config.watchlist.coops) == before
