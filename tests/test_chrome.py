"""The chrome's layout functions: breadcrumb, health slot and footer, with no terminal."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from rich.cells import cell_len

from eyewall.poll import Freshness, FreshnessState
from eyewall.sources import protocol
from eyewall.ui.chrome import (
    FeedStatus,
    FooterItem,
    ReplayStatus,
    fit_crumbs,
    footer_row,
    health,
    short_age,
    top_bar,
)
from eyewall.ui.glyphs import ASCII, UNICODE

FRESH = Freshness(FreshnessState.FRESH, age=180.0, stale_after=900.0)


def feeds(**states: Freshness) -> list[FeedStatus]:
    return [FeedStatus(feed, states.get(feed, FRESH)) for feed in (protocol.STORMS, protocol.OUTLOOK)]


# ---- health -----------------------------------------------------------------------------------------------------


def test_health_says_ok_with_the_storms_feed_age() -> None:
    slot = health(feeds(), None, UNICODE)
    assert slot.text().plain == "● data ok 3m"
    assert slot.text(short=True).plain == "● ok 3m"


def test_every_health_state_has_a_glyph_and_a_word() -> None:
    late = Freshness(FreshnessState.STALE, age=5000.0, stale_after=900.0)
    failing = Freshness(FreshnessState.ERROR, age=7000.0, failures=3)
    cached = Freshness(FreshnessState.STALE, age=7000.0, from_cache=True)
    loading = Freshness(FreshnessState.LOADING)
    cases = {
        "◐ 2 feeds late 1h": health(feeds(storms=late, outlook=late), None, UNICODE),
        "✕ 1 feed failing 1h": health(feeds(outlook=failing, storms=late), None, UNICODE),
        "✕ offline, cached": health(feeds(storms=cached), None, UNICODE),
        "○ checking": health(feeds(storms=loading), None, UNICODE),
    }
    for expected, slot in cases.items():
        assert slot.text().plain == expected
        assert slot.glyph and slot.word  # never colour alone


def test_health_in_ascii_uses_ascii_glyphs() -> None:
    assert health(feeds(), None, ASCII).text().plain == "* data ok 3m"


def test_health_for_a_replay_names_the_speed_and_state() -> None:
    moment = datetime(2025, 8, 20, 6, tzinfo=UTC)
    assert health(feeds(), ReplayStatus(False, 300, moment, "38"), UNICODE).text().plain == "▶ replay 300x"
    assert health(feeds(), ReplayStatus(True, 300, moment, "38"), UNICODE).text().plain == "⏸ replay paused"
    assert health(feeds(), ReplayStatus(True, 300, moment, "38", over=True), UNICODE).text().plain == "⏸ replay over"


def test_a_feed_that_is_not_polled_does_not_make_the_data_late() -> None:
    late = Freshness(FreshnessState.STALE, age=5000.0)
    items = [FeedStatus(protocol.STORMS, FRESH), FeedStatus(protocol.ALERTS, late, active=False)]
    assert health(items, None, UNICODE).text().plain == "● data ok 3m"


@pytest.mark.parametrize(("seconds", "text"), [(None, ""), (4, "4s"), (180, "3m"), (7500, "2h")])
def test_short_age(seconds: float | None, text: str) -> None:
    assert short_age(seconds) == text


# ---- breadcrumb -------------------------------------------------------------------------------------------------


def test_the_breadcrumb_shortens_the_middle_first_and_keeps_the_last() -> None:
    labels = ["Home", "Erin", "Buoy 41047", "Pictures"]
    assert [t for t, _ in fit_crumbs(labels, 80)] == labels
    assert [t for t, _ in fit_crumbs(labels, 30)] == ["Home", "…", "Pictures"]
    assert [t for t, _ in fit_crumbs(labels, 14)] == ["…", "Pictures"]
    cut = fit_crumbs(labels, 6)
    assert len(cut) == 1 and cut[0][0].endswith("…") and cut[0][1] == 3


def test_an_ellipsis_crumb_goes_back_one_step() -> None:
    assert fit_crumbs(["Home", "Erin", "Buoy 41047", "Pictures"], 30)[1] == ("…", 2)


# ---- the top bar ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("width", [60, 80, 120, 200])
def test_the_top_bar_always_ends_with_the_whole_health_slot(width: int) -> None:
    slot = health(feeds(), None, UNICODE)
    row = top_bar(["Home", "Erin", "Buoy 41047", "Advisory text"], slot, [("2 alerts", "app:alerts")], width, UNICODE)
    assert row.text.cell_len == width
    assert row.text.plain.rstrip().endswith(slot.text(width < 80).plain)


def test_the_top_bar_makes_the_earlier_crumbs_and_the_slot_clickable() -> None:
    slot = health(feeds(), None, UNICODE)
    row = top_bar(["Home", "Erin", "Pictures"], slot, [], 120, UNICODE)
    actions = [t.action for t in row.targets]
    assert actions == ["app:crumb(0)", "app:crumb(1)", "app:feeds"]
    home = row.targets[0]
    assert row.text.plain[home.start : home.end] == "Home"
    assert row.target_at(home.start) is home and row.target_at(home.end) is None


def test_extras_are_dropped_before_the_breadcrumb_is_shortened() -> None:
    slot = health(feeds(), None, UNICODE)
    crumbs = ["Home", "Erin", "Pictures"]
    wide = top_bar(crumbs, slot, [("3 alerts", "app:alerts")], 100, UNICODE)
    assert "3 alerts" in wide.text.plain and "app:alerts" in [t.action for t in wide.targets]
    tight = top_bar(crumbs, slot, [("3 alerts", "app:alerts")], 36, UNICODE)
    assert "alerts" not in tight.text.plain and "Home › Erin › Pictures" in tight.text.plain


# ---- the footer -------------------------------------------------------------------------------------------------

PINNED = [FooterItem("?", "help", "app:help"), FooterItem("^p", "menu", "app:command_palette")]
BACK = FooterItem("esc", "back", "app:back")
ITEMS = [FooterItem("enter", "detail", "key:enter"), FooterItem("b", "buoys", "key:b"), FooterItem("m", "map", "key:m")]


def test_the_footer_pins_help_menu_and_back_on_the_right() -> None:
    row = footer_row(ITEMS, [*PINNED, BACK], 80)
    assert row.text.cell_len == 80
    assert row.text.plain.rstrip().endswith("? help  ^p menu  esc back")
    assert row.text.plain.startswith(" enter detail  b buoys  m map")


MANY = [
    *ITEMS,
    FooterItem("l", "layers", "key:l"),
    FooterItem("c", "center", "key:c"),
    FooterItem("f", "fit", "key:f"),
    FooterItem("t", "tcp/tcm", "key:t"),
    FooterItem("p", "pin", "key:p"),
]


def test_keys_are_dropped_whole_from_the_right_and_the_pinned_group_stays() -> None:
    kept = []
    for width in range(110, 69, -1):
        plain = footer_row(MANY, [*PINNED, BACK], width).text.plain
        assert plain.rstrip().endswith("? help  ^p menu  esc back"), (width, plain)
        left = plain.split("? help")[0].strip()
        shown = [part for part in left.split("  ") if part]
        assert shown == [f"{i.key} {i.label}" for i in MANY][: len(shown)], (width, plain)  # a whole prefix
        kept.append(len(shown))
    assert kept[0] == len(MANY) and kept[-1] < len(MANY) and kept == sorted(kept, reverse=True)


def test_under_70_columns_the_pinned_group_is_keys_only() -> None:
    row = footer_row(ITEMS, [*PINNED, BACK], 65)
    assert row.text.plain.rstrip().endswith("? ^p esc")
    assert row.text.cell_len == 65


def test_a_footer_key_is_clickable_across_its_whole_width() -> None:
    row = footer_row(ITEMS, [*PINNED, BACK], 80)
    target = next(t for t in row.targets if t.action == "key:b")
    assert row.text.plain[target.start : target.end] == "b buoys"
    assert {t.action for t in row.targets} == {
        "key:enter",
        "key:b",
        "key:m",
        "app:help",
        "app:command_palette",
        "app:back",
    }


def test_a_wide_character_does_not_break_the_width() -> None:
    row = footer_row([FooterItem("w", "台風台風台風", "key:w")], [*PINNED, BACK], 40)
    assert row.text.cell_len == 40 or cell_len(row.text.plain) == 40
