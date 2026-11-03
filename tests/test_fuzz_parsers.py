"""Property tests for the NDBC and CO-OPS parsers and the NHC helpers test_nhc_robust.py does not reach.

The contract for every parser: a result or ParseError, never another exception; no NaN or infinity in a model; times
are timezone-aware. Example counts come from the hypothesis profile (conftest.py): 60 in a normal run, thousands in the
tag-time fuzz pass. Each call also has a time bound so a quadratic input fails instead of hanging.
"""

from __future__ import annotations

import contextlib
import dataclasses
import gzip
import json
import math
import time
from datetime import UTC, datetime
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from eyewall.coops import data as coops_data
from eyewall.coops.stations import parse_tide_stations
from eyewall.ndbc import historical, latest, spec, stdmet, supl
from eyewall.ndbc.stations import parse_stations
from eyewall.ndbc.table import read_table
from eyewall.providers.base import ParseError
from eyewall.providers.nhc import textutil, times
from tests.nhc_fixtures import FIXTURES

BOUND_SECONDS = 5.0
NDBC = FIXTURES / "ndbc"
COOPS = FIXTURES / "coops"


def assert_clean(value: Any) -> None:
    """Walk a parse result: floats finite, datetimes aware."""
    if isinstance(value, float):
        assert math.isfinite(value), value
    elif isinstance(value, datetime):
        assert value.tzinfo is not None
    elif dataclasses.is_dataclass(value) and not isinstance(value, type):
        for field in dataclasses.fields(value):
            assert_clean(getattr(value, field.name))
    elif isinstance(value, tuple | list):
        for item in value:
            assert_clean(item)
    elif isinstance(value, dict):
        for item in value.values():
            assert_clean(item)


def run(parse: Any, *args: Any) -> None:
    started = time.perf_counter()
    with contextlib.suppress(ParseError):
        assert_clean(parse(*args))
    assert time.perf_counter() - started < BOUND_SECONDS


# ---- NDBC ---------------------------------------------------------------------------------------------------------

NDBC_TABLE_PARSERS = [
    lambda text: stdmet.parse_stdmet(text, "41010"),
    spec.parse_spec,
    supl.parse_supl,
    latest.parse_latest_obs,
    read_table,
]
NDBC_FILES = ["41010_5day.txt", "41010_5day.spec", "41010_5day.supl", "latest_obs.txt"]

# Cells weighted towards what the files really hold: fill values, MM, numbers at the edge of float, junk.
cell = st.one_of(
    st.sampled_from(["MM", "N/A", "99.0", "999", "9999.0", "nan", "inf", "-inf", "1e999", "-0", "0", "1e-320", "2400"]),
    st.integers(-(10**12), 10**12).map(str),
    st.floats().map(repr),
    st.text(max_size=6),
)
HEADER = "#YY  MM DD hh mm WDIR WSPD GST WVHT DPD APD MWD PRES ATMP WTMP DEWP VIS PTDY TIDE"
UNITS = "#yr  mo dy hr mn degT m/s m/s m sec sec deg hPa degC degC degC nmi hPa ft"


@settings()
@given(text=st.text(max_size=800))
def test_ndbc_tables_of_arbitrary_text(text):
    for parse in NDBC_TABLE_PARSERS:
        run(parse, text)


@settings()
@given(rows=st.lists(st.lists(cell, max_size=22), max_size=8), wide=st.booleans())
def test_ndbc_rows_of_hostile_cells(rows, wide):
    body = "\n".join(" ".join(row) for row in rows)
    text = f"{HEADER}\n{UNITS}\n{body}\n"
    if wide:
        text = text.replace("#YY", "#STN LAT LON YYYY", 1)
    for parse in NDBC_TABLE_PARSERS:
        run(parse, text)


@pytest.mark.parametrize("name", NDBC_FILES)
@settings()
@given(data=st.data())
def test_damaged_ndbc_files(name, data):
    original = (NDBC / name).read_text()
    cut = data.draw(st.integers(0, len(original)))
    where = data.draw(st.integers(0, len(original)))
    junk = data.draw(st.text(max_size=12))
    for text in (original[:cut], original[:where] + junk + original[where:]):
        for parse in NDBC_TABLE_PARSERS:
            run(parse, text)


@settings()
@given(body=st.binary(max_size=400), cut=st.integers(0, 400))
def test_historical_bytes(body, cut):
    for blob in (body, b"\x1f\x8b" + body, gzip.compress(body)[:cut]):
        run(historical.parse_historical, blob, "41025")


@settings()
@given(data=st.data())
def test_damaged_historical_gzip(data):
    original = (NDBC / "41025h2025_erin_week.txt.gz").read_bytes()
    position = data.draw(st.integers(0, len(original) - 1))
    damaged = original[:position] + bytes([data.draw(st.integers(0, 255))]) + original[position + 1 :]
    run(historical.parse_historical, damaged, "41025")


@settings()
@given(data=st.one_of(st.text(max_size=500), st.binary(max_size=500)))
def test_ndbc_station_catalog_of_arbitrary_input(data):
    run(parse_stations, data)


