"""Pilot journeys through the Textual app: the Erin replay, a quiet live-style source and a dead network."""

from __future__ import annotations

import asyncio
import io
from datetime import timedelta

import pytest
from textual import events
from textual.widgets import DataTable, TabbedContent, Tabs

from eyewall.app import EyewallApp
from eyewall.config import Config
from eyewall.state.store import storm_key
from eyewall.ui.screens.alerts import AlertLogScreen
from eyewall.ui.screens.detail import StormDetailScreen
from eyewall.ui.screens.help import HelpScreen, help_text
from eyewall.ui.screens.layers import LayerMenu
from eyewall.ui.screens.main import MainScreen
from eyewall.ui.widgets.map_view import MapView
from tests.ui_support import (
    EDT,
    ScriptedSource,
    into_the_storm,
    press,
    replay_app,
    running,
    screen_text,
    scripted_app,
    settle,
    wait_until,
)

SIZES = [(80, 24), (140, 45)]


def _adv(app: EyewallApp) -> str | None:
    state = next(iter(app.store.storms.values()))
    return storm_key(state.storm)[0]


@pytest.mark.parametrize("size", SIZES, ids=["80x24", "140x45"])
async def test_the_main_screen_shows_the_storm_and_the_status_bar(size: tuple[int, int]) -> None:
    app = replay_app()
    async with running(app, size):
        text = screen_text(app)
        assert isinstance(app.screen, MainScreen)
        assert "Hurricane Erin" in text
        assert "replay" in text
        assert app.selected is not None


async def test_a_wide_main_screen_has_a_column_beside_the_map_and_a_small_one_a_strip() -> None:
    wide = replay_app()
    async with running(wide, (140, 45)):
        assert wide.screen.has_class("tier-medium") and wide.screen.query_one("#side").display is True
        assert wide.screen.query_one("#strip").display is False
    small = replay_app()
    async with running(small, (80, 24)):
        assert small.screen.has_class("tier-small") and small.screen.query_one("#side").display is False
        assert small.screen.query_one(MapView).display is True


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
        assert isinstance(app.screen, MainScreen)


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


def test_help_says_what_eyewall_is_not() -> None:
    from rich.console import Console

    console = Console(width=100, record=True, file=io.StringIO())
    console.print(help_text())
    text = " ".join(console.export_text().split())
    assert "not an official forecast or warning" in text
    assert "follow the National Hurricane Center and your local emergency officials" in text


async def test_overlay_screens_open_and_close() -> None:
    app = replay_app()
    async with running(app) as pilot:
        await press(pilot, "question_mark")
        assert isinstance(app.screen, HelpScreen)
        await press(pilot, "escape")
        await press(pilot, "A")
        assert isinstance(app.screen, AlertLogScreen)
        await press(pilot, "escape")
        await press(pilot, "l")
        assert isinstance(app.screen, LayerMenu)
        await press(pilot, "escape")
        assert isinstance(app.screen, MainScreen)


async def test_layer_menu_toggle_reaches_the_map() -> None:
    app = replay_app()
    async with running(app) as pilot:
        view = app.screen.query_one(MapView)
        assert view.options.cone is True
        await press(pilot, "l")
        await press(pilot, "down", "down", "space")
        await press(pilot, "enter")
        assert isinstance(app.screen, MainScreen)
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


async def test_a_data_refresh_keeps_the_selected_storm_and_the_map_zoom() -> None:
    app = replay_app()
    async with running(app) as pilot:
        view = app.screen.query_one(MapView)
        await press(pilot, "minus", "minus")
        zoomed, selected = view.viewport, app.selected
        assert selected is not None
        await into_the_storm(pilot, 1)
        assert app.selected == selected
        assert view.viewport == zoomed


async def test_basin_filter_and_units() -> None:
    app = replay_app()
    async with running(app) as pilot:
        await press(pilot, "2")
        assert "Hurricane Erin" not in screen_text(app)
        assert "No tropical storms in the East Pacific" in screen_text(app)
        assert app.basin_filter == "EP"
        await press(pilot, "a")
        assert "Hurricane Erin" in screen_text(app)
        preset = app.units
        await press(pilot, "u")
        assert app.units != preset


