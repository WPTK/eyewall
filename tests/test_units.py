import pytest
from hypothesis import given
from hypothesis import strategies as st

from eyewall.units import PRESETS, UnitError, convert, dimension, format_value, next_preset

SCALE = ["kt", "mph", "kmh", "mps"]


def test_known_wind_conversions():
    assert convert(100, "kt", "mph") == pytest.approx(115.078, abs=0.001)
    assert convert(10, "mps", "kt") == pytest.approx(19.438, abs=0.001)
    assert convert(100, "kmh", "mph") == pytest.approx(62.137, abs=0.001)


def test_known_other_conversions():
    assert convert(1013.25, "hpa", "inhg") == pytest.approx(29.92, abs=0.01)
    assert convert(1, "nm", "km") == pytest.approx(1.852)
    assert convert(100, "mi", "nm") == pytest.approx(86.898, abs=0.001)
    assert convert(10, "m", "ft") == pytest.approx(32.808, abs=0.001)
    assert convert(100, "f", "c") == pytest.approx(37.778, abs=0.001)
    assert convert(0, "c", "f") == 32


def test_mb_and_hpa_are_the_same_pressure():
    assert convert(1004.5, "mb", "hpa") == 1004.5


def test_mixed_dimensions_and_unknown_units_are_rejected():
    with pytest.raises(UnitError):
        convert(1, "kt", "nm")
    with pytest.raises(UnitError):
        dimension("furlong")


@given(st.floats(min_value=-1e6, max_value=1e6), st.sampled_from(SCALE), st.sampled_from(SCALE))
def test_wind_round_trip(value, a, b):
    assert convert(convert(value, a, b), b, a) == pytest.approx(value, rel=1e-9, abs=1e-9)


@given(st.floats(min_value=-200, max_value=500))
def test_temperature_round_trip(value):
    assert convert(convert(value, "c", "f"), "f", "c") == pytest.approx(value, abs=1e-9)


def test_format_value():
    assert format_value(100, "kt") == "100 kt"
    assert format_value(29.9213, "inhg") == "29.92 inHg"
    assert format_value(None, "kt") == "--"
    assert format_value(5.44, "nm") == "5.4 nm"
    assert format_value(54.4, "nm") == "54 nm"
    assert format_value(-0.04, "c") == "0.0 °C"
    assert format_value(12.345, "m", label=False) == "12.3"


def test_presets_format_from_a_source_unit():
    nautical, us, metric = PRESETS["nautical"], PRESETS["us"], PRESETS["metric"]
    assert nautical.fmt_wind(100) == "100 kt"
    assert us.fmt_wind(100) == "115 mph"
    assert metric.fmt_wind(100) == "185 km/h"
    assert us.fmt_pressure(1013.25, "mb") == "29.92 inHg"
    assert metric.fmt_distance(100, "nm") == "185 km"
    assert nautical.fmt_wind(None) == "--"
    assert metric.fmt_wind(10, "mps") == "36 km/h"


def test_next_preset_cycles():
    assert next_preset("nautical") == "us"
    assert next_preset("us") == "metric"
    assert next_preset("metric") == "nautical"
    assert next_preset("bogus") == "nautical"
