"""The buoy and gauge sentences, from the saved NDBC and CO-OPS payloads."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from eyewall.coops.data import parse_predictions, parse_water_level
from eyewall.coops.stations import parse_tide_stations
from eyewall.models.obs import Observation, TideSeries
from eyewall.ndbc.stations import parse_stations
from eyewall.ndbc.stdmet import parse_stdmet
from eyewall.state.nearby import nearby_stations
from eyewall.state.tides import latest_residual
from eyewall.state.trends import (
    Extremes,
    PressureTendency,
    interval_extremes,
    pressure_tendency,
    wave_trend,
    wind_trend,
)
from eyewall.ui.words import station as sw
from eyewall.units import PRESETS
from tests.state_support import T0, obs
from tests.words_support import assert_traces

NDBC = Path(__file__).parent / "fixtures" / "ndbc"
COOPS = Path(__file__).parent / "fixtures" / "coops"
EDT = timezone(timedelta(hours=-4), "EDT")


@pytest.fixture(scope="module")
def rows() -> tuple[Observation, ...]:
    return parse_stdmet((NDBC / "41010_5day.txt").read_text(encoding="utf-8"), "41010").observations


@pytest.fixture(scope="module")
def entry():
    stations = {s.id: s for s in parse_stations((NDBC / "activestations.xml").read_bytes()).items}
    found = nearby_stations((30.0, -75.0), [], [stations["41010"]])
    assert found
    return found[0]


def wave_row(rows):
    return next(o for o in rows if o.wave_height_m is not None)


# ------------------------------------------------------------------------------------------------------ buoy lead


@pytest.mark.parametrize(
    ("preset", "text"),
    [
        (
            "nautical",
            "Buoy 41010 (CANAVERAL EAST - 120NM East of Cape Canaveral), 195 nm WSW of Erin: "
            "wind 16 kt from the ENE, gusting 19 kt, waves 6 ft.",
        ),
        (
            "us",
            "Buoy 41010 (CANAVERAL EAST - 120NM East of Cape Canaveral), 225 mi WSW of Erin: "
            "wind 18 mph from the ENE, gusting 22 mph, waves 6 ft.",
        ),
        (
            "metric",
            "Buoy 41010 (CANAVERAL EAST - 120NM East of Cape Canaveral), 360 km WSW of Erin: "
            "wind 29 km/h from the ENE, gusting 36 km/h, waves 1.9 m.",
        ),
    ],
)
def test_the_buoy_lead_in_each_preset(rows, entry, preset, text):
    waves = wave_row(rows)
    words = sw.buoy_lead(entry, "Erin", rows[0], waves, PRESETS[preset])
    assert_traces(words, entry=entry, obs=rows[0], waves=waves)
    assert words.text == text


def test_the_waves_come_from_the_row_given_not_the_newest(rows, entry):
    assert rows[0].wave_height_m is None  # the newest row has no waves; the caller picks the one that does
    assert "waves" not in sw.buoy_lead(entry, "Erin", rows[0], None, PRESETS["us"]).text


def test_a_buoy_with_no_wind_direction_gust_or_speed_still_reads(entry):
    bare = Observation(time=T0, wind_speed_mps=10.0)
    assert sw.buoy_lead(entry, "Erin", bare, None, PRESETS["nautical"]).text.endswith(": wind 19 kt.")
    none = Observation(time=T0)
    assert sw.buoy_lead(entry, "Erin", none, none, PRESETS["nautical"]).text.endswith(": wind not reported.")


def test_a_buoy_at_the_storm_centre_is_said_to_be_at_it(entry):
    close = replace(entry, distance_nm=2.0)
    assert ", at Erin:" in sw.buoy_lead(close, "Erin", Observation(time=T0), None, PRESETS["us"]).text


def test_a_buoy_without_a_name_has_no_empty_brackets(entry):
    nameless = replace(entry, station=replace(entry.station, name=""))
    assert sw.buoy_lead(nameless, "Erin", Observation(time=T0), None, PRESETS["us"]).text.startswith("Buoy 41010, ")


# --------------------------------------------------------------------------------------------------------- trends


@pytest.mark.parametrize(
    ("delta", "preset", "text"),
    [
        (-3.2, "nautical", "Pressure is falling fast: down 3.2 mb in the last 3 hours."),
        (-3.0, "nautical", "Pressure is falling fast: down 3.0 mb in the last 3 hours."),
        (-1.4, "metric", "Pressure is falling: down 1.4 hPa in the last 3 hours."),
        (-1.0, "us", "Pressure is falling: down 0.03 inHg in the last 3 hours."),
        (-0.6, "us", "Pressure is steady over the last 3 hours."),
        (0.9, "us", "Pressure is steady over the last 3 hours."),
        (1.0, "nautical", "Pressure is rising: up 1.0 mb in the last 3 hours."),
        (2.5, "us", "Pressure is rising: up 0.07 inHg in the last 3 hours."),
    ],
)
def test_pressure_trend_wording_and_thresholds(delta, preset, text):
    tendency = PressureTendency(delta, "ptdy", 3.0)
    assert assert_traces(sw.pressure_trend(tendency, PRESETS[preset]), tendency=tendency).text == text


def test_pressure_trend_over_a_real_series_and_with_no_data(rows):
    assert sw.pressure_trend(pressure_tendency(rows), PRESETS["us"]).text == "Pressure is steady over the last 3 hours."
    assert sw.pressure_trend(None, PRESETS["us"]) is None
    short = PressureTendency(-2.0, "series", 1.0)
    assert sw.pressure_trend(short, PRESETS["nautical"]).text == "Pressure is falling: down 2.0 mb in the last 1 hour."


def synthetic(wind_then, wind_now, wave_then=None, wave_now=None):
    return [
        replace(obs(T0, wind_kt=wind_now), wave_height_m=wave_now),
        replace(obs(T0 - timedelta(hours=3), wind_kt=wind_then), wave_height_m=wave_then),
    ]


@pytest.mark.parametrize(
    ("then", "now", "preset", "text"),
    [
        (20, 35, "nautical", "Wind has picked up by 15 kt in the last 3 hours."),
        (35, 20, "us", "Wind has eased by 17 mph in the last 3 hours."),
        (35, 20, "metric", "Wind has eased by 28 km/h in the last 3 hours."),
        (30, 30.5, "us", "Wind is steady over the last 3 hours."),
    ],
)
def test_wind_trend_wording(then, now, preset, text):
    trend = wind_trend(synthetic(then, now))
    assert assert_traces(sw.wind_trend_sentence(trend, PRESETS[preset]), trend=trend).text == text


@pytest.mark.parametrize(
    ("then", "now", "preset", "text"),
    [
        (2.0, 5.0, "us", "Waves have picked up by 9.8 ft in the last 3 hours."),
        (5.0, 2.0, "metric", "Waves have eased by 3.0 m in the last 3 hours."),
        (3.0, 3.1, "us", "Waves are steady over the last 3 hours."),
    ],
)
def test_wave_trend_wording(then, now, preset, text):
    trend = wave_trend(synthetic(10, 10, then, now))
    assert sw.wave_trend_sentence(trend, PRESETS[preset]).text == text


def test_wave_trend_uses_only_rows_that_have_waves(rows):
    trend = wave_trend(rows)
    assert trend is not None
    assert trend.direction == "steady"
    assert wave_trend([obs(T0, wind_kt=10)]) is None
    assert sw.wave_trend_sentence(None, PRESETS["us"]) is None
    assert sw.wind_trend_sentence(None, PRESETS["us"]) is None


def test_wave_trend_steady_band_is_a_third_of_a_metre():
    assert wave_trend(synthetic(10, 10, 1.0, 1.4)).direction == "rising"
    assert wave_trend(synthetic(10, 10, 1.0, 1.2)).direction == "steady"
    assert wave_trend(synthetic(10, 10, 1.4, 1.0)).direction == "falling"


def test_the_closest_approach_sentence(entry):
    near = replace(entry, closest_approach_nm=40.0, eta_hours=18.4)
    words = assert_traces(sw.approach_sentence(near, PRESETS["us"]), entry=near)
    assert words.text == "The forecast track passes about 45 mi from here in about 18 hours."
    one_hour = replace(near, eta_hours=1.0)
    assert sw.approach_sentence(one_hour, PRESETS["nautical"]).text == (
        "The forecast track passes about 40 nm from here in about 1 hour."
    )
    now = replace(near, eta_hours=0.0)
    assert sw.approach_sentence(now, PRESETS["metric"]).text == (
        "The forecast track is closest to here now, about 75 km away."
    )


# -------------------------------------------------------------------------------------------- silent, dark, waiting


def test_silent_dark_and_waiting_buoys(rows):
    now = rows[0].time + timedelta(hours=3, minutes=12)
    silent = sw.state_sentence("silent", rows[0], now, EDT)
    assert assert_traces(silent, obs=rows[0]).text == "No report for 3h12m. Last heard Sat 03:40 AM EDT."
    assert sw.state_sentence("dark", None, now, EDT).text == "Not reporting (NOAA lists it as dark)."
    assert sw.state_sentence("waiting", None, now, EDT).text == "Waiting for the first report."
    assert sw.state_sentence("ok", rows[0], now, EDT) is None


# ----------------------------------------------------------------------------------------------- extremes, readings


def test_extremes_over_the_last_day(rows):
    now = rows[0].time + timedelta(minutes=10)
    extremes = interval_extremes(rows, since=now - timedelta(hours=24), until=now)
    words = assert_traces(sw.extremes_sentence(extremes, PRESETS["us"], EDT), extremes=extremes)
    assert words.text == "Highest gust 27 mph at Fri 09:00 AM EDT; lowest pressure 29.96 inHg at Fri 04:40 AM EDT."
    assert sw.extremes_sentence(extremes, PRESETS["nautical"], EDT).text == (
        "Highest gust 23 kt at Fri 09:00 AM EDT; lowest pressure 1014 mb at Fri 04:40 AM EDT."
    )
    assert sw.extremes_sentence(Extremes(), PRESETS["us"], EDT) is None


def test_extremes_with_only_a_pressure():
    when = datetime(2026, 10, 31, 6, 0, tzinfo=UTC)
    only = Extremes(min_pressure_hpa=990.0, min_pressure_time=when)
    assert sw.extremes_sentence(only, PRESETS["nautical"], EDT).text == "Lowest pressure 990 mb at Sat 02:00 AM EDT."


def test_the_readings_summary_over_a_window(rows):
    since = rows[0].time - timedelta(hours=24)
    words = sw.readings_summary(list(rows), since, PRESETS["us"], EDT)
    assert_traces(words, since=since, observations=list(rows))
    assert words.text == "Since Fri 03:40 AM EDT, wind has held near 18 mph and pressure has risen 0.11 inHg."


def test_the_readings_summary_picked_up_fallen_and_eased_risen():
    then = T0 - timedelta(hours=6)
    up = [obs(then, wind_kt=20, pressure=1005.0), obs(T0, wind_kt=45, pressure=990.0)]
    assert sw.readings_summary(up, then, PRESETS["nautical"], EDT).text == (
        "Since Tue 02:00 AM EDT, wind has picked up from 20 kt to 45 kt and pressure has fallen 15.0 mb."
    )
    down = [obs(then, wind_kt=45, pressure=990.0), obs(T0, wind_kt=20, pressure=1005.0)]
    assert sw.readings_summary(down, then, PRESETS["nautical"], EDT).text == (
        "Since Tue 02:00 AM EDT, wind has eased from 45 kt to 20 kt and pressure has risen 15.0 mb."
    )
    flat = [obs(then, pressure=1000.0), obs(T0, pressure=1000.2)]
    assert sw.readings_summary(flat, then, PRESETS["nautical"], EDT).text == (
        "Since Tue 02:00 AM EDT, pressure has held steady."
    )
    assert sw.readings_summary([obs(T0, wind_kt=5)], then, PRESETS["nautical"], EDT) is None


# ------------------------------------------------------------------------------------------------------- the gauge


@pytest.fixture(scope="module")
def gauge():
    stations = parse_tide_stations((COOPS / "stations_waterlevels.json").read_bytes()).items
    return stations[0]


@pytest.fixture(scope="module")
def tide():
    levels = parse_water_level((COOPS / "water_level_recent.json").read_bytes())
    predictions = parse_predictions((COOPS / "predictions_interval.json").read_bytes())
    inside = tuple(r for r in levels.items if r.time <= predictions.items[-1].time)  # the predictions end at 06:00Z
    return TideSeries("8721604", "MLLW", replace(levels, items=inside), predictions=predictions), levels


NOW = datetime(2026, 10, 31, 6, 10, tzinfo=UTC)


@pytest.mark.parametrize(("preset", "size"), [("nautical", "1.0 ft"), ("us", "1.0 ft"), ("metric", "0.3 m")])
def test_the_gauge_residual_in_each_preset(gauge, tide, preset, size):
    series, _ = tide
    words = sw.gauge_sentence(gauge, series, NOW, PRESETS[preset])
    assert_traces(words, station=gauge, series=series, residual=latest_residual(series))
    assert words.text == f"Water at {gauge.name} is {size} above the predicted tide."


def test_water_below_the_prediction_and_water_at_it(gauge, tide):
    series, _ = tide
    newest = series.water_level.items[0]
    low = replace(series, water_level=replace(series.water_level, items=(replace(newest, level_ft=1.5),)))
    assert "1.4 ft below the predicted tide" in sw.gauge_sentence(gauge, low, NOW, PRESETS["us"]).text
    level = replace(series, water_level=replace(series.water_level, items=(replace(newest, level_ft=2.95),)))
    assert (
        sw.gauge_sentence(gauge, level, NOW, PRESETS["us"]).text == f"Water at {gauge.name} is at the predicted tide."
    )


def test_gauge_with_no_prediction_no_data_or_silent(gauge, tide):
    series, everything = tide
    unpaired = replace(series, water_level=everything)  # the newest level (08:18Z) has no prediction near it
    eight_twenty = datetime(2026, 10, 31, 8, 20, tzinfo=UTC)
    assert sw.gauge_sentence(gauge, unpaired, eight_twenty, PRESETS["us"]).text == (
        f"No tide prediction to compare with at {gauge.name}."
    )
    assert sw.gauge_sentence(gauge, None, NOW, PRESETS["us"]).text == "Waiting for the first water level."
    empty = TideSeries("x", "MLLW")
    assert sw.gauge_sentence(gauge, empty, NOW, PRESETS["us"]).text == "Waiting for the first water level."
    late = datetime(2026, 10, 31, 9, 30, tzinfo=UTC)
    assert sw.gauge_sentence(gauge, series, late, PRESETS["us"]).text == f"No report from {gauge.name} for 3h30m."
