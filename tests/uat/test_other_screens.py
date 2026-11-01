"""Outlook, alert log, watchlist, station search, help, settings and the quiet-day state."""

from __future__ import annotations

from textual.widgets import Input, Switch

from eyewall.config import load_config
from eyewall.ui.screens.alerts import AlertLogScreen
from eyewall.ui.screens.buoy_detail import BuoyDetailScreen
from eyewall.ui.screens.help import HelpScreen
from eyewall.ui.screens.search import SearchScreen
from eyewall.ui.screens.settings import SettingsScreen
from eyewall.ui.screens.watchlist import WatchlistScreen
from tests.ui_support import replay_app, scripted_app


async def test_alert_log(journey, size) -> None:
    async with journey(size) as j:
        await j.keys("A")
        assert isinstance(j.screen, AlertLogScreen)
        j.see("Time (Z)", "New advisory", "? help")
        await j.shot("alert-log")
        await j.keys("escape")
        assert not isinstance(j.screen, AlertLogScreen)


async def test_watchlist_add_remove_and_open(journey, size) -> None:
    async with journey(size) as j:
        app = j.app
        await j.keys("w")
        assert isinstance(j.screen, WatchlistScreen)
        j.see("Buoys (", "Tide gauges (")
        await j.shot("watchlist")
        await j.keys("tab")
        await j.shot("watchlist-tide-table")
        await j.keys("tab", "a")
        assert isinstance(j.screen, SearchScreen)
        await j.shot("add-search", footer=False)
        await j.keys(*"41002")
        j.see("41002")
        await j.keys("enter")
        await j.settle()
        assert "41002" in app.config.watchlist.ndbc
        await j.shot("added")
        table = j.screen.query_one("#watch-buoys")
        table.move_cursor(row=table.row_count - 1)
        await j.settle()
        await j.keys("d")
        await j.settle()
        assert "41002" not in app.config.watchlist.ndbc
        await j.shot("removed")
        await j.keys("enter")
        assert isinstance(j.screen, BuoyDetailScreen)
        await j.shot("opened-from-watchlist")


async def test_station_search_opens_a_buoy(journey, size) -> None:
    async with journey(size) as j:
        await j.keys("slash")
        assert isinstance(j.screen, SearchScreen)
        await j.keys(*"41002")
        j.see("41002")
        await j.shot("search-hit", footer=False)
        await j.keys("enter")
        assert isinstance(j.screen, BuoyDetailScreen)
        await j.shot("search-opened")


async def test_help_screen_closes_two_ways(journey, size) -> None:
    async with journey(size) as j:
        for key in ("escape", "question_mark"):
            await j.keys("question_mark")
            assert isinstance(j.screen, HelpScreen)
            j.see("Map", "Storm detail")  # the rest of the help is below, behind the scroll
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
        assert isinstance(j.screen, WatchlistScreen)  # no storm to look at, so b opens the watchlist
        await j.shot("quiet-watchlist")
        await j.keys("escape", "A")
        j.see("New tropical weather outlook")
        await j.shot("quiet-alerts", footer=False)
