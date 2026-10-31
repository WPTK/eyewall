import re

import pytest
from hypothesis import given
from hypothesis import strategies as st

from eyewall.palette import (
    CATEGORY_COLORS,
    NEUTRAL,
    WATCH_WARNING_COLORS,
    Category,
    WatchWarning,
    category_color,
    category_for_knots,
    risk_color,
    wind_band_color,
)

HEX = re.compile(r"^#[0-9a-f]{6}$")


@pytest.mark.parametrize(
    ("wind", "expected"),
    [
        (0, Category.TD),
        (33.9, Category.TD),
        (34, Category.TS),
        (63.9, Category.TS),
        (64, Category.H1),
        (82.9, Category.H1),
        (83, Category.H2),
        (95.9, Category.H2),
        (96, Category.H3),
        (112.9, Category.H3),
        (113, Category.H4),
        (136.9, Category.H4),
        (137, Category.H5),
        (190, Category.H5),
    ],
)
def test_saffir_simpson_boundaries(wind, expected):
    assert category_for_knots(wind) is expected


def test_unknown_or_invalid_wind_has_no_category():
    assert category_for_knots(None) is None
    assert category_for_knots(-1) is None
    assert category_color(None) == NEUTRAL


@given(st.floats(min_value=0, max_value=250), st.floats(min_value=0, max_value=250))
def test_category_never_decreases_with_wind(a, b):
    order = list(Category)
    low, high = sorted((a, b))
    assert order.index(category_for_knots(low)) <= order.index(category_for_knots(high))


def test_every_category_and_watch_has_a_distinct_hex_color():
    assert set(CATEGORY_COLORS) == set(Category)
    assert set(WATCH_WARNING_COLORS) == set(WatchWarning)
    for colors in (CATEGORY_COLORS, WATCH_WARNING_COLORS):
        assert all(HEX.match(c) for c in colors.values())
        assert len(set(colors.values())) == len(colors)


def test_tcww_codes_match_nhc():
    assert {w.value for w in WatchWarning} >= {"TWA", "TWR", "HWA", "HWR"}


def test_risk_color():
    assert risk_color("High") == risk_color(" high ")
    assert risk_color("Low") != risk_color("High")
    assert risk_color(None) == NEUTRAL
    assert risk_color("mystery") == NEUTRAL


def test_wind_bands_follow_nhc_thresholds():
    assert wind_band_color(None) is None
    assert wind_band_color(33.9) is None
    colors = [wind_band_color(w) for w in (34, 49.9, 50, 63.9, 64, 120)]
    assert colors[0] == colors[1] != colors[2] == colors[3] != colors[4] == colors[5]
    assert all(c is not None and HEX.match(c) for c in colors)
