from datetime import UTC, datetime
from pathlib import Path

import pytest

from eyewall.models.obs import ObservationSeries
from eyewall.ndbc.historical import parse_historical
from eyewall.ndbc.stdmet import parse_stdmet

FIXTURES = Path(__file__).parent / "fixtures" / "ndbc"


@pytest.fixture(scope="module")
def five_day() -> ObservationSeries:
    return parse_stdmet((FIXTURES / "41010_5day.txt").read_text(encoding="utf-8"), "41010")


@pytest.fixture(scope="module")
def erin_week() -> ObservationSeries:
    return parse_historical((FIXTURES / "41025h2025_erin_week.txt.gz").read_bytes(), "41025")


def test_the_five_day_file_parses_completely_and_newest_first(five_day):
    assert five_day.station_id == "41010"
    assert len(five_day.observations) == 704
    assert five_day.skipped == 0
    times = [o.time for o in five_day.observations]
    assert times == sorted(times, reverse=True)
    assert five_day.latest == five_day.observations[0]
    assert five_day.reporting
    assert times[0] == datetime(2026, 10, 31, 7, 40, tzinfo=UTC)
    assert times[-1] == datetime(2026, 10, 26, 8, 10, tzinfo=UTC)


def test_a_regular_row_keeps_nws_units_and_leaves_missing_waves_none(five_day):
    obs = five_day.latest
    assert obs is not None
    assert (obs.wind_dir_deg, obs.wind_speed_mps, obs.gust_mps) == (60, 8.0, 10.0)
    assert (obs.pressure_hpa, obs.air_temp_c, obs.water_temp_c, obs.dewpoint_c) == (1018.4, 26.0, 27.5, 22.0)
    assert obs.wave_height_m is None
    assert obs.dominant_period_s is None
    assert obs.visibility_nmi is None
    assert obs.tide_ft is None


def test_wave_rows_fill_in_the_wave_columns(five_day):
    row = next(o for o in five_day.observations if o.time == datetime(2026, 10, 31, 7, 20, tzinfo=UTC))
    assert (row.wave_height_m, row.dominant_period_s, row.average_period_s, row.mean_wave_dir_deg) == (1.9, 7, 5.8, 75)
    with_waves = [o for o in five_day.observations if o.wave_height_m is not None]
    assert 0 < len(with_waves) < len(five_day.observations)


def test_ptdy_sits_at_the_end_of_this_file_and_only_on_the_hour(five_day):
    with_ptdy = [o for o in five_day.observations if o.pressure_tendency_hpa is not None]
    assert len(with_ptdy) == 117
    assert all(o.time.minute == 0 for o in with_ptdy)
    hour = next(o for o in five_day.observations if o.time == datetime(2026, 10, 31, 7, 0, tzinfo=UTC))
    assert hour.pressure_tendency_hpa == -0.7
    assert hour.pressure_hpa == 1018.5  # the neighbouring PRES column was not confused with PTDY


def test_a_row_with_no_pressure_is_kept(five_day):
    assert sum(1 for o in five_day.observations if o.pressure_hpa is None) == 1


def test_a_dark_buoys_404_is_an_empty_series_that_is_not_reporting():
    series = ObservationSeries("42040")
    assert series.latest is None
    assert not series.reporting


def test_the_historical_sample_uses_nine_fills_and_has_no_ptdy(erin_week):
    assert erin_week.station_id == "41025"
    assert erin_week.skipped == 0
    assert len(erin_week.observations) == 1153
    first_ever = erin_week.observations[-1]  # file order is oldest first; the series is newest first
    assert first_ever.time == datetime(2025, 8, 17, 0, 0, tzinfo=UTC)
    assert (first_ever.wind_dir_deg, first_ever.wind_speed_mps, first_ever.gust_mps) == (18, 9.3, 10.7)
    assert first_ever.pressure_hpa == 1015.6
    # 99.00 wave heights and periods, 999 wave direction, 99.0 visibility and 99.00 tide are all fills
    assert first_ever.wave_height_m is None
    assert first_ever.dominant_period_s is None
    assert first_ever.average_period_s is None
    assert first_ever.mean_wave_dir_deg is None
    assert first_ever.visibility_nmi is None
    assert first_ever.tide_ft is None
    assert all(o.pressure_tendency_hpa is None for o in erin_week.observations)


def test_the_historical_sample_holds_hurricane_erins_pass(erin_week):
    pressures = [(o.pressure_hpa, o.time) for o in erin_week.observations if o.pressure_hpa is not None]
    assert min(pressures) == (996.9, datetime(2025, 8, 21, 8, 10, tzinfo=UTC))  # the first of two equal readings
    gusts = [(o.gust_mps, o.time) for o in erin_week.observations if o.gust_mps is not None]
    assert max(gusts)[0] == 25.5
    times = [o.time for o in erin_week.observations]
    assert times == sorted(times, reverse=True)


def test_whole_row_fills_become_all_none():
    text = (
        "#YY  MM DD hh mm WDIR WSPD GST  WVHT   DPD   APD MWD   PRES  ATMP  WTMP  DEWP  VIS  TIDE\n"
        "#yr  mo dy hr mn degT m/s  m/s     m   sec   sec degT   hPa  degC  degC  degC  nmi    ft\n"
        "2025 01 29 03 30 999 99.0 99.0 99.00 99.00 99.00 999 9999.0 999.0  23.4 999.0 99.0 99.00\n"
    )
    obs = parse_stdmet(text, "41010").observations[0]
    assert obs.wind_dir_deg is None
    assert obs.wind_speed_mps is None
    assert obs.gust_mps is None
    assert obs.pressure_hpa is None
    assert obs.air_temp_c is None
    assert obs.dewpoint_c is None
    assert obs.water_temp_c == 23.4  # the one real value survives


def test_blank_cells_and_garbage_are_none_not_errors():
    text = "#YY MM DD hh mm WDIR WSPD GST\n2026 10 31 07 40 abc  -- 7.5\n"
    obs = parse_stdmet(text, "41010").observations[0]
    assert (obs.wind_dir_deg, obs.wind_speed_mps, obs.gust_mps) == (None, None, 7.5)


def test_rows_with_a_bad_date_are_skipped_and_counted():
    text = "#YY MM DD hh mm WSPD\n2026 10 31 07 40 5.0\n2026 10 32 07 40 5.0\nMM MM MM MM MM 5.0\n"
    series = parse_stdmet(text, "41010")
    assert len(series.observations) == 1
    assert series.skipped == 2


def test_an_html_error_page_is_an_empty_series_with_its_lines_counted():
    series = parse_stdmet("<html>\n<body>\nOops\n</body>\n</html>\n", "41010")
    assert series.observations == ()
    assert series.skipped == 5
    assert not series.reporting


def test_the_station_id_is_normalised_to_upper_case():
    assert parse_stdmet("", "trdf1").station_id == "TRDF1"
