"""Station and storm data is shown at its real age: nothing old is passed off as current."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from eyewall.config import Config, with_watchlist
from eyewall.models.events import EventKind
from eyewall.models.forecast import ForecastFix
from eyewall.models.obs import (
    LatestObservation,
    Observation,
    ObservationSeries,
    Station,
    TidePressure,
    TideSeries,
    TideStation,
    TideWind,
    WaterLevelReading,
)
from eyewall.models.obs import Parsed as ObsParsed
from eyewall.models.watches import AlertsResult, WatchWarningAlert
from eyewall.models.wind import WindRadii
from eyewall.state.store import Store, StormState, track_fixes, track_from
from eyewall.ui import adapt
from eyewall.ui import stations as st
from eyewall.ui.glyphs import glyphs_for
from eyewall.units import PRESETS
from tests.state_support import T0, advisories, make_storm

NOW = datetime(2026, 9, 1, 18, 0, tzinfo=UTC)
G = glyphs_for("unicode")
NAUTICAL = PRESETS["nautical"]


def fix(valid: datetime, lat: float, lon: float) -> ForecastFix:
    return ForecastFix(12, valid, lat, lon, None, None, WindRadii())


# ---- buoy and gauge ages --------------------------------------------------------------------------------------


def _gauge_series(wind_age_h: float, pressure_age_h: float) -> TideSeries:
    return TideSeries(
        "8651370",
        "MLLW",
        water_level=ObsParsed((WaterLevelReading(NOW - timedelta(minutes=6), 3.0),)),
        wind=ObsParsed((TideWind(NOW - timedelta(hours=wind_age_h), 55.0, 90.0, "E"),)),
        pressure=ObsParsed((TidePressure(NOW - timedelta(hours=pressure_age_h), 990.0),)),
    )


def test_a_gauge_shows_wind_and_pressure_only_while_they_are_recent() -> None:
    store = Store(Config())
    gauge = TideStation("8651370", "Duck", 36.18, -75.75, "NC")
    entry = st.Entry(gauge)
    store.tide_series[gauge.id] = _gauge_series(0.5, 0.5)
    fresh = st.tide_row(store, entry, NOW, NAUTICAL)
    assert "55" in fresh[7].plain and "990" in fresh[8].plain
    store.tide_series[gauge.id] = _gauge_series(30, 30)  # the sensors died a day ago; the water level still reports
    old = st.tide_row(store, entry, NOW, NAUTICAL)
    assert old[7].plain == "--" and old[8].plain == "--"
    mark = adapt._tide_mark(store, gauge, NOW)
    assert mark.wind_kt is None and not mark.stale


def _latest(station_id: str, minutes_ago: int, kt: float = 20.0) -> LatestObservation:
    obs = Observation(time=NOW - timedelta(minutes=minutes_ago), wind_speed_mps=kt * 0.514444, pressure_hpa=1000.0)
    return LatestObservation(station_id, 30.0, -80.0, obs)


def test_a_fresh_latest_obs_row_beats_a_series_that_stopped_refreshing() -> None:
    store = Store(Config())
    store.stations = {"41010": Station("41010", "CANAVERAL", 28.9, -78.5)}
    old = Observation(time=NOW - timedelta(hours=9), wind_speed_mps=5.0)
    store.series["41010"] = ObservationSeries("41010", (old,))
    assert st.buoy_state(store, "41010", NOW) == "silent"
    store.latest["41010"] = _latest("41010", 10)
    assert st.buoy_state(store, "41010", NOW) == "ok"
    newest = st.newest_observation(store, "41010")
    assert newest is not None and newest.time == NOW - timedelta(minutes=10)


def test_a_map_mark_from_an_old_latest_obs_row_is_stale() -> None:
    store = Store(Config())
    store.latest["41010"] = _latest("41010", 60 * 6)
    wind, stale = adapt._wind_kt_of(store, "41010", NOW)
    assert wind is not None and stale
    store.latest["41010"] = _latest("41010", 20)
    assert not adapt._wind_kt_of(store, "41010", NOW)[1]


# ---- the closest approach -------------------------------------------------------------------------------------


def test_hours_to_closest_approach_count_from_now_not_from_the_advisory() -> None:
    store = Store(Config())
    storm = make_storm("5", lat=25.0, lon=-75.0)
    adv = advisories("5")
    tcm = replace(adv.forecast, issued=T0, fixes=(fix(T0 + timedelta(hours=12), 25.0, -73.0),))
    state = StormState(storm, replace(adv, forecast=tcm))
    store.storms[storm.id] = state
    store.stations = {"41010": Station("41010", "EAST", 25.0, -73.0, met=True)}
    at_issue = store.nearby_buoys(storm.id, T0)[0]
    five_hours_on = store.nearby_buoys(storm.id, T0 + timedelta(hours=5))[0]
    assert abs((at_issue.eta_hours - five_hours_on.eta_hours) - 5) < 0.5
    assert [f.hours for f in track_fixes(state, T0 + timedelta(hours=5))] == [7.0]
    assert track_fixes(state, T0 + timedelta(hours=13)) == []  # a fix already past is dropped


# ---- the nearby buoys -----------------------------------------------------------------------------------------


def test_stations_without_weather_data_do_not_take_nearby_slots() -> None:
    store = Store(Config())
    storm = make_storm("5", lat=25.0, lon=-75.0)
    store.storms[storm.id] = StormState(storm, advisories("5"))
    store.stations = {
        "DART1": Station("DART1", "tsunami", 25.1, -75.0, met=False, dart=True),
        "41010": Station("41010", "weather", 26.0, -75.0, met=True),
        "NOFLAG": Station("NOFLAG", "unknown", 26.5, -75.0),
        "GONE": Station("GONE", "just went silent", 25.2, -75.0, met=False),
        "PINNED": Station("PINNED", "watched", 25.3, -75.0, met=False),
    }
    store.config = with_watchlist(store.config, "ndbc", ["PINNED"])
    store.series["GONE"] = ObservationSeries("GONE", (Observation(time=NOW),))
    ids = {e.station.id for e in store.nearby_buoys(storm.id)}
    assert ids == {"41010", "NOFLAG", "GONE", "PINNED"}


def _alert(alert_id: str, area: str, ends: datetime | None) -> WatchWarningAlert:
    return WatchWarningAlert(
        id=alert_id,
        event="Hurricane Warning",
        kind=None,
        headline=None,
        area_desc=area,
        severity=None,
        urgency=None,
        certainty=None,
        status=None,
        message_type=None,
        sender_name=None,
        sent=None,
        effective=None,
        onset=None,
        expires=None,
        ends=ends,
        description=None,
        instruction=None,
        zones=(),
        same_codes=(),
        rings=(),
    )


def test_expired_alerts_are_not_active() -> None:
    store = Store(Config())
    store.alerts = AlertsResult(
        (_alert("a", "Old County", NOW - timedelta(hours=1)), _alert("b", "Live County", NOW + timedelta(hours=1)))
    )
    assert [a.id for a in store.active_alerts(NOW)] == ["b"]


async def test_the_main_and_detail_screens_pass_now_to_the_age_aware_readers() -> None:
    from eyewall.ui.screens.main import MainScreen
    from tests.ui_support import into_the_storm, press, replay_app, running

    app = replay_app()
    async with running(app) as pilot:
        await into_the_storm(pilot)
        seen: list[datetime | None] = []
        original = app.store.nearby_buoys
        app.store.nearby_buoys = lambda storm_id, at=None: (seen.append(at), original(storm_id, at))[1]  # type: ignore[method-assign]
        screen = app.screen
        assert isinstance(screen, MainScreen)
        screen.refresh_data()
        assert seen and all(at is not None for at in seen)
        seen.clear()
        await press(pilot, "enter")  # the storm detail screen
        app.screen.refresh_data()  # type: ignore[attr-defined]
        assert seen and all(at is not None for at in seen)


# ---- review follow-ups ----------------------------------------------------------------------------------------


def _store_with_a_buoy_by_the_storm() -> tuple[Store, StormState]:
    store = Store(Config())
    storm = make_storm("5", lat=25.0, lon=-75.0)
    state = StormState(storm, advisories("5"))
    store.storms[storm.id] = state
    store.stations = {"41010": Station("41010", "NEAR", 25.0, -74.9, met=True)}
    return store, state


def test_a_buoy_whose_series_stopped_refreshing_is_not_silent_while_latest_obs_still_lists_it() -> None:
    store, _ = _store_with_a_buoy_by_the_storm()
    store.series["41010"] = ObservationSeries("41010", (Observation(time=T0 - timedelta(hours=3), wind_speed_mps=5.0),))
    assert [e.kind for e in store.buoy_events(T0)] == [EventKind.BUOY_SILENT]
    store.latest["41010"] = LatestObservation(
        "41010", 25.0, -74.9, Observation(time=T0 - timedelta(minutes=20), wind_speed_mps=5.0)
    )
    assert st.buoy_state(store, "41010", T0) == "ok"
    assert store.buoy_events(T0) == []


def _fixes_at(state: StormState, issued: datetime, *fixes: ForecastFix) -> StormState:
    tcm = replace(state.advisories.forecast, issued=issued, fixes=fixes)
    return StormState(state.storm, replace(state.advisories, forecast=tcm))


def test_when_every_forecast_fix_is_past_a_station_by_the_last_one_is_kept_with_an_eta_of_zero() -> None:
    store, state = _store_with_a_buoy_by_the_storm()
    store.storms[state.storm.id] = _fixes_at(
        state, T0, fix(T0 + timedelta(hours=6), 25.0, -74.0), fix(T0 + timedelta(hours=12), 25.0, -73.0)
    )
    store.stations = {"41010": Station("41010", "EAST", 25.0, -73.0, met=True)}
    assert [e.station.id for e in store.nearby_buoys(state.storm.id, T0)] == ["41010"]
    later = store.nearby_buoys(state.storm.id, T0 + timedelta(hours=20))
    assert [e.station.id for e in later] == ["41010"]
    assert later[0].eta_hours == 0 and later[0].near_now


def test_a_first_fix_already_past_does_not_leave_a_chord_across_the_real_track() -> None:
    store, state = _store_with_a_buoy_by_the_storm()
    # the storm swings south around the bend at hour 12 before heading to hour 24
    store.storms[state.storm.id] = _fixes_at(
        state, T0, fix(T0 + timedelta(hours=12), 20.0, -75.0), fix(T0 + timedelta(hours=24), 20.0, -70.0)
    )
    now = T0 + timedelta(hours=13)
    center, ahead = track_from(store.storms[state.storm.id], (25.0, -75.0), now)
    assert [f.hours for f in ahead] == [11.0]
    assert center[0] < 20.0 + 0.01 and center[0] > 19.5 and center[1] > -75.0  # just past the bend, on the real track
    assert track_from(store.storms[state.storm.id], (25.0, -75.0), None)[0] == (25.0, -75.0)
    # a station on the leg from the bend to hour 24 is still found, ETA counted from now
    store.stations = {"41010": Station("41010", "LEG", 20.0, -72.5, met=True)}
    found = store.nearby_buoys(state.storm.id, now)
    assert [e.station.id for e in found] == ["41010"] and 0 < found[0].eta_hours < 11


def test_the_feed_position_is_anchored_at_its_own_update_time_not_the_older_tcm() -> None:
    _, state = _store_with_a_buoy_by_the_storm()
    tcm_time = T0 - timedelta(hours=3)  # the TCM is held at the previous advisory; the feed is a full advisory ahead
    held = _fixes_at(state, tcm_time, fix(T0 + timedelta(hours=3), 25.0, -74.0))
    held = replace(held, storm=replace(held.storm, last_update=T0))
    center, _ = track_from(held, (25.0, -75.0), T0 + timedelta(minutes=10))
    assert center[1] == pytest.approx(-75.0, abs=0.1)  # 10 minutes into a 3 hour leg, not 3 hours 10 into it


def test_alert_expiry_uses_ends_then_expires_and_no_end_means_still_active() -> None:
    store = Store(Config())
    past, future = NOW - timedelta(hours=1), NOW + timedelta(hours=1)
    store.alerts = AlertsResult(
        (
            replace(_alert("expires-only-past", "A", None), expires=past),
            replace(_alert("expires-only-future", "B", None), expires=future),
            replace(_alert("ends-later", "C", future), expires=past),  # ends wins over expires
            replace(_alert("ends-earlier", "D", past), expires=future),
            _alert("neither", "E", None),
        )
    )
    assert [a.id for a in store.active_alerts(NOW)] == ["expires-only-future", "ends-later", "neither"]


def test_the_map_is_told_what_time_it_is() -> None:
    store, state = _store_with_a_buoy_by_the_storm()
    seen: list[datetime | None] = []
    original_buoys, original_tides = store.nearby_buoys, store.nearby_tides
    store.nearby_buoys = lambda storm_id, at=None: (seen.append(at), original_buoys(storm_id, at))[1]  # type: ignore[method-assign]
    store.nearby_tides = lambda storm_id, at=None: (seen.append(at), original_tides(storm_id, at))[1]  # type: ignore[method-assign]
    adapt.station_marks(store, state.storm.id, NOW)
    assert seen == [NOW, NOW]


def test_map_marks_and_table_rows_go_stale_at_the_same_age() -> None:
    store = Store(Config())
    gauge = TideStation("8651370", "Duck", 36.18, -75.75, "NC")
    store.stations = {"41010": Station("41010", "CANAVERAL", 28.9, -78.5)}
    for minutes, stale in ((110, False), (130, True)):
        store.latest["41010"] = _latest("41010", minutes)
        assert adapt._wind_kt_of(store, "41010", NOW)[1] is stale
        assert (st.buoy_state(store, "41010", NOW) == "silent") is stale
        series = TideSeries(
            "8651370", "MLLW", water_level=ObsParsed((WaterLevelReading(NOW - timedelta(minutes=minutes), 3.0),))
        )
        store.tide_series[gauge.id] = series
        assert adapt._tide_mark(store, gauge, NOW).stale is stale
