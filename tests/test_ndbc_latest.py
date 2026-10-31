from datetime import UTC, datetime
from pathlib import Path

import pytest

from eyewall.models.obs import LatestObservation
from eyewall.ndbc.latest import parse_latest_obs

FIXTURES = Path(__file__).parent / "fixtures" / "ndbc"


@pytest.fixture(scope="module")
def latest() -> dict[str, LatestObservation]:
    parsed = parse_latest_obs((FIXTURES / "latest_obs.txt").read_text(encoding="utf-8"))
    assert parsed.skipped == 0
    assert parsed.message is None
    return {row.station_id: row for row in parsed.items}


def test_every_row_of_the_recorded_file_parses(latest):
    assert len(latest) == 19


def test_a_full_buoy_row_is_read_by_column_name(latest):
    row = latest["41010"]
    assert (row.lat, row.lon) == (28.86, -78.478)
    obs = row.observation
    assert obs.time == datetime(2026, 10, 31, 7, 50, tzinfo=UTC)
    assert (obs.wind_dir_deg, obs.wind_speed_mps, obs.gust_mps) == (60, 8.0, 9.0)
    assert (obs.wave_height_m, obs.dominant_period_s, obs.average_period_s, obs.mean_wave_dir_deg) == (1.9, 9, 5.9, 64)
    assert (obs.pressure_hpa, obs.air_temp_c, obs.water_temp_c, obs.dewpoint_c) == (1018.4, 26.1, 27.5, 22.3)
    assert obs.pressure_tendency_hpa is None  # MM: PTDY is only filled on the hour
    assert obs.visibility_nmi is None
    assert obs.tide_ft is None


def test_mm_becomes_none_for_each_measurement(latest):
    wave_only = latest["41065"].observation  # a wave buoy: no wind, pressure or temperatures
    assert wave_only.wave_height_m == 0.7
    assert wave_only.wind_dir_deg is None
    assert wave_only.wind_speed_mps is None
    assert wave_only.gust_mps is None
    assert wave_only.pressure_hpa is None
    assert wave_only.air_temp_c is None
    assert latest["51WH0"].observation.pressure_hpa is None  # Hawaii: wind and temperatures only
    assert latest["SSBN7"].observation.wind_dir_deg is None
    assert latest["SSBN7"].observation.water_temp_c == 20.0  # the only temperature this wave buoy reports
    assert latest["SSBN7"].observation.air_temp_c is None


def test_pressure_tendency_keeps_its_sign_on_the_hour(latest):
    assert latest["41082"].observation.pressure_tendency_hpa == 1.3
    assert latest["44137"].observation.pressure_tendency_hpa == 0.4
    assert latest["41082"].observation.time.minute == 0


def test_waves_are_mostly_missing_in_this_file(latest):
    waves = [r for r in latest.values() if r.observation.wave_height_m is not None]
    assert 0 < len(waves) < len(latest)
    assert latest["TRDF1"].observation.wave_height_m is None


def test_cman_ids_are_upper_case(latest):
    assert {"TRDF1", "AAMC1", "SSBN7"} <= latest.keys()
    assert all(station_id == station_id.upper() for station_id in latest)


def test_a_zero_period_is_kept_as_reported(latest):
    assert latest["22101"].observation.dominant_period_s == 0.0


def test_new_and_missing_columns_are_tolerated():
    text = (
        "#STN LAT LON YYYY MM DD hh mm NEWCOL WSPD\n"
        "#text deg deg yr mo day hr mn x m/s\n"
        "abc12 10.5 -20.25 2026 10 31 07 00 7 5.5\n"
        "xyz99 11 -21 2026 10 31 07 10 MM\n"
    )
    parsed = parse_latest_obs(text)
    first, second = parsed.items
    assert first.station_id == "ABC12"
    assert first.observation.wind_speed_mps == 5.5
    assert first.observation.pressure_hpa is None
    assert second.observation.wind_speed_mps is None  # the row ended early


def test_rows_without_a_station_or_a_date_are_skipped_and_counted():
    text = (
        "#STN LAT LON YYYY MM DD hh mm WSPD\n"
        "41010 28.8 -78.4 2026 10 31 07 00 5.5\n"
        "41011 28.8 -78.4 2026 13 31 07 00 5.5\n"
        "41012 28.8 -78.4 MM MM MM MM MM 5.5\n"
    )
    parsed = parse_latest_obs(text)
    assert [r.station_id for r in parsed.items] == ["41010"]
    assert parsed.skipped == 2


def test_something_that_is_not_a_table_says_so():
    parsed = parse_latest_obs("<html>Service Unavailable</html>\n")
    assert parsed.items == ()
    assert parsed.message == "not an NDBC observation table"
    assert parsed.skipped == 1
