"""Pilot journeys through the buoy and tide gauge views: the two tabs, the buoy charts, the watchlist, the search, the
settings screen and unit cycling. Everything runs over the Erin replay (ticked by hand) or a scripted quiet-day source."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from textual.widgets import Input, Select, Sparkline, Static, Switch

from eyewall.app import EyewallApp
from eyewall.config import Config, load_config
from eyewall.models.obs import (
    LatestObservation,
    Observation,
    ObservationSeries,
    Station,
    TideSeries,
    TideStation,
    WaterLevelReading,
)
from eyewall.models.obs import Parsed as ObsParsed
from eyewall.ui.screens.buoy_detail import BuoyDetailScreen
from eyewall.ui.screens.detail import StormDetailScreen
from eyewall.ui.screens.outlook import OutlookScreen
from eyewall.ui.screens.search import SearchScreen
from eyewall.ui.screens.settings import SettingsScreen
from eyewall.ui.screens.watchlist import WatchlistScreen
from eyewall.ui.widgets.station_table import StationTable
from tests.ui_support import (
    QUIET_NOW,
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

STEP = "right_square_bracket"
SIZES = [(80, 24), (140, 45)]


def table(app: EyewallApp, table_id: str) -> StationTable:
    return app.screen.query_one(f"#{table_id}", StationTable)


def with_files(tmp_path: Path, config: Config | None = None) -> dict[str, object]:
    return {"config": config, "config_path": tmp_path / "eyewall.toml"}


@pytest.mark.parametrize("size", SIZES, ids=["80x24", "140x45"])
async def test_buoys_tab_lists_the_nearest_buoys_first(size: tuple[int, int]) -> None:
    app = replay_app()
    async with running(app, size) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "enter", "7")
        assert isinstance(app.screen, StormDetailScreen)
        keys = table(app, "buoys-table").keys
        assert keys[:2] == ["41002", "41001"]
        text = screen_text(app)
        assert "41002" in text
        assert "Wind" in text


async def test_the_nearest_buoy_stays_first_across_a_tick() -> None:
    app = replay_app()
    async with running(app) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "enter", "7")
        keys = table(app, "buoys-table").keys
        await press(pilot, STEP)
        assert table(app, "buoys-table").keys[0] == keys[0]


async def test_enter_on_a_buoy_row_opens_its_charts_and_escape_returns() -> None:
    app = replay_app()
    async with running(app) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "enter", "7", "enter")
        assert isinstance(app.screen, BuoyDetailScreen)
        assert app.screen.station_id == "41002"
        text = screen_text(app)
        assert "41002" in text and "Pressure" in text and "Wind and gust" in text and "Wave" in text
        assert "24 h" in text
        assert "41002" in app.poller.extra_buoys
        spark = app.screen.query_one("#spark-pressure", Sparkline)
        assert spark.data
        await press(pilot, "escape")
        assert isinstance(app.screen, StormDetailScreen)
        assert "41002" not in app.poller.extra_buoys


async def test_the_h_key_cycles_the_range_through_24_48_and_72_hours() -> None:
    app = replay_app()
    async with running(app) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "enter", "7", "enter")
        seen = []
        for _ in range(3):
            seen.append(app.screen.hours)  # type: ignore[attr-defined]
            await press(pilot, "h")
        assert seen == [24, 48, 72]
        assert app.screen.hours == 24  # type: ignore[attr-defined]


@pytest.mark.parametrize("size", SIZES, ids=["80x24", "140x45"])
async def test_buoy_detail_fits_both_sizes_and_the_info_panel_toggles_when_narrow(size: tuple[int, int]) -> None:
    app = replay_app()
    async with running(app, size) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "enter", "7", "enter")
        screen = app.screen
        assert isinstance(screen, BuoyDetailScreen)
        assert screen.has_class("narrow") is (size[0] < 110)
        if size[0] < 110:
            assert screen.has_class("show-info") is False
            await press(pilot, "i")
            assert screen.has_class("show-info")
            assert "Latest" in screen_text(app) or "Wind" in screen_text(app)


async def test_the_buoy_detail_shows_the_supplemental_note_when_there_is_no_file() -> None:
    app = replay_app()
    async with running(app) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "enter", "7", "enter")
        await wait_until(pilot, lambda: app.screen.supl is not None)  # type: ignore[attr-defined]
        await settle(pilot)
        assert "supplemental" in screen_text(app).lower()


async def test_tides_tab_shows_observed_predicted_and_the_residual() -> None:
    app = replay_app()
    async with running(app) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "enter", "8")
        keys = table(app, "tides-table").keys
        assert keys
        text = screen_text(app)
        assert "Observed" in text and "Predicted" in text and "Residual" in text
        assert any(mark in text for mark in ("+0.", "-0.", "+1.", "+2."))


async def test_unit_cycling_changes_the_numbers_on_the_buoys_tab() -> None:
    app = replay_app()
    async with running(app) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "enter", "7")
        nautical = screen_text(app)
        await press(pilot, "u")
        us = screen_text(app)
        await press(pilot, "u")
        metric = screen_text(app)
        assert app.units == "metric"
        assert "kt" in nautical and "mb" in nautical
        assert "mph" in us and "inHg" in us
        assert "km/h" in metric and "hPa" in metric
        await press(pilot, "u")
        assert app.units == "nautical"
        assert "kt" in screen_text(app)


async def test_p_pins_the_highlighted_buoy_and_saves_it_to_the_config_file(tmp_path: Path) -> None:
    app = replay_app(**with_files(tmp_path))
    async with running(app) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "enter", "7")
        station = table(app, "buoys-table").current_key()
        assert station is not None and station not in app.config.watchlist.ndbc
        await press(pilot, "p")
        await wait_until(pilot, lambda: station in app.config.watchlist.ndbc)
        saved = load_config(tmp_path / "eyewall.toml")
        assert saved.warnings == ()
        assert station in saved.config.watchlist.ndbc
        await press(pilot, "p")
        await wait_until(pilot, lambda: station not in app.config.watchlist.ndbc)
        assert station not in load_config(tmp_path / "eyewall.toml").config.watchlist.ndbc


async def test_p_on_the_buoy_detail_pins_that_buoy(tmp_path: Path) -> None:
    app = replay_app(**with_files(tmp_path))
    async with running(app) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "enter", "7", "enter", "p")
        await wait_until(pilot, lambda: "41002" in app.config.watchlist.ndbc)
        assert "41002" in load_config(tmp_path / "eyewall.toml").config.watchlist.ndbc


async def test_changes_are_kept_for_the_run_when_there_is_no_config_file() -> None:
    app = replay_app()
    async with running(app) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "enter", "7", "p")
        station = table(app, "buoys-table").current_key()
        await wait_until(pilot, lambda: station in app.config.watchlist.ndbc)


async def test_the_watchlist_screen_adds_and_removes_stations(tmp_path: Path) -> None:
    app = replay_app(**with_files(tmp_path))
    async with running(app) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "w")
        assert isinstance(app.screen, WatchlistScreen)
        before = app.config.watchlist.ndbc
        candidate = next(i for i in app.store.stations if i not in before and i.isdigit())
        await press(pilot, "a")
        assert isinstance(app.screen, SearchScreen)
        await pilot.press(*candidate)
        await settle(pilot)
        await press(pilot, "enter")
        await wait_until(pilot, lambda: candidate in app.config.watchlist.ndbc)
        assert isinstance(app.screen, WatchlistScreen)
        assert candidate in load_config(tmp_path / "eyewall.toml").config.watchlist.ndbc
        keys = app.screen.query_one("#watch-buoys", StationTable).keys
        assert candidate in keys
        app.screen.query_one("#watch-buoys", StationTable).move_cursor(row=keys.index(candidate))
        await press(pilot, "d")
        await wait_until(pilot, lambda: candidate not in app.config.watchlist.ndbc)
        assert candidate not in load_config(tmp_path / "eyewall.toml").config.watchlist.ndbc
        await press(pilot, "escape")
        assert not isinstance(app.screen, WatchlistScreen)


async def test_the_search_finds_a_station_by_name_and_enter_opens_its_charts() -> None:
    app = replay_app()
    async with running(app) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "slash")
        assert isinstance(app.screen, SearchScreen)
        station = app.store.stations["41002"]
        word = station.name.split()[0].lower()
        await pilot.press(*word)
        await settle(pilot)
        assert "41002" in screen_text(app)
        await press(pilot, "ctrl+p")
        await wait_until(pilot, lambda: "41002" in app.config.watchlist.ndbc)
        assert not isinstance(app.screen, SearchScreen)
        await press(pilot, "slash")
        await pilot.press(*"41002")
        await settle(pilot)
        await press(pilot, "enter")
        assert isinstance(app.screen, BuoyDetailScreen)


async def test_the_search_says_so_when_nothing_matches() -> None:
    app = replay_app()
    async with running(app) as pilot:
        await press(pilot, "slash")
        await pilot.press(*"qqqqzz")
        await settle(pilot)
        assert "No station matches" in screen_text(app)
        await press(pilot, "escape")
        assert not isinstance(app.screen, SearchScreen)


async def test_settings_save_round_trips_through_the_toml_file(tmp_path: Path) -> None:
    app = replay_app(**with_files(tmp_path))
    async with running(app) as pilot:
        await press(pilot, "S")
        assert isinstance(app.screen, SettingsScreen)
        screen = app.screen
        screen.query_one("#poll-storms", Input).value = "240"
        screen.query_one("#nearby-radius_now_nm", Input).value = "150"
        screen.query_one("#units-preset", Select).value = "metric"
        screen.query_one("#alerts-bell", Switch).value = False
        screen.query_one("#basin-CP", Switch).value = False
        await press(pilot, "ctrl+s")
        assert not isinstance(app.screen, SettingsScreen)
        assert app.config.poll.storms == 240
        assert app.config.nearby.radius_now_nm == 150
        assert app.units == "metric"
        loaded = load_config(tmp_path / "eyewall.toml")
        assert loaded.warnings == ()
        assert loaded.config == app.config
        assert loaded.config.units.preset == "metric"
        assert "CP" not in loaded.config.basins.enabled
        assert loaded.config.alerts.bell is False


async def test_settings_with_a_bad_value_stay_open_and_save_nothing(tmp_path: Path) -> None:
    app = replay_app(**with_files(tmp_path))
    async with running(app) as pilot:
        await press(pilot, "S")
        screen = app.screen
        screen.query_one("#poll-storms", Input).value = "soon"
        await press(pilot, "ctrl+s")
        assert isinstance(app.screen, SettingsScreen)
        assert "Not saved" in str(screen.query_one("#settings-note", Static).render())
        assert not (tmp_path / "eyewall.toml").exists()
        await press(pilot, "escape")
        assert not isinstance(app.screen, SettingsScreen)
        assert not (tmp_path / "eyewall.toml").exists()


async def test_a_config_file_that_cannot_be_written_is_reported_and_the_change_still_applies(tmp_path: Path) -> None:
    blocked = tmp_path / "is-a-folder"
    blocked.mkdir()
    app = replay_app(config_path=blocked)
    async with running(app) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "enter", "7", "p")
        station = table(app, "buoys-table").current_key()
        await wait_until(pilot, lambda: station in app.config.watchlist.ndbc)
        assert not blocked.is_file()
        assert station in app.config.watchlist.ndbc


# ---- a quiet day: no storm, a watchlist ------------------------------------------------------------------------------


class QuietDaySource(ScriptedSource):
    """No storms; one watched buoy that reports and one that has gone dark, and one tide gauge."""

    async def ndbc_stations(self) -> tuple[Station, ...]:
        return (
            Station("41010", "CANAVERAL EAST", 28.9, -78.5, type="buoy", owner="NDBC"),
            Station("42001", "MID GULF", 25.9, -89.7, type="buoy", owner="NDBC"),
        )

    async def ndbc_latest(self) -> tuple[LatestObservation, ...]:
        row = Observation(QUIET_NOW - timedelta(minutes=20), wind_speed_mps=9.0, pressure_hpa=1015.0)
        return (LatestObservation("41010", 28.9, -78.5, row),)

    async def ndbc_series(self, station_id: str) -> ObservationSeries:
        if station_id != "41010":
            return ObservationSeries(station_id, message="no file")
        rows = tuple(
            Observation(
                QUIET_NOW - timedelta(minutes=30 * k),
                wind_speed_mps=9.0 + k * 0.1,
                gust_mps=12.0,
                pressure_hpa=1015.0 - k * 0.2,
                wave_height_m=1.5,
            )
            for k in range(0, 60)
        )
        return ObservationSeries(station_id, rows)

    async def coops_stations(self) -> tuple[TideStation, ...]:
        return (TideStation("8721604", "Trident Pier", 28.41, -80.59, "FL"),)

    async def coops_series(self, station: TideStation, datum: str) -> TideSeries:
        moment = datetime(2026, 10, 31, 11, 54, tzinfo=UTC)
        return TideSeries(station.id, datum, water_level=ObsParsed((WaterLevelReading(moment, 3.2),)))


async def test_a_quiet_day_polls_the_watchlist_and_the_outlook_lists_it() -> None:
    app = scripted_app(QuietDaySource())
    async with running(app) as pilot:
        await press(pilot, "O")
        assert isinstance(app.screen, OutlookScreen)
        await wait_until(pilot, lambda: "41010" in app.store.latest)
        await settle(pilot)
        text = screen_text(app)
        assert "Watchlist" in text
        assert "41010" in text
        assert "42001" in text
        assert "not reporting" in text or "waiting" in text


async def test_the_watchlist_screen_on_a_quiet_day_opens_a_buoy_with_enter() -> None:
    app = scripted_app(QuietDaySource())
    async with running(app) as pilot:
        await wait_until(pilot, lambda: "41010" in app.store.latest)
        await press(pilot, "b")
        assert isinstance(app.screen, WatchlistScreen)
        assert app.screen.query_one("#watch-buoys", StationTable).keys[0] == "41010"
        await press(pilot, "enter")
        assert isinstance(app.screen, BuoyDetailScreen)
        await settle(pilot)
        text = screen_text(app)
        assert "41010" in text and "CANAVERAL" in text


async def test_a_silent_watchlist_buoy_reads_not_reporting_on_its_chart_screen() -> None:
    app = scripted_app(QuietDaySource())
    async with running(app) as pilot:
        await wait_until(pilot, lambda: "41010" in app.store.latest)
        app.open_buoy("42001")
        await settle(pilot)
        assert isinstance(app.screen, BuoyDetailScreen)
        assert "not reporting" in screen_text(app) or "waiting" in screen_text(app)


# ---- review fixes ------------------------------------------------------------------------------------------------


async def test_command_line_flags_are_not_saved_with_a_pin(tmp_path: Path) -> None:
    from dataclasses import replace

    from eyewall.config import BasinsConfig, save_config

    path = tmp_path / "eyewall.toml"
    from_file = Config()
    save_config(from_file, path)
    flagged = replace(from_file, basins=BasinsConfig(("AL",)), map=replace(from_file.map, glyph_set="ascii"))
    app = replay_app(flagged, config_path=path, file_config=from_file)
    async with running(app) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "enter", "7", "p")
        await wait_until(pilot, lambda: load_config(path).config.watchlist != from_file.watchlist)
    saved = load_config(path).config
    assert saved.basins == from_file.basins
    assert saved.map.glyph_set == from_file.map.glyph_set


async def test_a_value_changed_in_settings_is_saved_even_when_a_flag_set_it(tmp_path: Path) -> None:
    from dataclasses import replace

    from eyewall.config import save_config

    path = tmp_path / "eyewall.toml"
    from_file = Config()
    save_config(from_file, path)
    flagged = replace(from_file, map=replace(from_file.map, glyph_set="ascii"))
    app = replay_app(flagged, config_path=path, file_config=from_file)
    async with running(app) as pilot:
        await press(pilot, "S")
        app.screen.query_one("#map-glyph-set", Select).value = "unicode"
        await press(pilot, "ctrl+s")
    assert load_config(path).config.map.glyph_set == "unicode"


async def test_a_file_that_failed_to_load_is_backed_up_before_the_first_save(tmp_path: Path) -> None:
    path = tmp_path / "eyewall.toml"
    path.write_text("[poll\nstorms = 'oops'\n", encoding="utf-8")
    original = path.read_bytes()
    app = replay_app(config_path=path, config_file_broken=True)
    async with running(app) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "enter", "7", "p")
        await wait_until(pilot, lambda: not load_config(path).broken)
    assert (tmp_path / "eyewall.toml.bak").read_bytes() == original
    assert load_config(path).config.watchlist != Config().watchlist


async def test_opening_a_buoy_fetches_that_series_and_reuses_the_supplemental_file() -> None:
    app = replay_app()
    async with running(app) as pilot:
        await into_the_storm(pilot)
        asked: list[str] = []
        refreshed: list[tuple[str, ...]] = []
        original = app.source.ndbc_supplemental

        async def spy(station_id: str):  # type: ignore[no-untyped-def]
            asked.append(station_id)
            return await original(station_id)

        app.source.ndbc_supplemental = spy  # type: ignore[method-assign]
        app.poller.refresh_feeds = lambda *feeds: refreshed.append(feeds)  # type: ignore[method-assign]
        app.store.series.pop("41002", None)
        for _ in range(2):
            app.open_buoy("41002")
            await settle(pilot)
            await wait_until(pilot, lambda: app.screen.supl is not None)  # type: ignore[attr-defined]
            await press(pilot, "escape")
        assert "41002" in app.store.series
        assert refreshed == []
        assert asked == ["41002"]


async def test_a_settings_change_makes_only_the_affected_feeds_due() -> None:
    from dataclasses import replace

    app = replay_app()
    async with running(app):
        due: list[tuple[str, ...]] = []
        app.poller.refresh_feeds = lambda *feeds: due.append(feeds)  # type: ignore[method-assign]
        app.poller.refresh = lambda: due.append(("everything",))  # type: ignore[method-assign]
        app.apply_config(replace(app.config, poll=replace(app.config.poll, buoys=900.0)), persist=False)
        assert due == [("buoys",)]
        due.clear()
        app.apply_config(replace(app.config, nearby=replace(app.config.nearby, radius_now_nm=200.0)), persist=False)
        assert due == [("buoys", "tides")]
        due.clear()
        app.apply_config(replace(app.config, units=replace(app.config.units, preset="metric")), persist=False)
        assert due == []


async def test_a_failing_pin_is_reported_and_does_not_end_the_app() -> None:
    app = replay_app()
    async with running(app) as pilot:
        await into_the_storm(pilot)

        async def broken(*_args: object) -> None:
            raise RuntimeError("disk on fire")

        app.set_watch = broken  # type: ignore[method-assign]
        await press(pilot, "enter", "7", "p")
        await wait_until(pilot, lambda: any("disk on fire" in n.message for n in app._notifications))
        assert app.is_running
        assert isinstance(app.screen, StormDetailScreen)


async def test_a_hand_edited_fractional_interval_survives_a_settings_save(tmp_path: Path) -> None:
    from dataclasses import replace

    config = Config()
    config = replace(config, poll=replace(config.poll, storms=90.5))
    app = replay_app(config, config_path=tmp_path / "eyewall.toml")
    async with running(app) as pilot:
        await press(pilot, "S")
        assert app.screen.query_one("#poll-storms", Input).value == "90.5"
        await press(pilot, "ctrl+s")
    assert load_config(tmp_path / "eyewall.toml").config.poll.storms == 90.5
