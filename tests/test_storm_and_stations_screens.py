"""The Storm screen, the NHC text screen and the Buoys and gauges list: what they say, and that a click and a key
reach the same places, at the three sizes that matter."""

from __future__ import annotations

from dataclasses import replace

import pytest

from eyewall.config import Config, WatchlistConfig
from eyewall.poll import Freshness, FreshnessState
from eyewall.ui.screens.buoys import BuoysScreen
from eyewall.ui.screens.main import MainScreen
from eyewall.ui.screens.nhc_text import NhcTextScreen
from eyewall.ui.screens.station import StationScreen
from eyewall.ui.screens.storm import StormScreen
from eyewall.ui.widgets.station_list import StationList
from tests.ui_support import into_the_storm, press, replay_app, running, screen_text, settle, wait_until

SIZES = [(80, 24), (100, 40), (200, 50)]
IDS = [f"{w}x{h}" for w, h in SIZES]


def flat(app) -> str:  # type: ignore[no-untyped-def]
    return " ".join(screen_text(app).split())


def stations(app) -> StationList:  # type: ignore[no-untyped-def]
    return app.screen.query_one(StationList)


# ---- the Storm screen -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("size", SIZES, ids=IDS)
async def test_the_storm_screen_leads_with_a_sentence_and_the_exact_nhc_wording(size) -> None:
    app = replay_app()
    async with running(app, size) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "enter")
        assert isinstance(app.screen, StormScreen)
        text = flat(app)
        assert text.count("Hurricane Erin, Category 2, is about") == 1
        assert "Tropical Storm Warning" in text
        full = " ".join(line.text.plain for line in app.screen._lines(max(size[0] - 2, 40)))
        full = " ".join(full.split())
        for exact in (
            "Tropical Storm Warning",
            "Tropical Storm Watch",
            "Storm Surge Warning",
            "conditions expected",
            "conditions possible",
            "Beaufort Inlet, North Carolina to Chincoteague, Virginia",
        ):
            assert exact in full, exact
        assert "ago" in full  # how old the data is, in words
        assert "WHAT THIS MEANS" in full and "IN EFFECT" in full


@pytest.mark.parametrize("size", SIZES, ids=IDS)
async def test_the_storm_screen_keys_and_their_screens(size) -> None:
    app = replay_app()
    async with running(app, size) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "enter", "b")
        assert isinstance(app.screen, BuoysScreen)
        await press(pilot, "escape", "t")
        assert isinstance(app.screen, NhcTextScreen)
        await press(pilot, "escape", "p")
        assert isinstance(app.screen, NhcTextScreen) and app.screen.tab == "chances"
        await press(pilot, "escape", "g")
        assert type(app.screen).__name__ == "GraphicsScreen"
        await press(pilot, "escape")
        assert isinstance(app.screen, StormScreen)


async def test_left_and_right_do_nothing_with_one_storm() -> None:
    app = replay_app()
    async with running(app, (100, 40)) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "enter")
        before = app.screen
        await press(pilot, "right", "left")
        assert app.screen is before and app.screen.storm_id == app.selected


# ---- the NHC text screen ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("size", SIZES, ids=IDS)
async def test_the_text_screen_has_an_issued_header_and_no_banner_when_the_feed_is_fresh(size) -> None:
    app = replay_app()
    async with running(app, size) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "enter", "t")
        assert isinstance(app.screen, NhcTextScreen)
        assert "advisory 38" in flat(app).lower()
        assert not app.screen.query_one("#text-stale").display


@pytest.mark.parametrize("size", SIZES, ids=IDS)
async def test_the_text_screen_says_when_its_text_may_be_out_of_date(size) -> None:
    app = replay_app()
    async with running(app, size) as pilot:
        await into_the_storm(pilot)
        app.poller.freshness = lambda feed: Freshness(FreshnessState.STALE, age=7500.0)  # type: ignore[method-assign]
        await press(pilot, "enter", "t")
        await settle(pilot)
        banner = app.screen.query_one("#text-stale")
        assert banner.display
        assert "Stale" in flat(app) and "may be out of date" in flat(app)


async def test_the_outlook_key_opens_the_outlook_tab_with_the_full_text() -> None:
    app = replay_app()
    async with running(app, (100, 40)) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "O")
        assert isinstance(app.screen, NhcTextScreen) and app.screen.tab == "outlook"
        await press(pilot, "left")
        assert app.screen.tab == "chances"


# ---- the Buoys and gauges list ----------------------------------------------------------------------------------


@pytest.mark.parametrize("size", SIZES, ids=IDS)
async def test_the_list_renders_two_line_rows_with_plain_words(size) -> None:
    app = replay_app()
    async with running(app, size) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "enter", "b")
        assert isinstance(app.screen, BuoysScreen)
        text = flat(app)
        assert "near Erin" in text and "Sorted by nearest" in text
        assert ("Buoy 41002" in text and "Gauge" in text) or size[1] < 30
        assert "nm" in text and "ago" in text
        assert max(len(line) for line in screen_text(app).splitlines()) <= size[0]


@pytest.mark.parametrize("size", SIZES, ids=IDS)
async def test_clicking_a_row_opens_its_station_page(size) -> None:
    app = replay_app()
    async with running(app, size) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "enter", "b")
        first = stations(app).rows[0]
        await pilot.click(StationList, offset=(4, 1))
        await settle(pilot)
        screen = app.screen
        assert isinstance(screen, StationScreen)
        assert screen.station_id == first.id and screen.kind == first.kind


