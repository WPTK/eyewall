import re

import pytest
from hypothesis import given
from hypothesis import strategies as st

from eyewall import palette
from eyewall.models.events import Severity
from eyewall.palette import (
    CATEGORY_COLORS,
    CATEGORY_CUES,
    DASHED,
    DOTTED,
    FORECAST_DASH,
    FRESHNESS_CUES,
    NEUTRAL,
    PATTERN_SAMPLES,
    PRESSURE_TREND_CUES,
    RING_KNOTS,
    RING_PATTERNS,
    RISK_CUES,
    SEVERITY_CUES,
    SOLID,
    SPARSE,
    TIDE_DIFFERENCE_CUES,
    WATCH_WARNING_COLORS,
    WATCH_WARNING_CUES,
    Category,
    Cue,
    WatchWarning,
    category_color,
    category_for_knots,
    risk_color,
    storm_force,
)
from eyewall.poll import FreshnessState

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


def test_one_wind_scale_is_neutral_below_34_knots_and_the_saffir_simpson_colors_above():
    assert category_color(None) == category_color(33.9) == category_color(0) == NEUTRAL
    assert not storm_force(33.9) and storm_force(34) and not storm_force(None)
    for knots, category in ((34, Category.TS), (63.9, Category.TS), (64, Category.H1), (140, Category.H5)):
        assert category_color(knots) == CATEGORY_COLORS[category]
    assert not hasattr(palette, "wind_band_color")


def test_every_state_has_a_cue_with_a_word():
    tables = [CATEGORY_CUES, WATCH_WARNING_CUES, RISK_CUES, FRESHNESS_CUES, SEVERITY_CUES, PRESSURE_TREND_CUES]
    for table in tables:
        for cue in table.values():
            assert cue.word and cue.short and HEX.match(cue.color), cue
    assert set(CATEGORY_CUES) == set(Category)
    assert set(WATCH_WARNING_CUES) == set(WatchWarning)
    assert set(FRESHNESS_CUES) == {state.value for state in FreshnessState}
    assert set(SEVERITY_CUES) == {severity.value for severity in Severity}
    assert all(HEX.match(cue.color) and cue.word for _, cue in TIDE_DIFFERENCE_CUES)


def test_freshness_cues_have_distinct_glyphs_in_both_sets():
    unicode_glyphs = [cue.glyph for cue in FRESHNESS_CUES.values()]
    ascii_glyphs = [cue.ascii_glyph for cue in FRESHNESS_CUES.values()]
    assert len(set(unicode_glyphs)) == len(set(ascii_glyphs)) == len(FRESHNESS_CUES)


def test_rings_and_watch_warning_lines_have_distinct_patterns():
    assert len({RING_PATTERNS[kt] for kt in RING_KNOTS}) == len(RING_KNOTS)
    warning = WATCH_WARNING_CUES[WatchWarning.HURRICANE_WARNING].pattern
    watch = WATCH_WARNING_CUES[WatchWarning.HURRICANE_WATCH].pattern
    surge = WATCH_WARNING_CUES[WatchWarning.SURGE_WARNING].pattern
    assert warning is SOLID and watch == DASHED and surge == DOTTED
    assert WATCH_WARNING_CUES[WatchWarning.SURGE_WATCH].pattern == SPARSE != surge
    assert FORECAST_DASH not in (RING_PATTERNS[50], DASHED)  # the forecast track is not mistaken for a 50 kt ring
    assert WATCH_WARNING_CUES[WatchWarning.TROPICAL_STORM_WATCH].pattern == watch
    assert set(PATTERN_SAMPLES) == {SOLID, DASHED, DOTTED, SPARSE}


def test_cue_style_puts_emphasis_before_the_color():
    assert Cue("#112233", "w", "s", emphasis="bold").style() == "bold #112233"
    assert Cue("#112233", "w", "s").style() == "#112233"
