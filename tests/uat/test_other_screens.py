"""Outlook, alert log, followed stations, station menu, help, settings and the quiet-day state."""

from __future__ import annotations

from textual.widgets import Input, Switch

from eyewall.config import Config, load_config
from eyewall.ui.screens.alerts import AlertLogScreen
from eyewall.ui.screens.buoys import BuoysScreen
from eyewall.ui.screens.help import HelpScreen
from eyewall.ui.screens.settings import SettingsScreen
from eyewall.ui.screens.station import StationScreen
from eyewall.ui.widgets.station_list import StationList
from tests.ui_support import replay_app, scripted_app


async def test_alert_log(journey, size) -> None:
    async with journey(size) as j:
        await j.keys("A")
        assert isinstance(j.screen, AlertLogScreen)
        j.see("Time (Z)", "New advisory", "? help")
        await j.shot("alert-log")
        await j.keys("escape")
        assert not isinstance(j.screen, AlertLogScreen)


async def test_follow_unfollow_and_open_from_your_stations(journey, size) -> None:
    async with journey(size) as j:
        app = j.app
        await j.keys("enter", "b")
        assert isinstance(j.screen, BuoysScreen)
        stations = j.screen.query_one(StationList)
        stations.highlighted = [r.key for r in stations.rows].index("ndbc:41002")
        await j.keys("f")
        await j.settle()
        assert "41002" in app.config.watchlist.ndbc
        await j.keys("tab")
        await j.shot("your-stations")
        rows = j.screen.query_one(StationList).rows
        # Your stations lists the default watchlist too, so the one just followed is among them, not alone.
        assert "ndbc:41002" in [r.key for r in rows]
        assert {r.key for r in rows} == {
            *(f"ndbc:{i}" for i in Config().watchlist.ndbc),
            *(f"coops:{i}" for i in Config().watchlist.coops),
            "ndbc:41002",
        }
        stations = j.screen.query_one(StationList)
        stations.highlighted = [r.key for r in stations.rows].index("ndbc:41002")
        await j.settle()
        await j.keys("enter")
        assert isinstance(j.screen, StationScreen)
        await j.shot("opened-from-your-stations")
        await j.keys("escape", "f")
        await j.settle()
        assert "41002" not in app.config.watchlist.ndbc
        await j.shot("unfollowed")


async def test_station_menu_opens_a_buoy(journey, size) -> None:
    async with journey(size) as j:
        await j.keys("slash")
        await j.pilot.pause(0.3)
        await j.keys(*"41002")
        await j.pilot.pause(0.6)
        j.see("41002")
        await j.shot("search-hit", footer=False)
        await j.keys("enter")
        await j.settle()
        assert isinstance(j.screen, StationScreen)
        await j.shot("search-opened")


async def test_help_screen_closes_two_ways(journey, size) -> None:
    async with journey(size) as j:
        for key in ("escape", "question_mark"):
            await j.keys("question_mark")
            assert isinstance(j.screen, HelpScreen)
            j.see("Map")  # the rest of the help is below, behind the scroll
            if key == "escape":
                await j.shot("help", footer=False)
            await j.keys(key)
            assert not isinstance(j.screen, HelpScreen)


async def test_settings_edit_save_cancel_and_invalid(journey, size, tmp_path) -> None:
    path = tmp_path / "config.toml"
    app = replay_app()
    app.config_path = path
    async with journey(size, app=app) as j:
        await j.keys("S")
        assert isinstance(j.screen, SettingsScreen)
        j.see("Settings", "Poll intervals")
        await j.shot("settings", footer=False)
        j.screen.query_one("#poll-storms", Input).value = "120"
        await j.keys("escape")  # cancel throws the edit away
        assert app.config.poll.storms != 120 and not path.exists()
        await j.keys("S")
        j.screen.query_one("#poll-storms", Input).value = "soon"
        await j.keys("ctrl+s")
        assert isinstance(j.screen, SettingsScreen)
        j.see("Not saved")
        note, scroll = j.screen.query_one("#settings-note"), j.screen.query_one("#settings-scroll")
        assert note.region.y >= scroll.region.bottom, "the error overlaps the settings list"
        assert note.region.bottom < j.screen.query_one("#settings-box").region.bottom, "the error runs into the border"
        await j.shot("settings-invalid", footer=False)
        j.screen.query_one("#poll-storms", Input).value = "120"  # below the 300 s floor for the storms feed
        await j.keys("ctrl+s")
        assert isinstance(j.screen, SettingsScreen)
        j.see("Not saved", "poll.storms")
        j.screen.query_one("#poll-storms", Input).value = "600"
        switch = j.screen.query_one("#alerts-bell", Switch)
        wanted = not switch.value
        switch.value = wanted
        await j.keys("ctrl+s")
        assert not isinstance(j.screen, SettingsScreen)
        assert app.config.poll.storms == 600 and app.config.alerts.bell is wanted
        saved = load_config(path).config
        assert saved.poll.storms == 600 and saved.alerts.bell is wanted
        await j.shot("settings-saved")


async def test_quiet_day(size, journey) -> None:
    async with journey(size, app=scripted_app()) as j:
        j.see("No tropical storms")  # no storms: the plain sentence, with the outlook and the replay offer under it
        await j.shot("quiet-main")
        await j.keys("g")
        assert "Select a storm" in j.toasts()
        await j.keys("b")
        assert isinstance(j.screen, BuoysScreen)  # no storm to look at, so b opens the watchlist
        await j.shot("quiet-watchlist")
        await j.keys("escape", "A")
        j.see("New tropical weather outlook")
        await j.shot("quiet-alerts", footer=False)
