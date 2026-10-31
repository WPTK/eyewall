"""The pure station helpers behind the Buoys and Tides tabs, the buoy charts, the search and the tide residual."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from eyewall.config import Config, toggle_watch, watchlist_ids, with_watchlist
from eyewall.models.obs import (
    Observation,
    Prediction,
    Station,
    TideSeries,
    TideStation,
    WaterLevelReading,
)
from eyewall.models.obs import Parsed as ObsParsed
from eyewall.state.store import Store
from eyewall.state.tides import is_silent, latest_residual, observation_age, predicted_at
from eyewall.ui import stations as st
from eyewall.ui.glyphs import glyphs_for
from eyewall.units import PRESETS

NOW = datetime(2025, 8, 20, 12, 0, tzinfo=UTC)
G = glyphs_for("unicode")


def obs(minutes_ago: int, **fields: float) -> Observation:
    return Observation(time=NOW - timedelta(minutes=minutes_ago), **fields)


def level(minutes_ago: int, value: float | None) -> WaterLevelReading:
    return WaterLevelReading(NOW - timedelta(minutes=minutes_ago), value)


def test_wind_is_banded_at_34_50_and_64_knots() -> None:
    assert st.banded("x", 20).style == ""
    assert st.banded("x", 34).style != st.banded("x", 50).style != st.banded("x", 64).style
    assert st.banded("x", 33.9).style == ""
    assert st.banded("x", None).style == ""
    assert st.banded("x", 34).style != ""


def test_falling_pressure_is_flagged_by_size() -> None:
    preset = PRESETS["nautical"]
    assert st.delta_text(None, preset, G).plain == "--"
    assert st.delta_text(-0.5, preset, G).style == ""
    assert "ffa63d" in str(st.delta_text(-1.2, preset, G).style)
    assert "ff4d4d" in str(st.delta_text(-3.4, preset, G).style)
    assert st.delta_text(-1.2, preset, G).plain.startswith(G.falling)
    assert st.delta_text(1.2, preset, G).plain.startswith(G.rising)
    assert st.delta_text(0.0, preset, G).plain.startswith(G.steady)


def test_residual_colors_grow_with_the_surge_and_mark_a_drawdown() -> None:
    assert st.residual_color(0.3) == ""
    assert st.residual_color(1.0) != st.residual_color(2.0) != st.residual_color(4.0)
    assert "ffe94a" in st.residual_color(1.4)
    assert st.residual_color(-1.5) == st.NEGATIVE_RESIDUAL
    assert st.residual_color(-0.4) == ""


def test_chart_series_keeps_only_the_range_and_puts_hours_back_on_x() -> None:
    rows = [obs(30, pressure_hpa=1000.0, wind_speed_mps=10.0), obs(60 * 30, pressure_hpa=990.0)]
    lines = st.chart_series(rows, NOW, 24, PRESETS["nautical"])
    assert set(lines) == {"pressure", "wind", "wave"}
    pressure = lines["pressure"][0].points
    assert [y for _x, y in pressure if y is not None] == [pytest.approx(1000.0, abs=0.01)]
    assert pressure[0][0] == pytest.approx(-0.5)
    assert st.has_points(lines["pressure"])
    assert not st.has_points(lines["wave"])


def test_time_ticks_split_the_range_in_four() -> None:
    ticks = st.time_ticks(48)
    assert [t.label for t in ticks] == ["-48h", "-36h", "-24h", "-12h", "now"]
    assert [t.value for t in ticks] == [-48, -36, -24, -12, 0]


def test_extremes_use_the_supplemental_rows_when_given() -> None:
    rows = [obs(30, pressure_hpa=1000.0, gust_mps=20.0), obs(90, pressure_hpa=996.0, gust_mps=25.0)]
    ext = st.extremes_for(rows, [], NOW, 24)
    assert ext.min_pressure_hpa == pytest.approx(996.0)
    text = st.extremes_text(ext, 24, PRESETS["nautical"], UTC, supl_note="no supplemental file")
    assert "no supplemental file" in text.plain
    assert "Min pressure" in text.plain


def _store() -> Store:
    store = Store(Config())
    store.stations = {
        "41002": Station("41002", "S HATTERAS", 31.76, -74.84, type="buoy", owner="NDBC"),
        "41010": Station("41010", "CANAVERAL EAST", 28.9, -78.5, type="buoy", owner="NDBC"),
        "44014": Station("44014", "VIRGINIA BEACH", 36.6, -74.8, type="buoy", owner="NDBC"),
    }
    store.tide_stations = (
        TideStation("8651370", "Duck", 36.18, -75.75, "NC"),
        TideStation("8410140", "Eastport", 44.9, -66.98, "ME"),
        TideStation("9999999", "Port 41002", 30.0, -80.0, "FL"),
    )
    return store


def test_search_ranks_exact_id_then_prefix_then_contains_then_name() -> None:
    store = _store()
    hits = st.search_stations(store, "41002")
    assert [h.id for h in hits] == ["41002", "9999999"]
    assert hits[0].kind == "ndbc" and hits[1].kind == "coops"
    assert [h.id for h in st.search_stations(store, "410")] == ["41002", "41010", "8410140", "9999999"]
    assert [h.id for h in st.search_stations(store, "canaveral")] == ["41010"]
    assert [h.id for h in st.search_stations(store, "beach virginia")] == ["44014"]
    assert [h.kind for h in st.search_stations(store, "duck")] == ["coops"]


def test_search_with_no_words_or_no_match_finds_nothing() -> None:
    assert st.search_stations(_store(), "  ") == []
    assert st.search_stations(_store(), "zzz") == []
    assert len(st.search_stations(_store(), "4", limit=2)) == 2


def test_predicted_at_matches_the_nearest_step_within_tolerance() -> None:
    preds = tuple(Prediction(NOW + timedelta(minutes=6 * k), 1.0 + k) for k in range(-3, 4))
    assert predicted_at(preds, NOW) == 1.0
    assert predicted_at(preds, NOW + timedelta(minutes=4)) == 2.0
    assert predicted_at(preds, NOW + timedelta(hours=3)) is None
    assert predicted_at((), NOW) is None


def test_latest_residual_is_observed_minus_predicted_at_the_same_moment() -> None:
    series = TideSeries(
        "8651370",
        "MLLW",
        water_level=ObsParsed((level(0, 3.4), level(6, 3.0))),
        predictions=ObsParsed((Prediction(NOW - timedelta(minutes=6), 2.5), Prediction(NOW, 2.6))),
    )
    found = latest_residual(series)
    assert found is not None
    assert found.residual_ft == pytest.approx(0.8)
    assert (found.observed_ft, found.predicted_ft) == (3.4, 2.6)


def test_no_residual_without_a_prediction_for_the_newest_level() -> None:
    no_predictions = TideSeries("1", "MLLW", water_level=ObsParsed((level(0, 3.0),)))
    assert latest_residual(no_predictions) is None
    stale_predictions = TideSeries(
        "1",
        "MLLW",
        water_level=ObsParsed((level(0, 3.0),)),
        predictions=ObsParsed((Prediction(NOW - timedelta(hours=5), 2.0),)),
    )
    assert latest_residual(stale_predictions) is None


def test_a_gauge_with_an_old_level_is_silent() -> None:
    fresh = TideSeries("1", "MLLW", water_level=ObsParsed((level(30, 1.0),)))
    old = TideSeries("1", "MLLW", water_level=ObsParsed((level(60 * 5, 1.0),)))
    empty = TideSeries("1", "MLLW")
    assert not is_silent(fresh, NOW) and is_silent(old, NOW)
    assert not is_silent(empty, NOW)
    assert observation_age(old, NOW) == timedelta(hours=5)
    assert observation_age(empty, NOW) is None


def test_a_buoy_with_no_data_is_waiting_or_dark_and_a_silent_one_is_not_reporting() -> None:
    store = _store()
    assert st.buoy_state(store, "41002", NOW) == "waiting"
    from eyewall.models.obs import ObservationSeries

    store.series["41002"] = ObservationSeries("41002", (obs(60 * 6, wind_speed_mps=5.0),))
    assert st.buoy_state(store, "41002", NOW) == "silent"
    store.series["41002"] = ObservationSeries("41002", (obs(20, wind_speed_mps=5.0),))
    assert st.buoy_state(store, "41002", NOW) == "ok"


def test_watchlist_toggle_adds_removes_and_rejects_bad_ids() -> None:
    config = Config()
    added, watched = toggle_watch(config, "ndbc", " 44014 ")
    assert watched and "44014" in watchlist_ids(added, "ndbc")
    removed, watched = toggle_watch(added, "ndbc", "44014")
    assert not watched and "44014" not in watchlist_ids(removed, "ndbc")
    _same, watched = toggle_watch(config, "coops", "no good!")
    assert not watched
    with pytest.raises(ValueError):
        with_watchlist(config, "weather", ["1"])
    assert watchlist_ids(with_watchlist(config, "coops", ["8651370", "8651370", "x y"]), "coops") == ("8651370",)


def test_a_residual_that_rounds_to_zero_never_shows_a_minus_sign() -> None:
    assert st._signed(-0.02, "ft", 1) == "+0.0 ft"
    assert st._signed(-0.4, "ft", 1) == "-0.4 ft"
    assert st._signed(0.0, "ft", 1) == "+0.0 ft"


def test_a_latest_obs_only_row_never_shows_a_negative_age() -> None:
    from eyewall.models.obs import LatestObservation

    store = _store()
    store.latest["41002"] = LatestObservation("41002", 31.76, -74.84, obs(-5, wind_speed_mps=5.0))  # 5 min ahead
    entry = st.Entry(store.stations["41002"])
    cells = st.buoy_row(store, entry, NOW, PRESETS["nautical"], G)
    assert not cells[10].plain.startswith("-")


def test_a_buoy_missing_from_a_loaded_latest_obs_is_not_reporting() -> None:
    from eyewall.models.obs import LatestObservation

    store = _store()
    store.latest["41010"] = LatestObservation("41010", 28.9, -78.5, obs(10, wind_speed_mps=5.0))
    assert st.buoy_state(store, "41002", NOW) == "dark"
    assert st.buoy_state(store, "41010", NOW) == "ok"