@pytest.mark.parametrize("size", SIZES, ids=IDS)
async def test_the_keyboard_reaches_the_same_page_as_a_click(size) -> None:
    app = replay_app()
    async with running(app, size) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "enter", "b")
        second = stations(app).rows[1]
        await press(pilot, "down", "enter")
        screen = app.screen
        assert isinstance(screen, StationScreen)
        assert screen.station_id == second.id and screen.kind == second.kind
        await press(pilot, "escape")
        assert isinstance(app.screen, BuoysScreen)


@pytest.mark.parametrize("size", SIZES, ids=IDS)
async def test_f_follows_with_a_toast_and_a_star(size) -> None:
    app = replay_app()
    async with running(app, size) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "enter", "b")
        row = stations(app).rows[0]
        assert not row.followed
        await press(pilot, "f")
        await wait_until(pilot, lambda: row.id in app.config.watchlist.ndbc + app.config.watchlist.coops)
        await settle(pilot)
        assert any(f"Following {row.id}" in n.message for n in app._notifications)
        assert stations(app).rows[0].followed
        assert "* " in screen_text(app)
        await press(pilot, "f")
        await wait_until(pilot, lambda: row.id not in app.config.watchlist.ndbc + app.config.watchlist.coops)
        assert any(f"Stopped following {row.id}" in n.message for n in app._notifications)


async def test_s_changes_the_order_and_says_so() -> None:
    app = replay_app()
    async with running(app, (100, 40)) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "enter", "b")
        nearest = [r.key for r in stations(app).rows]
        await press(pilot, "s")
        assert "Sorted by strongest wind" in flat(app)
        assert [r.key for r in stations(app).rows] != nearest
        await press(pilot, "s", "s")
        assert [r.key for r in stations(app).rows] == nearest


async def test_tab_switches_between_near_the_storm_and_your_stations() -> None:
    app = replay_app()
    async with running(app, (100, 40)) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "enter", "b")
        assert app.screen.tab == "near"  # type: ignore[attr-defined]
        await press(pilot, "tab")
        assert app.screen.tab == "yours"  # type: ignore[attr-defined]
        assert "You follow" in flat(app)
        await press(pilot, "tab")
        assert app.screen.tab == "near"  # type: ignore[attr-defined]


async def test_an_empty_your_stations_says_how_to_follow_one() -> None:
    config = replace(Config(), watchlist=WatchlistConfig(ndbc=(), coops=()))
    app = replay_app(config)
    async with running(app, (100, 40)) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "enter", "b", "tab")
        text = flat(app)
        assert "You are not following any stations" in text
        assert "press f to follow it" in text


async def test_slash_opens_the_station_menu_from_the_list() -> None:
    app = replay_app()
    async with running(app, (100, 40)) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "enter", "b", "slash")
        await pilot.pause(0.3)
        assert type(app.screen).__name__ == "CommandPalette"
        await press(pilot, "escape")
        assert isinstance(app.screen, BuoysScreen)


# ---- stations that are quiet never leave a blank screen ---------------------------------------------------------


async def test_a_silent_and_a_dark_station_say_so_in_words_on_the_list() -> None:
    from tests.test_ui_obs import QuietDaySource
    from tests.ui_support import scripted_app

    app = scripted_app(QuietDaySource())
    async with running(app, (100, 40)) as pilot:
        await wait_until(pilot, lambda: "41010" in app.store.latest)
        await press(pilot, "b")
        assert isinstance(app.screen, BuoysScreen)
        await settle(pilot)
        rows = stations(app).rows
        assert rows
        for row in rows:
            assert row.detail.strip(), row  # every row says something
        text = flat(app)
        assert "42001" in text
        for _ in rows:
            await press(pilot, "enter")
            assert isinstance(app.screen, StationScreen)
            await settle(pilot)
            assert app.screen.query_one("#station-lead").region.height >= 1
            assert flat(app).strip()
            await press(pilot, "escape")
            await press(pilot, "down")


async def test_the_main_screen_near_storm_link_opens_the_list() -> None:
    from eyewall.ui.widgets.side_info import SHOW_BUOYS

    app = replay_app()
    async with running(app, (100, 40)) as pilot:
        await into_the_storm(pilot)
        assert isinstance(app.screen, MainScreen)
        panel = app.screen.query_one("#side")
        row = next(i for i, line in enumerate(panel.lines) if line.action == SHOW_BUOYS)  # type: ignore[attr-defined]
        await pilot.click("#side", offset=(3, row))
        await settle(pilot)
        assert isinstance(app.screen, BuoysScreen)


def test_a_stale_station_carries_a_word_and_a_glyph_so_colour_is_never_the_only_cue() -> None:
    from eyewall.palette import FRESHNESS_CUES
    from eyewall.ui import station_view

    cue = FRESHNESS_CUES["stale"]
    for ascii_, glyph in ((False, cue.glyph), (True, cue.ascii_glyph)):
        text = station_view.stale_text(None, ascii_, "No report for 3h.")  # type: ignore[arg-type]
        assert text.startswith(f"{glyph} {cue.word.capitalize()}:") and "No report for 3h." in text
