"""Replay start, stepping and ticks, and the main screen: panels, storm selection, the map and its layers."""

from __future__ import annotations

from datetime import timedelta

from textual.widgets import SelectionList

from eyewall.app import REPLAY_SPEEDS, REPLAY_TICK
from eyewall.ui.screens.detail import StormDetailScreen
from eyewall.ui.screens.layers import LayerMenu
from eyewall.ui.screens.main import MainScreen
from tests.uat.harness import Journey


def moment(j: Journey):  # type: ignore[no-untyped-def]
    assert j.app.replay is not None
    return j.app.replay.now()


async def test_replay_start_and_stepping(journey, size) -> None:
    async with journey(size, storm=False) as j:
        await j.shot("start")
        assert j.app.replay is not None and j.app.paused
        j.see("Erin")  # the replay opens on the first advisory, not the empty hours before it
        assert j.app.glyphs.pause in j.top()
        first = moment(j)
        await j.keys("right_square_bracket")
        assert moment(j) > first
        await j.shot("next-advisory")
        await j.keys("left_square_bracket")
        assert moment(j) == first
        await j.keys("left_square_bracket")
        assert "first advisory" in j.toasts()
        await j.shot("first-advisory")


async def test_replay_speed_and_pause(journey, size) -> None:
    async with journey(size) as j:
        app = j.app
        await j.keys("greater_than_sign")
        assert app.speed_index == 2
        await j.keys("greater_than_sign", "greater_than_sign")
        assert app.speed_index == len(REPLAY_SPEEDS) - 1  # clamped at the fastest
        await j.shot("fastest")
        await j.keys("less_than_sign", "less_than_sign", "less_than_sign", "less_than_sign")
        assert app.speed_index == 0
        await j.keys("space")
        assert not app.paused and app.glyphs.play in j.top()
        await j.shot("playing")
        await j.keys("space")
        assert app.paused and app.glyphs.pause in j.top()
        await j.shot("paused")


async def test_replay_ticks_advance_the_virtual_clock(journey, size) -> None:
    async with journey(size) as j:
        app, replay = j.app, j.app.replay
        assert replay is not None
        before = replay.now()
        await app._replay_tick()
        assert replay.now() == before  # paused: no movement
        app.paused = False
        await app._replay_tick()
        app.paused = True
        assert replay.now() - before == timedelta(seconds=REPLAY_SPEEDS[app.speed_index] * REPLAY_TICK)
        await j.shot("after-a-tick")


async def test_replay_runs_out_and_steps_back(journey, size) -> None:
    async with journey(size) as j:
        app, replay = j.app, j.app.replay
        assert replay is not None
        async with app._tick_lock:
            replay.clock.advance((replay.manifest.end - replay.now()).total_seconds() - 1)
        app.paused = False
        await app._replay_tick()
        await j.settle()
        assert app.replay_over and app.paused
        assert "replay is over" in j.toasts() and "over" in j.top()
        await j.shot("replay-over")
        await j.keys("left_square_bracket")
        assert not app.replay_over
        await j.shot("stepped-back")


async def test_main_screen_panels(journey, size) -> None:
    async with journey(size) as j:
        j.see("Hurricane Erin")
        if size[0] >= 100 and size[1] >= 30:
            j.see("NAMED STORMS", "WATCHES AND WARNINGS")
        else:
            j.see("Erin")
        await j.shot("main")


async def test_storm_selection_and_basins(journey, size) -> None:
    async with journey(size) as j:
        app = j.app
        assert app.selected == "al052025"
        await j.keys("j", "k")
        assert app.selected == "al052025"
        await j.keys("2")
        assert app.basin_filter == "EP"
        j.not_see("Hurricane Erin")
        await j.shot("east-pacific-only")
        await j.keys("3")
        await j.shot("central-pacific-only")
        await j.keys("1")
        j.see("Hurricane Erin")
        await j.shot("atlantic-only")
        await j.keys("a")
        assert app.basin_filter is None
        await j.keys("enter")
        assert isinstance(app.screen, StormDetailScreen)
        await j.shot("detail-opened")
        await j.keys("escape")
        assert isinstance(app.screen, MainScreen)
        await j.shot("back-on-the-main-screen")


async def test_map_zoom_fit_centre_and_full_screen(journey, size) -> None:
    async with journey(size) as j:
        app, dash = j.app, j.screen
        if size[0] < 90:
            await j.keys("m")  # below 90 columns the map is hidden until asked for
        view = dash.map_view
        await j.shot("map")
        fitted = view.viewport
        assert fitted is not None
        await j.keys("plus")
        zoomed = view.viewport
        assert zoomed.deg_per_dot < fitted.deg_per_dot
        await j.shot("zoomed-in")
        await j.keys("minus", "minus")
        assert view.viewport.deg_per_dot > zoomed.deg_per_dot
        await j.keys("f")
        assert view.viewport.deg_per_dot == fitted.deg_per_dot
        await j.keys("plus", "plus", "c")
        storm = app.store.storms[app.selected].storm
        assert abs(view.viewport.center_lat - storm.lat) < 0.5 and abs(view.viewport.center_lon - storm.lon) < 0.5
        await j.shot("centred")
        await j.keys("M")
        assert dash.has_class("full-map")
        assert view.region.width >= size[0] - 2
        await j.shot("full-screen-map")
        await j.keys("M")
        assert not dash.has_class("full-map")


async def test_map_layers_apply_and_cancel(journey, size) -> None:
    async with journey(size) as j:
        app = j.app
        if size[0] < 90:
            await j.keys("m")
        await j.keys("l")
        assert isinstance(app.screen, LayerMenu)
        await j.shot("layer-menu", footer=False)
        assert app.map_options.land
        await j.keys("space", "enter")
        assert not app.map_options.land
        assert not isinstance(app.screen, LayerMenu)
        await j.shot("land-off")
        await j.keys("l", "space", "escape")  # toggled but cancelled: nothing changes
        assert not app.map_options.land
        await j.keys("l")
        menu = app.screen.query_one(SelectionList)
        assert "land" not in menu.selected
        await j.keys("escape")
