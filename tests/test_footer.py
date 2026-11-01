"""The footer lists only the keys that work where the focus is, and never loses `?`, the menu key or Esc/q."""

from __future__ import annotations

import pytest

from eyewall.poll import Freshness, FreshnessState
from eyewall.ui.chrome import FooterBar, footer_items
from eyewall.ui.screens.main import MainScreen
from eyewall.ui.screens.station import StationScreen
from tests.ui_support import into_the_storm, press, replay_app, running, screen_text, settle

SIZES = [(80, 24), (140, 45)]


def bottom(app) -> str:  # type: ignore[no-untyped-def]
    return screen_text(app).splitlines()[-1]


def labels(app) -> list[str]:  # type: ignore[no-untyped-def]
    """The words of the screen's own footer keys, in order, apart from the pinned group."""
    return [item.label for item in footer_items(app.screen)[0]]


def one_row(app, width: int) -> str:  # type: ignore[no-untyped-def]
    """The bottom row: the footer is one row high, fits the width and ends with the pinned group."""
    bar = app.screen.query_one(FooterBar)
    assert bar.region.height == 1
    row = bottom(app).rstrip()
    assert len(row) <= width, row
    assert row.endswith(("esc back", "q quit")) or row.endswith(("^p esc", "^p q")), row
    return row


# ---- the main screen ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("size", SIZES)
async def test_main_footer_is_one_row_and_lists_the_map_keys(size: tuple[int, int]) -> None:
    app = replay_app()
    async with running(app, size) as pilot:
        await into_the_storm(pilot)
        assert type(app.focused).__name__ == "MainMap"
        one_row(app, size[0])
        assert labels(app) == ["zoom", "fit", "center", "layers", "open", "buoys", "NHC text"]


async def test_footer_follows_the_focus_without_waiting_for_the_clock() -> None:
    app = replay_app()
    async with running(app, (140, 45)) as pilot:
        await into_the_storm(pilot)
        assert "zoom" in bottom(app)
        app.screen.set_focus(None)
        await pilot.pause()  # no refresh_status call and no one-second pulse in between
        assert "zoom" not in bottom(app) and "open" in bottom(app)


# ---- the storm screen and the NHC text -------------------------------------------------------------------------


@pytest.mark.parametrize("size", SIZES)
async def test_the_storm_and_text_screens_keep_one_row_and_list_only_working_keys(size: tuple[int, int]) -> None:
    app = replay_app()
    async with running(app, size) as pilot:
        await into_the_storm(pilot)
        await pilot.press("enter")
        await pilot.pause()
        one_row(app, size[0])
        storm = labels(app)
        assert "buoys" in storm and "text" in storm and "pictures" in storm
        await pilot.press("t")
        await pilot.pause()
        one_row(app, size[0])
        text = labels(app)
        assert "buoys" not in text and "text" not in text
        assert text != storm


async def test_keys_that_are_not_listed_do_nothing() -> None:
    app = replay_app()
    async with running(app, (140, 45)) as pilot:
        await into_the_storm(pilot)
        await pilot.press("enter")
        await pilot.pause()
        screen = app.screen
        toasts = len(app._notifications)
        await pilot.press("f", "s", "h")
        await pilot.pause()
        assert app.screen is screen
        assert len(app._notifications) == toasts


# ---- other screens --------------------------------------------------------------------------------------------


async def test_the_buoys_screen_lists_its_keys_in_the_footer_not_in_its_header() -> None:
    app = replay_app()
    async with running(app, (140, 45)) as pilot:
        await into_the_storm(pilot)
        await pilot.press("enter", "b")
        await pilot.pause()
        row = one_row(app, 140)
        for text in ("enter open", "f follow", "s sort", "esc back"):
            assert text in row, row
        assert "Enter: open" not in screen_text(app)


async def test_the_station_screen_lists_range_follow_map_and_back() -> None:
    app = replay_app()
    async with running(app, (140, 45)) as pilot:
        await into_the_storm(pilot)
        app.open_station("ndbc", "41002")
        for _ in range(50):  # until the station screen is up
            await pilot.pause()
            if isinstance(app.screen, StationScreen):
                break
        await pilot.pause()
        row = one_row(app, 140)
        assert "h 24/48/72 h" in row and "f follow" in row and "m map" in row and "esc back" in row


# ---- the crowded worst case -----------------------------------------------------------------------------------


@pytest.mark.parametrize("width", [70, 80, 90, 110])
async def test_help_survives_a_crowded_status_at_every_width(width: int) -> None:
    app = replay_app()
    async with running(app, (width, 24)) as pilot:
        app.poller.freshness = lambda feed: Freshness(FreshnessState.STALE, age=7500.0)  # type: ignore[method-assign]
        app.poller.active = lambda feed: True  # type: ignore[method-assign]
        app.alert_log = [object()] * 12  # type: ignore[list-item]
        await pilot.pause(0.3)
        assert "? help  ^p menu  q quit" in one_row(app, width)
        # A replay speaks for the health slot ("paused" in the short form), whatever the feeds say.
        assert "paused" in screen_text(app).splitlines()[0]


async def test_under_70_columns_the_pinned_keys_lose_their_words_but_stay() -> None:
    app = replay_app()
    async with running(app, (69, 24)) as pilot:
        await pilot.pause()
        assert bottom(app).rstrip().endswith("? ^p q") and "help" not in bottom(app)


@pytest.mark.parametrize("screen_key", ["g", "enter", "b"])
async def test_every_screen_rebuilds_its_footer_after_the_too_small_screen(screen_key: str) -> None:
    app = replay_app()
    async with running(app, (120, 30)) as pilot:
        await into_the_storm(pilot)
        await press(pilot, screen_key)
        assert not isinstance(app.screen, MainScreen)
        await pilot.resize_terminal(59, 24)
        await settle(pilot)
        await pilot.resize_terminal(60, 16)
        await settle(pilot)
        await pilot.resize_terminal(120, 30)
        await settle(pilot)
        assert one_row(app, 120).endswith("esc back")
