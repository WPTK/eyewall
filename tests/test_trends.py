from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from eyewall.models.obs import Observation, ObservationSeries, SupplementalReading
from eyewall.ndbc.stdmet import parse_stdmet
from eyewall.ndbc.supl import parse_supl
from eyewall.state.trends import (
    Extremes,
    PressureTendency,
    Trend,
    gust_trend,
    interval_extremes,
    is_silent,
    observation_age,
    pressure_tendency,
    station_trends,
    wind_trend,
)

FIXTURES = Path(__file__).parent / "fixtures" / "ndbc"
NOW = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)


def obs(minutes_ago: float, **values: float) -> Observation:
    return Observation(time=NOW - timedelta(minutes=minutes_ago), **values)


def series(*observations: Observation) -> ObservationSeries:
    return ObservationSeries("41010", tuple(sorted(observations, key=lambda o: o.time, reverse=True)))


# --- pressure tendency ------------------------------------------------------------------------------------------


def test_ptdy_is_used_when_the_newest_reading_carries_it():
    rows = [obs(0, pressure_hpa=1005.0, pressure_tendency_hpa=-2.4), obs(180, pressure_hpa=1010.0)]
    assert pressure_tendency(rows) == PressureTendency(-2.4, "ptdy", 3.0)


def test_without_ptdy_it_is_computed_from_the_reading_three_hours_earlier():
    rows = [obs(0, pressure_hpa=1005.0), obs(60, pressure_hpa=1007.0), obs(180, pressure_hpa=1010.0)]
    tendency = pressure_tendency(rows)
    assert tendency == PressureTendency(-5.0, "series", 3.0)


def test_the_closest_reading_to_three_hours_back_is_chosen_within_twenty_minutes():
    rows = [obs(0, pressure_hpa=1000.0), obs(170, pressure_hpa=1004.0), obs(200, pressure_hpa=1006.0)]
    tendency = pressure_tendency(rows)
    assert tendency is not None
    assert tendency.delta_hpa == pytest.approx(-4.0)  # 10 minutes off beats 20 minutes off
    assert tendency.hours == pytest.approx(170 / 60)  # the real gap is reported, not pretended to be three hours


def test_no_reading_near_three_hours_back_means_no_tendency():
    assert pressure_tendency([obs(0, pressure_hpa=1000.0), obs(120, pressure_hpa=1002.0)]) is None
    assert pressure_tendency([obs(0, pressure_hpa=1000.0), obs(210, pressure_hpa=1002.0)]) is None  # 30 min off
    assert pressure_tendency([obs(0, pressure_hpa=1000.0)]) is None


def test_a_newer_row_without_pressure_does_not_hide_the_tendency():
    rows = [obs(0, wave_height_m=1.0), obs(10, pressure_hpa=1003.0), obs(190, pressure_hpa=1008.0)]
    assert pressure_tendency(rows) == PressureTendency(-5.0, "series", pytest.approx(3.0))


def test_ptdy_on_an_older_row_is_not_used_for_a_newer_pressure():
    rows = [
        obs(10, pressure_hpa=1003.0),
        obs(60, pressure_hpa=1004.0, pressure_tendency_hpa=-1.0),
        obs(190, pressure_hpa=1008.0),
    ]
    tendency = pressure_tendency(rows)
    assert tendency is not None
    assert tendency.source == "series"
    assert tendency.delta_hpa == pytest.approx(-5.0)


def test_no_pressure_anywhere_gives_none_and_order_does_not_matter():
    assert pressure_tendency([]) is None
    assert pressure_tendency([obs(0, wind_speed_mps=5.0)]) is None
    forward = [obs(0, pressure_hpa=1000.0), obs(180, pressure_hpa=1003.0)]
    assert pressure_tendency(forward) == pressure_tendency(list(reversed(forward)))


# --- wind and gust trend ----------------------------------------------------------------------------------------


def test_wind_trend_compares_with_the_reading_three_hours_back():
    rows = [obs(0, wind_speed_mps=14.0), obs(90, wind_speed_mps=10.0), obs(180, wind_speed_mps=8.0)]
    assert wind_trend(rows) == Trend(delta=6.0, direction="rising", hours=3.0)


