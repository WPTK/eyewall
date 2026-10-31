"""Loaders for the saved NOAA payloads under tests/fixtures. Shared by the test_nhc_* modules."""

from __future__ import annotations

from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
NHC = FIXTURES / "nhc"
GIS = FIXTURES / "gis"


def nhc_bytes(relative: str) -> bytes:
    """A fixture under tests/fixtures/nhc, byte for byte."""
    return (NHC / relative).read_bytes()


def nhc_text(relative: str) -> str:
    return nhc_bytes(relative).decode("utf-8")


def gis_bytes(name: str) -> bytes:
    """A zip under tests/fixtures/gis."""
    return (GIS / name).read_bytes()
