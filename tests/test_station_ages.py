"""Station and storm data is shown at its real age: nothing old is passed off as current."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from eyewall.config import Config, with_watchlist
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
from eyewall.state.store import Store, StormState, track_fixes
from eyewall.ui import adapt
from eyewall.ui import format as fmt
from eyewall.ui import stations as st
from eyewall.ui.glyphs import glyphs_for
from eyewall.units import PRESETS
from tests.state_support import T0, advisories, make_storm

NOW = datetime(2026, 9, 1, 18, 0, tzinfo=UTC)
G = glyphs_for("unicode")
NAUTICAL = PRESETS["nautical"]


def fix(valid: datetime, lat: float, lon: float) -> ForecastFix:
    return ForecastFix(12, valid, lat, lon, None, None, WindRadii())


# ---- the wind panel -------------------------------------------------------------------------------------------


def test_the_wind_panel_shows_the_storm_feed_when_it_is_newer_than_the_forecast_advisory() -> None:
    store = Store(Config())
    storm = replace(make_storm("5"), intensity_kt=115, pressure_mb=950)
    adv = advisories("5")
    tcm = replace(adv.forecast, max_wind_kt=100, pressure_mb=960)
    store.storms[storm.id] = StormState(storm, replace(adv, forecast=tcm))
    text = fmt.wind_panel(store, storm.id, NAUTICAL).plain
    assert "115" in text and "100" not in text and "950" in text and "960" not in text


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


# ---- the dashboard panels -------------------------------------------------------------------------------------


def test_cut_text_ends_in_an_ellipsis_at_a_word() -> None:
    assert fmt._cut("short", 90) == "short"
    cut = fmt._cut("alpha beta gamma delta", 14)
    assert cut == "alpha beta…" and len(cut) <= 14


def test_the_buoy_strip_shows_the_pressure_change_in_the_preset_unit() -> None:
    store = Store(Config())
    storm = make_storm("5", lat=25.0, lon=-75.0)
    store.storms[storm.id] = StormState(storm, advisories("5"))
    store.stations = {"41010": Station("41010", "EAST", 25.5, -75.0, met=True)}
    rows = tuple(
        Observation(time=NOW - timedelta(minutes=30 + 60 * h), pressure_hpa=1000.0 + 1.0 * h, wind_speed_mps=10.0)
        for h in range(5)
    )
    store.series["41010"] = ObservationSeries("41010", rows)
    us = fmt.buoy_strip(store, storm.id, NOW, PRESETS["us"], G).plain
    nautical = fmt.buoy_strip(store, storm.id, NOW, NAUTICAL, G).plain
    assert "inHg" in us and "3.0" not in us.split("inHg")[1]
    assert "3.0" in nautical


def test_expired_alerts_are_left_out_of_the_panel() -> None:
    store = Store(Config())
    store.alerts = AlertsResult(
        (_alert("a", "Old County", NOW - timedelta(hours=1)), _alert("b", "Live County", NOW + timedelta(hours=1)))
    )
    assert [a.id for a in store.active_alerts(NOW)] == ["b"]
    text = fmt.ww_panel(store, None, G, NOW).plain
    assert "Live County" in text and "Old County" not in text


async def test_the_dashboard_and_detail_screens_pass_now_to_the_age_aware_readers() -> None:
    from eyewall.ui.screens.dashboard import DashboardScreen
    from eyewall.ui.widgets.panels import Panel
    from tests.ui_support import into_the_storm, press, replay_app, running

    app = replay_app()
    async with running(app) as pilot:
        await into_the_storm(pilot)
        now = app.now()
        app.store.alerts = AlertsResult(
            (
                _alert("old", "Old County", now - timedelta(hours=1)),
                _alert("new", "Live County", now + timedelta(hours=1)),
            )
        )
        screen = app.screen
        assert isinstance(screen, DashboardScreen)
        screen.refresh_selection()
        ww = next(p for p in screen.query(Panel) if p.kind == "ww")
        text = str(ww.body.render())
        assert "Live County" in text and "Old County" not in text

        seen: list[datetime | None] = []
        original = app.store.nearby_buoys
        app.store.nearby_buoys = lambda storm_id, at=None: (seen.append(at), original(storm_id, at))[1]  # type: ignore[method-assign]
        await press(pilot, "enter")  # the storm detail screen
        app.screen._refresh_stations()  # type: ignore[attr-defined]
        assert seen and all(at is not None for at in seen)