def test_falling_and_steady_use_a_band_of_one_metre_per_second():
    assert wind_trend([obs(0, wind_speed_mps=7.0), obs(180, wind_speed_mps=9.0)]) == Trend(-2.0, "falling", 3.0)
    assert wind_trend([obs(0, wind_speed_mps=9.9), obs(180, wind_speed_mps=9.0)]) == Trend(
        pytest.approx(0.9), "steady", 3.0
    )
    assert wind_trend([obs(0, wind_speed_mps=10.0), obs(180, wind_speed_mps=9.0)]).direction == "steady"  # type: ignore[union-attr]
    assert wind_trend([obs(0, wind_speed_mps=10.1), obs(180, wind_speed_mps=9.0)]).direction == "rising"  # type: ignore[union-attr]
    custom = wind_trend([obs(0, wind_speed_mps=10.5), obs(180, wind_speed_mps=9.0)], steady_band=2.0)
    assert custom is not None
    assert custom.direction == "steady"


def test_gust_trend_uses_the_gust_column_and_other_windows():
    rows = [obs(0, gust_mps=20.0, wind_speed_mps=12.0), obs(60, gust_mps=15.0), obs(180, gust_mps=11.0)]
    assert gust_trend(rows) == Trend(9.0, "rising", 3.0)
    assert gust_trend(rows, hours=1.0) == Trend(5.0, "rising", 1.0)


def test_a_trend_needs_a_reading_at_the_right_distance_back_and_a_value_in_it():
    assert wind_trend([obs(0, wind_speed_mps=5.0)]) is None
    assert wind_trend([obs(0, wind_speed_mps=5.0), obs(60, wind_speed_mps=4.0)]) is None
    assert wind_trend([obs(0, wind_speed_mps=5.0), obs(180, pressure_hpa=1010.0)]) is None  # that row has no wind
    assert wind_trend([]) is None
    assert gust_trend([obs(0, wind_speed_mps=5.0)]) is None  # no gust at all


# --- age and silence --------------------------------------------------------------------------------------------


def test_age_is_measured_from_the_newest_observation():
    assert observation_age(series(obs(25, wind_speed_mps=5.0), obs(95)), NOW) == timedelta(minutes=25)


def test_a_clock_a_little_behind_the_station_gives_age_zero_not_negative():
    assert observation_age(series(obs(-5)), NOW) == timedelta(0)


def test_a_station_with_no_observations_has_no_age():
    assert observation_age(ObservationSeries("42040"), NOW) is None


def test_silent_means_it_was_reporting_and_the_newest_row_is_now_old():
    assert is_silent(series(obs(119)), NOW) is False
    assert is_silent(series(obs(120)), NOW) is False  # exactly two hours is not yet silent
    assert is_silent(series(obs(121)), NOW) is True
    assert is_silent(series(obs(121)), NOW, silent_after=timedelta(hours=3)) is False
    assert is_silent(series(obs(35)), NOW, silent_after=timedelta(minutes=30)) is True


def test_a_station_that_never_reported_is_not_reporting_rather_than_silent():
    dark = ObservationSeries("42040")
    assert is_silent(dark, NOW) is False
    assert not dark.reporting


# --- extremes ---------------------------------------------------------------------------------------------------


def test_extremes_from_regular_rows_alone():
    rows = [
        obs(0, pressure_hpa=1004.0, gust_mps=15.0),
        obs(60, pressure_hpa=1001.5, gust_mps=22.0),
        obs(120, pressure_hpa=1003.0, gust_mps=22.0),
        obs(180, wind_speed_mps=30.0),
    ]
    found = interval_extremes(rows)
    assert found == Extremes(
        min_pressure_hpa=1001.5,
        min_pressure_time=NOW - timedelta(minutes=60),
        peak_gust_mps=22.0,
        peak_gust_time=NOW - timedelta(minutes=120),  # a tie goes to the earlier reading
        peak_wind_mps=None,
        peak_wind_time=None,
    )


def test_supplemental_rows_supply_the_true_minimum_and_the_peak_wind_with_their_own_times():
    rows = [obs(0, pressure_hpa=1004.0, gust_mps=15.0), obs(10, pressure_hpa=1002.0, gust_mps=16.0)]
    extra = [
        SupplementalReading(
            time=NOW - timedelta(minutes=10),
            min_pressure_hpa=1000.8,
            min_pressure_time=NOW - timedelta(minutes=14),
            peak_wind_mps=18.0,
            peak_wind_time=NOW - timedelta(minutes=12),
        ),
        SupplementalReading(time=NOW, min_pressure_hpa=1003.5, peak_wind_mps=12.0),
    ]
    found = interval_extremes(rows, extra)
    assert (found.min_pressure_hpa, found.min_pressure_time) == (1000.8, NOW - timedelta(minutes=14))
    assert (found.peak_gust_mps, found.peak_gust_time) == (16.0, NOW - timedelta(minutes=10))
    assert (found.peak_wind_mps, found.peak_wind_time) == (18.0, NOW - timedelta(minutes=12))


