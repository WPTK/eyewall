"""Damaged versions of real payloads must parse or raise ParseError, never anything else."""

from __future__ import annotations

import contextlib
import gzip
import json

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from eyewall.providers.base import ParseError
from eyewall.providers.nhc import alerts, atcf, gis, graphics, two
from eyewall.providers.nhc.current import parse_current_storms
from eyewall.providers.nhc.tcm import parse_tcm
from eyewall.providers.nhc.text import parse_pws, parse_tcd, parse_tcp, parse_two
from tests.nhc_fixtures import gis_bytes, nhc_bytes, nhc_text

SETTINGS = settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])

TEXT_CASES = [
    (parse_tcm, "tcm/erin_030.txt"),
    (parse_tcm, "tcm/nolo_057.txt"),
    (parse_tcm, "tcm/ptc08_001.txt"),
    (parse_tcp, "tcp/erin_030.txt"),
    (parse_tcp, "tcp/nolo_057.txt"),
    (parse_tcd, "tcd/erin_030.txt"),
    (parse_tcd, "tcd/fay_039.txt"),
    (parse_pws, "pws/erin_030.txt"),
    (parse_two, "two/ep_20260910.txt"),
    (atcf.parse_bdeck, "atcf/bal052025.dat.gz"),
    (atcf.parse_btk_index, "atcf/btk_index.html"),
]


def _damage(text: str, data: st.DataObject) -> str:
    lines = text.splitlines(keepends=True)
    mode = data.draw(st.sampled_from(["drop_lines", "truncate", "shuffle_chars", "blank_line"]))
    if mode == "drop_lines" and lines:
        start = data.draw(st.integers(0, len(lines) - 1))
        stop = data.draw(st.integers(start, len(lines)))
        return "".join(lines[:start] + lines[stop:])
    if mode == "truncate":
        return text[: data.draw(st.integers(0, len(text)))]
    if mode == "blank_line" and lines:
        index = data.draw(st.integers(0, len(lines) - 1))
        lines[index] = "\n"
        return "".join(lines)
    position = data.draw(st.integers(0, max(len(text) - 1, 0)))
    junk = data.draw(st.text(min_size=1, max_size=20))
    return text[:position] + junk + text[position:]


@pytest.mark.parametrize(("parse", "path"), TEXT_CASES)
@SETTINGS
@given(data=st.data())
def test_damaged_text_products_parse_or_raise_parse_error(parse, path, data):
    raw = nhc_bytes(path)
    if path.endswith(".gz"):
        import gzip

        original = gzip.decompress(raw).decode()
    else:
        original = raw.decode()
    damaged = _damage(original, data)
    with contextlib.suppress(ParseError):
        parse(damaged)


@SETTINGS
@given(data=st.data())
def test_damaged_current_storms_json_never_crashes(data):
    text = nhc_text("current/populated.json")
    document = json.loads(text)
    storm = document["activeStorms"][data.draw(st.integers(0, 3))]
    key = data.draw(st.sampled_from(sorted(storm)))
    replacement = data.draw(
        st.one_of(
            st.none(), st.integers(), st.floats(allow_nan=False), st.text(max_size=12), st.lists(st.none(), max_size=2)
        )
    )
    storm[key] = replacement
    result = parse_current_storms(json.dumps(document))
    assert len(result.storms) + result.skipped == 4


@SETTINGS
@given(data=st.data())
def test_damaged_alerts_json_never_crashes(data):
    document = json.loads(nhc_text("api/alerts_populated.json"))
    feature = document["features"][data.draw(st.integers(0, 2))]
    section = data.draw(st.sampled_from(["properties", "geometry"]))
    target = feature.get(section)
    if isinstance(target, dict) and target:
        key = data.draw(st.sampled_from(sorted(target)))
        target[key] = data.draw(
            st.one_of(st.none(), st.integers(), st.text(max_size=8), st.lists(st.integers(), max_size=3))
        )
    else:
        feature[section] = data.draw(st.one_of(st.none(), st.integers(), st.text(max_size=8)))
    alerts.parse_alerts(json.dumps(document))


ZIP_CASES = [
    (gis.parse_forecast_zip, "erin_5day_030.zip"),
    (gis.parse_radii_zip, "erin_fcst_030.zip"),
    (two.parse_gtwo_zip, "gtwo_20250919.zip"),
]


@pytest.mark.parametrize(("parse", "name"), ZIP_CASES)
@SETTINGS
@given(data=st.data())
def test_truncated_or_corrupted_zips_parse_or_raise_parse_error(parse, name, data):
    original = gis_bytes(name)
    if data.draw(st.booleans()):
        damaged = original[: data.draw(st.integers(0, len(original)))]
    else:
        position = data.draw(st.integers(0, len(original) - 1))
        damaged = original[:position] + bytes([data.draw(st.integers(0, 255))]) + original[position + 1 :]
    with contextlib.suppress(ParseError):
        parse(damaged)


@SETTINGS
@given(page=st.text(max_size=400))
def test_graphics_pages_of_any_text_do_not_crash(page):
    graphics.parse_graphics_page(page, "https://www.nhc.noaa.gov/graphics_at1.shtml")
    graphics.parse_floater_storms(page)
    graphics.parse_floater_products(page)
    graphics.parse_floater_listing(page, "al052025", "GEOCOLOR")


@SETTINGS
@given(body=st.binary(max_size=300), cut=st.integers(0, 300))
def test_gzip_looking_bytes_are_a_parse_error_or_a_result(body, cut):
    for data in (b"\x1f\x8b" + body, gzip.compress(body)[:cut]):
        with contextlib.suppress(ParseError):
            atcf.parse_bdeck(data)


@SETTINGS
@given(text=st.text(max_size=600))
def test_arbitrary_text_is_a_parse_error_or_a_result(text):
    for parse in (parse_tcm, parse_tcp, parse_tcd, parse_pws, parse_two, atcf.parse_bdeck):
        with contextlib.suppress(ParseError):
            parse(text)


# ---- values that are numbers or dates but cannot be used --------------------------------------------------------


def test_a_listing_row_with_an_impossible_date_keeps_the_file_and_loses_only_the_date():
    html = '<a href="bal912026.dat">x</a> 2026-13-45 06:00 1K\n<a href="bal902026.dat">x</a> 2026-08-01 06:00 1K\n'
    files = atcf.parse_btk_index(html)
    assert [f.storm_id for f in files] == ["al912026", "al902026"]
    assert files[0].modified is None and files[1].modified is not None


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_a_dbf_value_that_is_not_a_finite_number_reads_as_missing(value):
    assert gis._number(value) is None
    assert gis._int(value) is None
    assert gis._ymdh(value) is None


@pytest.mark.parametrize("text", ["9999-12-31T23:59:59-05:00", "0001-01-01T00:00:00+05:00"])
def test_an_iso_time_that_overflows_utc_reads_as_missing(text):
    from eyewall.providers.nhc.times import parse_iso

    assert parse_iso(text) is None


def test_a_header_time_that_overflows_utc_reads_as_missing():
    from eyewall.providers.nhc.times import parse_header_time

    assert parse_header_time("1100 PM EDT Dec 31 9999") is None