async def test_quiet_source_says_so_and_shows_the_outlook_areas() -> None:
    app = scripted_app()
    async with running(app):
        text = " ".join(screen_text(app).split())
        assert "No tropical storms in the Atlantic" in text
        assert "NHC is watching 1 area" in text


async def test_a_dead_network_marks_feeds_stale_without_crashing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "eyewall.poll.REFRESH_MIN_GAP", 0.0
    )  # `r` is throttled on live data; this test presses it at once
    source = ScriptedSource()
    app = scripted_app(source)
    async with running(app) as pilot:
        source.fail = True
        await press(pilot, "r")
        await wait_until(pilot, lambda: app.poller.freshness("storms").failures > 0, 15)
        assert isinstance(app.screen, MainScreen)
        assert "NHC is watching 1 area" in " ".join(screen_text(app).split())  # the last good outlook stays on screen


async def test_tab_arrows_work_while_a_table_has_focus() -> None:
    app = replay_app()
    async with running(app) as pilot:
        await press(pilot, "enter", "2")
        table = app.screen.query_one("#forecast-table", DataTable)
        table.focus()
        await settle(pilot)
        assert app.focused is table
        tabs = app.screen.query_one(TabbedContent)
        await press(pilot, "right")
        assert tabs.active == "tab-public"
        await press(pilot, "left", "left")
        assert tabs.active == "tab-summary"
        strip = app.screen.query_one(Tabs)
        strip.focus()
        await settle(pilot)
        assert app.focused is strip
        await press(pilot, "right", "right")
        assert tabs.active == "tab-public"  # one step per press: the Tabs widget must not also move


async def test_a_screen_that_raises_does_not_stop_the_polling() -> None:
    app = replay_app()
    async with running(app) as pilot:
        calls = []

        def broken() -> None:
            calls.append(1)
            raise RuntimeError("boom")

        app.screen.refresh_data = broken  # type: ignore[method-assign]
        await press(pilot, "r")
        await press(pilot, "r")
        assert len(calls) >= 2  # the app survived the first failure and kept delivering results
        assert app.is_running
        assert any("failed" in n.message for n in app._notifications)


async def test_stepping_and_ticks_share_the_lock_and_the_replay_stops_at_the_end() -> None:
    app = replay_app()
    async with running(app) as pilot:
        assert app.replay is not None
        end = app.replay.manifest.end
        app.replay.clock.set(end - timedelta(seconds=1))
        app.paused = False
        # The app's own half-second timer also ticks, and a tick that finds the lock held returns without advancing, so
        # keep driving ticks until the replay reports it is over, up to a time limit rather than a count of tries.

        async def tick() -> bool:
            await app._replay_tick()
            return app.replay_over

        deadline = asyncio.get_running_loop().time() + 30
        while not await tick():
            assert asyncio.get_running_loop().time() < deadline, "the replay did not reach its end in 30 s"
            await pilot.pause(0.05)
        assert app.replay.now() == end
        assert app.paused and app.replay_over
        await app._replay_tick()  # paused and over: nothing moves
        assert app.replay.now() == end
        await settle(pilot)
        assert "over" in screen_text(app)
        await press(pilot, "left_square_bracket")
        assert not app.replay_over
        assert app.replay.now() < end


async def test_every_mouse_event_counts_as_presence() -> None:
    app = replay_app()
    async with running(app):
        app._last_input = 0.0
        await app.on_event(events.MouseScrollDown(None, 1, 1, 0, 1, 0, False, False, False))
        assert app._idle_seconds() < 5


async def test_no_network_and_no_cache_says_so_on_the_main_screen() -> None:
    source = ScriptedSource()
    source.fail = True
    app = scripted_app(source)
    async with running(app) as pilot:
        await wait_until(pilot, lambda: "Storm data unavailable" in screen_text(app), 15)


async def test_the_first_live_run_names_the_settings_file(tmp_path) -> None:
    path = tmp_path / "config.toml"
    app = EyewallApp(Config(), ScriptedSource(), local_tz=EDT, config_path=path)
    async with running(app):
        assert any(str(path) in note.message for note in app._notifications)


async def test_the_summary_tab_does_not_repeat_the_header_strip() -> None:
    app = replay_app()
    async with running(app) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "enter")
        text = screen_text(app)
        assert text.count("ERIN") == 2  # the header strip, and the headline under the summary
        assert "ERIN  H2  HU" not in text
