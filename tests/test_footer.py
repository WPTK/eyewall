"""The footer lists only the keys that work where the focus is, and never loses `?`, the menu key or Esc/q."""

from __future__ import annotations

import pytest
from textual.widgets import TabbedContent

from eyewall.poll import Freshness, FreshnessState
from eyewall.ui.chrome import FooterBar, footer_items
from eyewall.ui.screens.buoy_detail import BuoyDetailScreen
from eyewall.ui.screens.dashboard import DashboardScreen
from eyewall.ui.screens.detail import TABS
from tests.ui_support import into_the_storm, press, replay_app, running, screen_text, settle

SIZES = [(80, 24), (140, 45)]


def bottom(app) -> str:  # type: ignore[no-untyped-def]
    return screen_text(app).splitlines()[-1]


async def show_tab(pilot, tab: str) -> str:  # type: ignore[no-untyped-def]
    """Jump to a detail tab and return the bottom row once the footer has followed."""
    await pilot.press(str(([t for t, _ in TABS].index(tab) + 1) % 10))
    await pilot.pause()
    return bottom(pilot.app)


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


# ---- the dashboard --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("size", SIZES)
async def test_dashboard_footer_is_one_row_and_follows_the_focus(size: tuple[int, int]) -> None:
    app = replay_app()
    async with running(app, size) as pilot:
        await into_the_storm(pilot)
        seen = {}
        for _ in range(6):
            await pilot.pause()
            row = one_row(app, size[0])
            seen.setdefault(type(app.focused).__name__, row)
            await pilot.press("tab")
        assert "enter detail" in seen["StormList"]
        if size[0] >= 110:  # the map is on screen
            assert "+/- zoom" in seen["DashboardMap"] and seen["DashboardMap"] != seen["StormList"]


async def test_dashboard_map_lists_its_own_keys_and_the_list_does_not() -> None:
    app = replay_app()
    async with running(app, (140, 45)) as pilot:
        await into_the_storm(pilot)
        in_list = labels(app)
        assert in_list == ["detail", "buoys", "map"]
        app.screen.map_view.focus()
        await pilot.pause()
        assert "zoom" in bottom(app) and "center" in bottom(app) and "layers" in bottom(app)
        assert labels(app)[:4] == ["zoom", "fit", "center", "layers"]


async def test_footer_follows_the_focus_without_waiting_for_the_clock() -> None:
    app = replay_app()
    async with running(app, (140, 45)) as pilot:
        await into_the_storm(pilot)
        before = bottom(app)
        app.screen.map_view.focus()
        await pilot.pause()  # no refresh_status call and no one-second pulse in between
        assert bottom(app) != before and "zoom" in bottom(app)


async def test_the_narrow_dashboard_tabs_list_the_same_keys_as_the_list() -> None:
    app = replay_app()
    async with running(app, (100, 30)) as pilot:
        await into_the_storm(pilot)
        app.screen.query_one("#side-tabs", TabbedContent).focus()
        await pilot.pause()
        assert labels(app) == ["detail", "buoys", "map"]
        one_row(app, 100)


# ---- the storm detail tabs ------------------------------------------------------------------------------------


@pytest.mark.parametrize("size", SIZES)
async def test_every_detail_tab_keeps_one_row_and_lists_only_working_keys(size: tuple[int, int]) -> None:
    app = replay_app()
    async with running(app, size) as pilot:
        await into_the_storm(pilot)
        await pilot.press("enter")
        await pilot.pause()
        rows = {}
        for tab, _ in TABS:
            await show_tab(pilot, tab)
            one_row(app, size[0])
            rows[tab] = labels(app)
        assert "tcp/tcm" in rows["public"]
        assert not any("tcp/tcm" in shown for tab, shown in rows.items() if tab != "public")
        assert all(("pin" in shown) == (tab in ("buoys", "tides")) for tab, shown in rows.items())
        assert all(("charts" in shown) == (tab == "buoys") for tab, shown in rows.items())
        assert "open" in rows["graphics"] and "copy URL" in rows["graphics"]
        assert len({tuple(shown) for shown in rows.values()}) > 3  # it changes with the tab


async def test_keys_that_are_not_listed_do_nothing() -> None:
    app = replay_app()
    async with running(app, (140, 45)) as pilot:
        await into_the_storm(pilot)
        await pilot.press("enter")
        await pilot.pause()
        screen = app.screen
        await show_tab(pilot, "summary")
        before, toasts = screen.show_tcm, len(app._notifications)
        await pilot.press("t")
        await pilot.press("p")
        await pilot.pause()
        assert screen.show_tcm is before
        assert screen.query_one("#detail-tabs", TabbedContent).active == "tab-summary"
        assert len(app._notifications) == toasts
        await show_tab(pilot, "public")
        await pilot.press("t")
        assert screen.show_tcm is not before


async def test_a_tide_gauge_row_lists_no_enter() -> None:
    app = replay_app()
    async with running(app, (140, 45)) as pilot:
        await into_the_storm(pilot)
        await pilot.press("enter")
        await pilot.pause()
        await show_tab(pilot, "tides")
        assert "charts" not in bottom(app) and "pin" in bottom(app)


# ---- other screens --------------------------------------------------------------------------------------------


async def test_the_watchlist_lists_its_keys_in_the_footer_not_in_its_header() -> None:
    app = replay_app()
    async with running(app, (140, 45)) as pilot:
        await pilot.press("w")
        await pilot.pause()
        row = one_row(app, 140)
        for text in ("a add", "d remove", "tab other table", "esc back", "enter charts"):
            assert text in row, row
        assert "Enter: charts" not in screen_text(app)


async def test_the_buoy_charts_list_range_pin_and_back() -> None:
    app = replay_app()
    async with running(app, (140, 45)) as pilot:
        await into_the_storm(pilot)
        app.open_buoy("41002")
        for _ in range(50):  # until the buoy screen is up
            await pilot.pause()
            if isinstance(app.screen, BuoyDetailScreen):
                break
        await pilot.pause()
        row = one_row(app, 140)
        assert "h range" in row and "p pin" in row and "esc back" in row


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


@pytest.mark.parametrize("size", [(80, 24), (100, 50), (120, 30), (200, 50), (280, 70)])
async def test_the_forecast_table_fits_without_scrolling_sideways(size: tuple[int, int]) -> None:
    from textual.widgets import DataTable

    app = replay_app()
    async with running(app, size) as pilot:
        await into_the_storm(pilot)
        await pilot.press("enter")
        await pilot.pause()
        await show_tab(pilot, "forecast")
        table = app.screen.query_one("#forecast-table", DataTable)
        assert table.row_count > 5 and table.virtual_size.width <= table.size.width


@pytest.mark.parametrize("screen_key", ["g", "enter", "b"])
async def test_every_screen_rebuilds_its_footer_after_the_too_small_screen(screen_key: str) -> None:
    app = replay_app()
    async with running(app, (120, 30)) as pilot:
        await into_the_storm(pilot)
        await press(pilot, screen_key)
        assert not isinstance(app.screen, DashboardScreen)
        await pilot.resize_terminal(59, 24)
        await settle(pilot)
        await pilot.resize_terminal(60, 16)
        await settle(pilot)
        await pilot.resize_terminal(120, 30)
        await settle(pilot)
        assert one_row(app, 120).endswith("esc back")
