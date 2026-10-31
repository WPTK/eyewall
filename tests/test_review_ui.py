"""Keys, focus and the gallery across the screens: each test names a behaviour that once failed."""

from __future__ import annotations

from dataclasses import replace

import pytest
from textual.containers import VerticalScroll
from textual.widgets import DataTable, Select, TabbedContent

from eyewall.ui.screens.alerts import AlertLogScreen
from eyewall.ui.screens.dashboard import DashboardScreen
from eyewall.ui.screens.outlook import OutlookScreen
from eyewall.ui.screens.settings import SettingsScreen
from eyewall.ui.screens.small import TooSmallScreen
from eyewall.ui.widgets.gallery import GalleryPanel, ImageView
from tests.test_ui_graphics import ImageSource, app_for, open_gallery, pick, view_text
from tests.ui_support import into_the_storm, press, replay_app, running, screen_text, settle, wait_until

# ---- the detail screen ---------------------------------------------------------------------------------------------


async def test_the_arrows_act_on_a_text_tab_and_a_plain_table_at_once() -> None:
    app = replay_app()
    async with running(app, (120, 30)) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "enter", "3")
        assert isinstance(app.focused, VerticalScroll)
        await press(pilot, "2")
        table = app.screen.query_one("#forecast-table", DataTable)
        assert app.focused is table
        await press(pilot, "down")
        assert table.cursor_row == 1


async def test_a_wide_table_scrolls_sideways_before_the_arrow_changes_tab() -> None:
    app = replay_app()
    async with running(app, (80, 24)) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "enter", "7")
        table = app.screen.query_one("#buoys-table", DataTable)
        tabs = app.screen.query_one(TabbedContent)
        assert app.focused is table and table.max_scroll_x > 0
        await press(pilot, "right")
        assert table.scroll_x > 0 and tabs.active == "tab-buoys"
        for _ in range(40):
            if tabs.active != "tab-buoys":
                break
            await press(pilot, "right")
        assert tabs.active == "tab-tides"  # at the last column the arrow goes on to the next tab


# ---- the dashboard -------------------------------------------------------------------------------------------------


async def test_the_full_map_keeps_the_keyboard_and_the_arrows_pan() -> None:
    app = replay_app()
    async with running(app, (120, 30)) as pilot:
        await into_the_storm(pilot)
        view = app.screen.map_view
        await press(pilot, "M")
        assert app.focused is view
        before = view.viewport
        await press(pilot, "right")
        assert view.viewport != before
        await press(pilot, "M")
        assert app.focused is not None


@pytest.mark.parametrize("size", [(120, 30), (200, 50), (280, 70)])
async def test_hiding_the_map_gives_the_panels_the_whole_width(size: tuple[int, int]) -> None:
    app = replay_app()
    async with running(app, size) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "m")
        screen = app.screen
        assert isinstance(screen, DashboardScreen)
        assert screen.query_one("#side-stack").region.right == size[0]
        await press(pilot, "m")
        assert app.focused is not None


# ---- the other screens ---------------------------------------------------------------------------------------------


async def test_the_outlook_does_not_promise_an_enter_it_does_not_have() -> None:
    app = replay_app()
    async with running(app) as pilot:
        await press(pilot, "O")
        assert isinstance(app.screen, OutlookScreen)
        assert "Enter" not in screen_text(app)


async def test_the_watchlist_rows_stay_inside_the_outlook_on_a_short_terminal() -> None:
    app = replay_app()
    async with running(app, (60, 16)) as pilot:
        await press(pilot, "O")
        left = app.screen.query_one("#outlook-left")
        table = app.screen.query_one("#watchlist")
        assert left.region.contains_region(table.region)


async def test_a_poll_that_adds_no_alert_leaves_the_alert_log_where_it_was() -> None:
    app = replay_app()
    async with running(app, (80, 24)) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "A")
        assert isinstance(app.screen, AlertLogScreen)
        table = app.screen.query_one("#alert-table", DataTable)
        assert table.row_count > 2
        table.move_cursor(row=2)
        app.screen.refresh_data()
        await settle(pilot)
        assert table.cursor_row == 2


async def test_choosing_the_configured_units_after_u_takes_effect() -> None:
    app = replay_app()
    async with running(app) as pilot:
        configured = app.config.units.preset
        await press(pilot, "u")
        assert app.units != configured
        await press(pilot, "S")
        assert isinstance(app.screen, SettingsScreen)
        app.screen.query_one("#units-preset", Select).value = configured
        await press(pilot, "ctrl+s")
        assert app.units == configured


async def test_the_pinning_of_a_station_leaves_the_shown_units_alone() -> None:
    app = replay_app()
    async with running(app) as pilot:
        await press(pilot, "u")
        shown = app.units
        app.apply_config(replace(app.config), persist=False)
        assert app.units == shown


@pytest.mark.parametrize("key", ["O", "w", "A", "S", "g", "slash"])
async def test_no_key_opens_a_screen_over_the_too_small_notice(key: str) -> None:
    app = replay_app()
    async with running(app, (50, 14)) as pilot:
        assert isinstance(app.screen, TooSmallScreen)
        await press(pilot, key)
        assert isinstance(app.screen, TooSmallScreen)
        assert len(app.screen_stack) == 2


# ---- the gallery ---------------------------------------------------------------------------------------------------


class NoImages(ImageSource):
    async def satellite(self, storm):  # type: ignore[no-untyped-def]
        return ()

    async def satellite_product(self, storm, product):  # type: ignore[no-untyped-def]
        return None


async def test_a_gallery_that_opens_empty_says_so() -> None:
    app = app_for(NoImages())
    async with running(app) as pilot:
        await press(pilot, "g")
        panel = app.screen.query_one(GalleryPanel)
        assert panel.items == []
        assert "No graphics yet." in view_text(panel)


async def test_the_old_picture_stops_when_the_next_one_is_loading() -> None:
    source = ImageSource()
    app = app_for(source)
    async with running(app) as pilot:
        panel = await open_gallery(pilot)
        await wait_until(pilot, lambda: panel._frames is not None, 15)
        panel.debounce = 30  # the next fetch stays pending
        await pick(pilot, panel, next(t for t in (i.title for i in panel.items) if t != panel.current.title))
        assert panel._frames is None and panel._timer is None
        assert "Loading..." in view_text(panel)


async def test_a_long_message_wraps_to_the_width_of_the_view() -> None:
    app = replay_app()
    async with running(app, (60, 20)) as pilot:
        view = ImageView()
        await app.mount(view)
        await settle(pilot)
        view.say("Could not load this image.\n\n" + "https://example.test/a/long/path " * 4 + "HTTP 503")
        width = view.size.width
        assert all(line.cell_length <= width for line in view._lines)
        assert "HTTP 503" in "\n".join(line.text for line in view._lines)
