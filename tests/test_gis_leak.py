"""Parsing a GIS zip must not leave its pyshp Reader, or the shapefile bytes, reachable (issue 197)."""

from __future__ import annotations

import gc
import tracemalloc
from pathlib import Path

import shapefile

from eyewall.providers.nhc import gis

FIXTURES = Path(__file__).parent / "fixtures" / "gis"
PARSERS = (
    ("erin_5day_030.zip", gis.parse_forecast_zip),
    ("erin_fcst_030.zip", gis.parse_radii_zip),
    ("erin_best_track.zip", gis.parse_best_track_zip),
)


def _parse_all(rounds: int) -> None:
    blobs = [((FIXTURES / name).read_bytes(), parse) for name, parse in PARSERS]
    for _ in range(rounds):
        for data, parse in blobs:
            parse(data)


def _live_readers() -> int:
    gc.collect()
    return sum(isinstance(obj, shapefile.Reader | shapefile.ShpReader) for obj in gc.get_objects())


def test_parsed_zips_leave_no_pyshp_reader_alive() -> None:
    _parse_all(1)
    before = _live_readers()
    _parse_all(5)
    assert _live_readers() == before


def test_heap_is_flat_across_many_parses() -> None:
    _parse_all(5)
    gc.collect()
    tracemalloc.start()
    try:
        base = tracemalloc.get_traced_memory()[0]
        _parse_all(30)
        gc.collect()
        growth = tracemalloc.get_traced_memory()[0] - base
    finally:
        tracemalloc.stop()
    # Unfixed, 90 parses retain well over 10 MB; the fixed path holds the one blob list and nothing else.
    assert growth < 1_000_000
