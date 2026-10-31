"""Pilot journeys through the Textual app: the Erin replay, a quiet live-style source and a dead network."""

from __future__ import annotations

import pytest
from textual.widgets import DataTable, TabbedContent

from eyewall.app import EyewallApp
from eyewall.state.store import storm_key
from eyewall.ui.screens.alerts import AlertLogScreen
from eyewall.ui.screens.dashboard import DashboardScreen
from eyewall.ui.screens.detail import StormDetailScreen
from eyewall.ui.screens.help import HelpScreen
from eyewall.ui.screens.layers import LayerMenu
from eyewall.ui.screens.outlook import OutlookScreen
from eyewall.ui.widgets.map_view import MapView
from tests.ui_support import ScriptedSource, press, replay_app, running, screen_text, scripted_app, wait_until

SIZES = [(80, 24), (140, 45)]


def _adv(app: EyewallApp) -> str | None:
    state = next(iter(app.store.storms.values()))
    return storm_key(state.storm)[0]


@pytest.mark.parametrize("size", SIZES, ids=["80x24", "140x45"])
async def test_dashboard_shows_the_storm_and_the_status_bar(size: tuple[int, int]) -> None:
    app = replay_app()
    async with running(app, size):
        text = screen_text(app)
        assert isinstance(app.screen, DashboardScreen)
        assert "ERIN" in text
        assert "ATLANTIC" in text
        assert "replay" in text
        assert app.selected is not None


async def test_wide_dashboard_has_map_and_panels_and_narrow_folds_them() -> None:
    wide = replay_app()
    async with running(wide, (140, 45)):
        assert wide.screen.has_class("narrow") is False
        assert wide.screen.query_one(MapView).display is True
    small = replay_app()
    async with running(small, (80, 24)):
        assert small.screen.has_class("compact")
        assert small.screen.query_one("#map-pane").display is False


async def test_enter_opens_detail_and_tabs_switch() -> None:
    app = replay_app()
    async with running(app) as pilot:
        await press(pilot, "enter")
        assert isinstance(app.screen, StormDetailScreen)
        tabs = app.screen.query_one(TabbedContent)
        assert tabs.active == "tab-summary"
        await press(pilot, "2")
        assert tabs.active == "tab-forecast"
        table = app.screen.query_one("#forecast-table", DataTable)
        assert table.row_count > 3
        await press(pilot, "right")
        assert tabs.active == "tab-public"
        before = screen_text(app)
        await press(pilot, "t")
        assert screen_text(app) != before
        await press(pilot, "0")
        assert tabs.active == "tab-history"
        await press(pilot, "escape")
        assert isinstance(app.screen, DashboardScreen)


async def test_stepping_advisories_moves_the_replay_and_stops_at_the_ends() -> None:
    app = replay_app()
    async with running(app) as pilot:
        first = _adv(app)
        await press(pilot, "right_square_bracket")
        second = _adv(app)
        assert second != first
        await press(pilot, "left_square_bracket")
        assert _adv(app) == first


async def test_transport_keys_pause_and_change_speed() -> None:
    app = replay_app()
    async with running(app) as pilot:
        was = app.paused
        await press(pilot, "space")
        assert app.paused is not was
        speed = app.speed_index
        await press(pilot, "greater_than_sign")
        assert app.speed_index == min(speed + 1, 3)
        await press(pilot, "less_than_sign", "less_than_sign", "less_than_sign", "less_than_sign", "less_than_sign")
        assert app.speed_index == 0


async def test_overlay_screens_open_and_close() -> None:
    app = replay_app()
    async with running(app) as pilot:
        await press(pilot, "question_mark")
        assert isinstance(app.screen, HelpScreen)
        await press(pilot, "escape")
        await press(pilot, "O")
        assert isinstance(app.screen, OutlookScreen)
        await press(pilot, "escape")
        await press(pilot, "A")
        assert isinstance(app.screen, AlertLogScreen)
        await press(pilot, "escape")
        await press(pilot, "l")
        assert isinstance(app.screen, LayerMenu)
        await press(pilot, "escape")
        assert isinstance(app.screen, DashboardScreen)


async def test_layer_menu_toggle_reaches_the_map() -> None:
    app = replay_app()
    async with running(app) as pilot:
        view = app.screen.query_one(MapView)
        assert view.options.cone is True
        await press(pilot, "l")
        await press(pilot, "down", "down", "space")
        await press(pilot, "enter")
        assert isinstance(app.screen, DashboardScreen)
        assert app.map_options.cone is False


async def test_zoom_flips_the_detail_tier_and_fit_returns() -> None:
    app = replay_app()
    async with running(app) as pilot:
        view = app.screen.query_one(MapView)
        assert view.detailed is True  # the fitted cone around Erin is already close enough for the 10 m coast
        fitted = view.viewport
        for _ in range(4):
            await press(pilot, "minus")
        assert view.detailed is False
        for _ in range(4):
            await press(pilot, "plus")
        assert view.detailed is True
        await press(pilot, "minus", "c", "f")
        assert view.viewport == fitted


async def test_basin_filter_and_units() -> None:
    app = replay_app()
    async with running(app) as pilot:
        await press(pilot, "2")
        assert "ERIN" not in screen_text(app).split("Headline")[0].split("╮")[0]
        assert app.basin_filter == "EP"
        await press(pilot, "a")
        assert "ERIN" in screen_text(app)
        preset = app.units
        await press(pilot, "u")
        assert app.units != preset


async def test_quiet_source_shows_outlook_areas_and_opens_the_outlook() -> None:
    app = scripted_app()
    async with running(app) as pilot:
        text = screen_text(app)
        assert "No tropical cyclones" in text
        assert "Area 1" in text
        await press(pilot, "O")
        assert isinstance(app.screen, OutlookScreen)
        assert "Central Pacific" in screen_text(app) or "Hawaiian" in screen_text(app)


async def test_a_dead_network_marks_feeds_stale_without_crashing() -> None:
    source = ScriptedSource()
    app = scripted_app(source)
    async with running(app) as pilot:
        source.fail = True
        await press(pilot, "r")
        await wait_until(pilot, lambda: app.poller.freshness("storms").failures > 0, 15)
        assert isinstance(app.screen, DashboardScreen)
        assert "Area 1" in screen_text(app)  # the last good outlook stays on screen
        await press(pilot, "O")
        assert isinstance(app.screen, OutlookScreen)