def test_a_supplemental_row_without_clock_times_falls_back_to_its_own_time():
    extra = [SupplementalReading(time=NOW, min_pressure_hpa=999.0, peak_wind_mps=20.0)]
    found = interval_extremes([], extra)
    assert (found.min_pressure_time, found.peak_wind_time) == (NOW, NOW)


def test_since_and_until_bound_the_period():
    rows = [obs(0, pressure_hpa=1004.0), obs(60, pressure_hpa=1000.0), obs(240, pressure_hpa=990.0)]
    assert interval_extremes(rows, since=NOW - timedelta(hours=2)).min_pressure_hpa == 1000.0
    assert interval_extremes(rows, until=NOW - timedelta(minutes=30)).min_pressure_hpa == 990.0
    assert interval_extremes(rows, since=NOW - timedelta(minutes=30), until=NOW).min_pressure_hpa == 1004.0
    assert interval_extremes(rows, since=NOW + timedelta(hours=1)) == Extremes()


def test_nothing_in_gives_nothing_out():
    assert interval_extremes([]) == Extremes()
    assert interval_extremes([obs(0, wind_speed_mps=5.0)]) == Extremes()


# --- against the recorded 41010 files ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def recorded() -> tuple[ObservationSeries, tuple[SupplementalReading, ...]]:
    main = parse_stdmet((FIXTURES / "41010_5day.txt").read_text(encoding="utf-8"), "41010")
    extra = parse_supl((FIXTURES / "41010_5day.supl").read_text(encoding="utf-8")).items
    return main, extra


def test_recorded_tendency_is_computed_when_the_newest_row_is_off_the_hour(recorded):
    main, _ = recorded
    tendency = pressure_tendency(main.observations)
    assert tendency is not None
    assert tendency.source == "series"
    assert tendency.delta_hpa == pytest.approx(-0.6)
    assert tendency.hours == 3.0


def test_recorded_tendency_is_ptdy_on_the_hour(recorded):
    main, _ = recorded
    from_the_hour = [o for o in main.observations if o.time <= datetime(2026, 10, 31, 7, 0, tzinfo=UTC)]
    assert pressure_tendency(from_the_hour) == PressureTendency(-0.7, "ptdy", 3.0)


def test_recorded_extremes_prefer_the_supplemental_minimum(recorded):
    main, extra = recorded
    regular = interval_extremes(main.observations)
    combined = interval_extremes(main.observations, extra)
    assert regular.min_pressure_hpa == 1013.8
    assert regular.min_pressure_time == datetime(2026, 10, 29, 7, 50, tzinfo=UTC)
    assert combined.min_pressure_hpa == 1013.7
    assert combined.min_pressure_time == datetime(2026, 10, 29, 7, 54, tzinfo=UTC)
    assert combined.peak_gust_mps == 18.0
    assert combined.peak_gust_time == datetime(2026, 10, 26, 14, 30, tzinfo=UTC)
    assert (combined.peak_wind_mps, combined.peak_wind_time) == (16.0, datetime(2026, 10, 27, 22, 26, tzinfo=UTC))


def test_recorded_summary_for_a_live_station_and_the_same_station_three_hours_later(recorded):
    main, extra = recorded
    now = main.observations[0].time
    live = station_trends(main, extra, now=now, window_hours=72)
    assert live.station_id == "41010"
    assert live.latest == main.latest
    assert live.age == timedelta(0)
    assert live.silent is False
    assert live.pressure_tendency == PressureTendency(pytest.approx(-0.6), "series", 3.0)
    assert live.wind == Trend(0.0, "steady", 3.0)
    assert live.gust == Trend(1.0, "steady", 3.0)
    assert live.extremes.peak_gust_mps == 17.0  # the 18 m/s gust was more than 72 hours ago
    assert live.extremes.peak_wind_mps == 15.0

    later = station_trends(main, extra, now=now + timedelta(hours=3))
    assert later.age == timedelta(hours=3)
    assert later.silent is True
    assert later.extremes.peak_gust_mps == 18.0  # no window: the whole file


def test_a_dark_buoys_summary_is_empty_but_not_silent():
    summary = station_trends(ObservationSeries("42040"), now=NOW)
    assert summary.latest is None
    assert summary.age is None
    assert summary.silent is False
    assert summary.pressure_tendency is None
    assert (summary.wind, summary.gust) == (None, None)
    assert summary.extremes == Extremes()
