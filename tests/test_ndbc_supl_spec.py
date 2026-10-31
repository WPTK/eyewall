from datetime import UTC, datetime
from pathlib import Path

import pytest

from eyewall.models.obs import SupplementalReading, WaveSummary
from eyewall.ndbc.spec import parse_spec
from eyewall.ndbc.supl import parse_supl

FIXTURES = Path(__file__).parent / "fixtures" / "ndbc"


def at(day: int, hour: int, minute: int, month: int = 10) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=UTC)


@pytest.fixture(scope="module")
def supl() -> tuple[SupplementalReading, ...]:
    parsed = parse_supl((FIXTURES / "41010_5day.supl").read_text(encoding="utf-8"))
    assert parsed.skipped == 0
    assert parsed.message is None
    return parsed.items


@pytest.fixture(scope="module")
def spec() -> tuple[WaveSummary, ...]:
    parsed = parse_spec((FIXTURES / "41010_5day.spec").read_text(encoding="utf-8"))
    assert parsed.skipped == 0
    assert parsed.message is None
    return parsed.items


def test_supl_has_a_row_per_regular_row_newest_first(supl):
    assert len(supl) == 704
    assert [r.time for r in supl] == sorted((r.time for r in supl), reverse=True)


def test_supl_row_has_the_interval_extremes_and_their_times(supl):
    assert supl[0] == SupplementalReading(
        time=at(31, 7, 40),
        min_pressure_hpa=1018.4,
        min_pressure_time=at(31, 7, 38),
        peak_wind_mps=9.0,
        peak_wind_dir_deg=60.0,
        peak_wind_time=at(31, 7, 38),
    )


def test_supl_clock_times_that_cross_midnight_belong_to_the_previous_day(supl):
    row = next(r for r in supl if r.time == at(31, 0, 0))
    assert row.min_pressure_hpa == 1017.8
    assert row.min_pressure_time == at(30, 23, 58)
    assert row.peak_wind_time == at(30, 23, 54)


def test_supl_clock_times_are_never_after_their_row_or_more_than_an_interval_before_it(supl):
    for row in supl:
        for moment in (row.min_pressure_time, row.peak_wind_time):
            assert moment is not None
            assert 0 <= (row.time - moment).total_seconds() <= 600


def test_the_lowest_pressure_in_five_days_is_found_by_its_own_time(supl):
    lowest = min((r for r in supl if r.min_pressure_hpa is not None), key=lambda r: r.min_pressure_hpa or 0)
    assert (lowest.min_pressure_hpa, lowest.min_pressure_time) == (1013.7, at(29, 7, 54))


def test_supl_tolerates_missing_values_and_bad_clock_times():
    text = (
        "#YY  MM DD hh mm   PRES PTIME  WSPD  WDIR WTIME\n"
        "#yr  mo dy hr mn    hPa  hhmm   m/s  degT  hhmm\n"
        "2026 10 31 07 40 1018.4  0738     9    60  0738\n"
        "2026 10 31 07 30     MM    MM    MM    MM    MM\n"
        "2026 10 31 07 20 1018.5  2575     9    60   738\n"
        "2026 10 31 07 10 1018.5\n"
        "MM MM MM MM MM 1018.5 0707 9 60 0702\n"
    )
    parsed = parse_supl(text)
    assert parsed.skipped == 1
    blank, bad_clock, short = parsed.items[1], parsed.items[2], parsed.items[3]
    assert (blank.min_pressure_hpa, blank.min_pressure_time, blank.peak_wind_mps) == (None, None, None)
    assert (bad_clock.min_pressure_hpa, bad_clock.min_pressure_time, bad_clock.peak_wind_time) == (1018.5, None, None)
    assert (short.min_pressure_hpa, short.peak_wind_mps) == (1018.5, None)


def test_spec_row_reads_swell_and_wind_wave_parts_with_compass_text(spec):
    assert len(spec) == 225
    assert spec[0] == WaveSummary(
        time=at(31, 7, 10),
        wave_height_m=1.9,
        swell_height_m=1.1,
        swell_period_s=9.1,
        wind_wave_height_m=1.6,
        wind_wave_period_s=6.7,
        swell_direction="ENE",
        wind_wave_direction="ENE",
        steepness="STEEP",
        average_period_s=5.8,
        mean_wave_dir_deg=75.0,
    )


def test_spec_words_are_kept_as_noaa_prints_them(spec):
    assert {r.steepness for r in spec} == {"STEEP", "AVERAGE", "VERY_STEEP"}
    assert {"ENE", "ESE", "E", "N", "NE", "SSE"} <= {r.swell_direction for r in spec}


def test_spec_missing_values_are_none():
    text = (
        "#YY  MM DD hh mm WVHT  SwH  SwP  WWH  WWP SwD WWD  STEEPNESS  APD MWD\n"
        "#yr  mo dy hr mn    m    m  sec    m  sec  -  degT     -      sec degT\n"
        "2026 10 30 16 10  2.8  0.0   MM  2.8  9.1  MM ENE    AVERAGE  6.6  58\n"
        "2026 10 30 16 40  2.8   MM   MM   MM   MM  MM  MM        N/A   MM  MM\n"
    )
    newer, older = parse_spec(text).items  # sorted newest first whatever the file order
    assert newer.time > older.time
    assert (older.swell_height_m, older.swell_period_s, older.swell_direction) == (0.0, None, None)
    assert (older.wind_wave_height_m, older.wind_wave_direction) == (2.8, "ENE")
    assert (newer.wave_height_m, newer.steepness, newer.average_period_s) == (2.8, None, None)
    assert (newer.swell_height_m, newer.wind_wave_period_s, newer.mean_wave_dir_deg) == (None, None, None)


def test_something_that_is_not_a_table_says_so():
    assert parse_supl("<html></html>").message == "not an NDBC supplemental table"
    assert parse_spec("<html></html>").message == "not an NDBC wave table"