@settings()
@given(data=st.data())
def test_damaged_ndbc_station_catalog(data):
    original = (NDBC / "activestations.xml").read_text()
    run(parse_stations, original[: data.draw(st.integers(0, len(original)))])
    value = data.draw(cell)
    attribute = data.draw(st.sampled_from(["lat", "lon", "elev", "id", "met"]))
    run(parse_stations, original.replace(f'{attribute}="', f'{attribute}="{value}', 1))


# ---- CO-OPS -------------------------------------------------------------------------------------------------------

COOPS_PARSERS = [
    coops_data.parse_water_level,
    coops_data.parse_predictions,
    coops_data.parse_air_pressure,
    coops_data.parse_wind,
    parse_tide_stations,
]
json_scalar = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.floats(),  # json.dumps writes NaN and infinity as the bare words Python's json reads back
    st.text(max_size=12),
    st.sampled_from(["NaN", "Infinity", "-Infinity", "1e999", "2026-09-10 12:00", "0000-01-01 00:00"]),
)
json_value = st.recursive(
    json_scalar,
    lambda inner: st.one_of(st.lists(inner, max_size=4), st.dictionaries(st.text(max_size=3), inner)),
    max_leaves=12,
)
KEYS = ("t", "v", "s", "f", "q", "type", "d", "dr", "g", "id", "lat", "lng", "lon", "name")
record = st.fixed_dictionaries({}, optional=dict.fromkeys(KEYS, json_scalar))


@settings()
@given(text=st.one_of(st.text(max_size=300), st.binary(max_size=300)))
def test_coops_arbitrary_input(text):
    for parse in COOPS_PARSERS:
        run(parse, text)


@settings()
@given(rows=st.lists(record, max_size=6), key=st.sampled_from(["data", "predictions", "stations"]), top=json_value)
def test_coops_hostile_json(rows, key, top):
    for payload in ({key: rows}, top, {key: top}):
        text = json.dumps(payload, allow_nan=True)
        for parse in COOPS_PARSERS:
            run(parse, text)


@pytest.mark.parametrize("name", [p.name for p in sorted(COOPS.glob("*.json")) if p.name != "manifest.json"])
@settings()
@given(data=st.data())
def test_damaged_coops_payloads(name, data):
    original = (COOPS / name).read_text()
    cut = data.draw(st.integers(0, len(original)))
    where = data.draw(st.integers(0, len(original)))
    junk = data.draw(st.sampled_from(["NaN", "Infinity", "-Infinity", "1e999", '"', "{", "[", "null"]))
    for text in (original[:cut], original[:where] + junk + original[where:]):
        for parse in COOPS_PARSERS:
            run(parse, text)


@pytest.mark.parametrize("parse", [*COOPS_PARSERS, parse_stations])
def test_deeply_nested_input_is_a_result_or_parse_error(parse):
    for text in ("[" * 200_000, '{"a":' * 200_000, "<a>" * 200_000):
        run(parse, text)


# ---- NHC helpers --------------------------------------------------------------------------------------------------

reference_times = st.datetimes(min_value=datetime(1970, 1, 2), max_value=datetime(2100, 1, 1), timezones=st.just(UTC))


@settings()
@given(text=st.text(max_size=300))
def test_nhc_time_text(text):
    run(times.parse_iso, text)
    run(times.parse_header_time, text)


@settings()
@given(day=st.integers(-5, 40), hour=st.integers(-5, 30), minute=st.integers(-5, 70), reference=reference_times)
def test_resolve_day_time_never_raises(day, hour, minute, reference):
    result = times.resolve_day_time(day, hour, minute, reference)
    assert result is None or result.tzinfo is not None


@settings()
@given(text=st.one_of(st.text(max_size=400), st.binary(max_size=400)))
def test_nhc_textutil(text):
    run(textutil.normalize_newlines, text)
    if isinstance(text, str):
        for helper in (
            textutil.collapse,
            textutil.paragraphs,
            textutil.numbered_items,
            textutil.find_storm_id,
            textutil.find_forecaster,
        ):
            run(helper, text)


# ---- regressions for what the first fuzz runs found ---------------------------------------------------------------


def test_a_flipped_byte_inside_a_gzip_stream_is_a_series_with_a_message():
    original = (NDBC / "41025h2025_erin_week.txt.gz").read_bytes()
    series = historical.parse_historical(original[:10] + b"\x00" + original[11:], "41025")
    assert series.observations == () and series.message


@pytest.mark.parametrize("word", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_non_finite_numbers_read_as_missing(word):
    water = coops_data.parse_water_level(f'{{"data":[{{"t":"2026-09-10 12:00","v":{word}}}]}}')
    assert water.items[0].level_ft is None
    stations = parse_tide_stations(f'{{"stations":[{{"id":"1","lat":{word},"lng":-70}}]}}')
    assert stations.items == () and stations.skipped == 1
    catalog = parse_stations(f'<stations><station id="a" lat="{word}" lon="1"/></stations>')
    assert catalog.items == () and catalog.skipped == 1


def test_an_hour_too_big_for_a_c_int_is_a_row_without_a_date():
    text = f"{HEADER}\n{UNITS}\n2026 09 10 2147483648 00 1 1\n"
    assert stdmet.parse_stdmet(text, "41010").skipped == 1
