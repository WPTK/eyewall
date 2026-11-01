"""Fixes from the redesign UAT: alert order, naming a marked mark, charts that are never squeezed, the feed list in
plain words, one wording for old storm data, the picture gallery's width and NO_COLOR headings."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from textual.widgets import DataTable

from eyewall.models.events import Event, EventKind, Severity
from eyewall.models.watches import WatchWarningArea
from eyewall.net import FetchError, HttpError, RateLimited
from eyewall.palette import WatchWarning
from eyewall.poll import plain_reason
from eyewall.providers.base import ParseError
from eyewall.render.layers import MapScene, StormScene, WarningSegment, WindRadii
from eyewall.ui.screens.station import CHART_ROWS, StationScreen
from eyewall.ui.widgets import warning_list
from eyewall.ui.widgets.chart_view import ChartView
from eyewall.ui.widgets.map_view import MapView
from tests.test_ui_graphics import ImageSource, app_for, loaded, open_gallery
from tests.ui_support import (
    ScriptedSource,
    into_the_storm,
    press,
    replay_app,
    running,
    screen_text,
    scripted_app,
    settle,
)

LINE = ((30.0, -80.0), (30.0, -75.0))
FULL = (100.0, 80.0, 60.0, 90.0)


def event(hour: int, message: str) -> Event:
    moment = datetime(2025, 8, 21, hour, 0, tzinfo=UTC)
    return Event(EventKind.NEW_ADVISORY, message, message, moment, severity=Severity.INFO)


# ---- the alert log is in time order -------------------------------------------------------------------------------


@pytest.mark.parametrize("size", [(80, 24), (120, 30)], ids=lambda s: f"{s[0]}x{s[1]}")
async def test_the_alert_log_is_newest_first_whatever_order_the_events_arrived_in(size) -> None:  # type: ignore[no-untyped-def]
    app = replay_app()
    async with running(app, size) as pilot:
        # The log is kept in arrival order, newest arrival first: a buoy reading from earlier arrived after a later advisory.
        app.alert_log = [event(9, "buoy nine"), event(12, "advisory b"), event(12, "advisory a")]
        await press(pilot, "A")
        table = app.screen.query_one("#alert-table", DataTable)
        assert [str(table.get_row_at(i)[0]) for i in range(table.row_count)] == [
            "Aug 21 12:00",
            "Aug 21 12:00",
            "Aug 21 09:00",
        ]
        assert [str(table.get_row_at(i)[3]) for i in range(2)] == ["advisory b", "advisory a"]  # equal times keep order


# ---- a marked buoy or gauge is named before Enter -----------------------------------------------------------------


async def test_a_marked_station_is_named_in_words_at_80x24() -> None:
    app = replay_app()
    async with running(app, (80, 24)) as pilot:
        await into_the_storm(pilot)
        legend = app.screen.query_one(".legend")
        rows = len(str(legend.render()).splitlines())
        assert "Marked" not in str(legend.render())
        for _ in range(8):
            await press(pilot, "n")
            mark = app.screen.map_view.focused_mark
            if mark is not None and mark.kind == "buoy":
                break
        mark = app.screen.map_view.focused_mark
        assert mark is not None and mark.kind == "buoy"
        assert f"Marked: Buoy {mark.id}" in str(legend.render())
        assert len(str(legend.render()).splitlines()) == rows  # the map does not move when a mark is named
        await press(pilot, "escape")
        assert "Marked" not in str(legend.render())


# ---- the map legend: the sample sits by its label and never wraps -------------------------------------------------


def legend_rows(scene: MapScene, width: int) -> list[str]:
    view = MapView()
    view.scene = scene
    return view.legend(width).plain.split("\n")


def everything() -> MapScene:
    radii = WindRadii(25.0, -70.0, kt34=FULL, kt50=FULL, kt64=FULL)
    kinds = tuple(WatchWarning)
    return MapScene(
        storms=(
            StormScene(
                radii=(radii,),
                warnings=tuple(WarningSegment(k, LINE) for k in kinds[:4]),
                surge=tuple(WarningSegment(k, LINE) for k in kinds[4:]),
            ),
        )
    )


@pytest.mark.parametrize("width", [60, 80, 100, 120, 200])
def test_the_legend_is_two_rows_at_most_and_never_cut_mid_item(width: int) -> None:
    rows = legend_rows(everything(), width)
    assert len(rows) == 2
    assert all(len(row) <= width for row in rows)
    assert not rows[1].rstrip().endswith(("TS", "Hurr", "Surge"))  # a label is whole or the item is absent


def test_each_line_sample_comes_before_its_label() -> None:
    row = legend_rows(everything(), 200)[1]
    assert row.index("┈┈┈") < row.index("34kt") < row.index("╌╌╌", row.index("34kt")) < row.index("50kt")
    assert row.index("╌╌╌") < row.index("TS watch") < row.index("───", row.index("TS watch")) < row.index("TS warning")


def test_what_does_not_fit_is_dropped_whole_from_the_end() -> None:
    wide, narrow = legend_rows(everything(), 200)[1], legend_rows(everything(), 60)[1]
    assert "64kt" in wide and "64kt" not in narrow
    assert wide.startswith(narrow.rstrip())


# ---- station charts keep their height -----------------------------------------------------------------------------


@pytest.mark.parametrize("size", [(80, 24), (100, 40), (120, 30), (200, 50)], ids=lambda s: f"{s[0]}x{s[1]}")
async def test_every_visible_chart_has_at_least_the_least_rows_and_the_rest_are_a_key_away(size) -> None:  # type: ignore[no-untyped-def]
    app = replay_app()
    async with running(app, size) as pilot:
        await into_the_storm(pilot)
        app.open_station("ndbc", "41001")
        await settle(pilot, 6)
        await pilot.pause(0.5)
        screen = app.screen
        assert isinstance(screen, StationScreen)
        shown = [c for c in screen.query(ChartView) if c.display]
        assert shown and all(c.size.height >= CHART_ROWS for c in shown)
        more = screen.query_one("#station-more")
        if len(shown) < 3:
            assert more.display and "More charts: tab" in str(more.render())
            first = [c.id for c in shown]
            await press(pilot, "tab")
            now = [c for c in screen.query(ChartView) if c.display]
            assert [c.id for c in now] != first
            assert all(c.size.height >= CHART_ROWS for c in now)
        else:
            assert not more.display


async def test_the_gauge_legend_is_whole_at_80x24() -> None:
    app = replay_app()
    async with running(app, (80, 24)) as pilot:
        await into_the_storm(pilot)
        app.open_station("coops", "8654467")
        await settle(pilot, 6)
        await pilot.pause(0.5)
        text = screen_text(app)
        assert "observed" in text and "predicted" in text


# ---- the feed list and the main screen say old data in plain words ------------------------------------------------


def test_a_failed_fetch_is_put_in_plain_words() -> None:
    assert plain_reason(FetchError("https://x", "boom")) == "could not reach NOAA"
    assert plain_reason(TimeoutError("slow")) == "could not reach NOAA"
    assert "503" in plain_reason(HttpError("https://x", 503))
    assert "slow down" in plain_reason(RateLimited("https://x", 30))
    assert "could not read" in plain_reason(ParseError("bad"))
    assert plain_reason(KeyError("x")) == "the feed could not be read"


async def test_the_feed_list_in_a_failure_has_no_exception_text_and_no_cut_words() -> None:
    source = ScriptedSource()
    app = scripted_app(source)
    async with running(app, (80, 24)) as pilot:
        source.fail = True
        app.poller.refresh()
        await app.poller.tick()
        await settle(pilot)
        await press(pilot, "D")
        text = screen_text(app)
        assert "FetchError" not in text and "scripted://" not in text and "…" not in text
        assert "could not reach NOAA, retrying in" in text
        assert "satellite" in text and "not polled now" in text
        assert "Esc closes" in text


async def test_old_storm_data_has_one_wording_in_the_lead_and_the_health_slot() -> None:
    source = ScriptedSource()
    app = scripted_app(source)
    async with running(app, (100, 30)) as pilot:
        source.stale = lambda feed: True  # type: ignore[method-assign]
        app.poller.refresh()
        await app.poller.tick()
        await settle(pilot)
        lines = screen_text(app).splitlines()
        assert "offline, cached" in lines[0] and "0s" not in lines[0]
        assert "Storm data unavailable (offline, cached)." in lines[1]
        assert "0s ago" not in "\n".join(lines)


async def test_a_failing_feed_names_no_age_until_there_is_one_worth_saying() -> None:
    source = ScriptedSource()
    app = scripted_app(source)
    async with running(app, (100, 30)) as pilot:
        source.fail = True
        app.poller.refresh()
        await app.poller.tick()
        await settle(pilot)
        lead = screen_text(app).splitlines()[1]
        assert "Storm data unavailable (storms feed failing)." in lead and "ago" not in lead


# ---- the picture gallery uses the whole width when there is one picture -------------------------------------------


async def test_a_single_picture_takes_the_whole_width_and_shows_no_replay_address() -> None:
    app = replay_app()
    async with running(app, (80, 24)) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "g")
        await pilot.pause(0.5)
        screen = app.screen
        assert not screen.query_one("#gal-list").display
        assert screen.query_one("#gal-main").size.width >= 78
        text = screen_text(app)
        assert "replay:" not in text and "H2" not in text and "graphics" not in text.splitlines()[1]
        assert text.count("Cone, 5 day") == 1
        assert "o open" in text  # the keys still work: the panel holds the focus


async def test_with_several_pictures_the_list_stays() -> None:
    app = app_for(ImageSource())
    async with running(app) as pilot:
        panel = await open_gallery(pilot)
        await loaded(pilot, panel, "Cone, 5 day")
        assert panel.query_one("#gal-list").display


# ---- help and settings say how to leave and how to reach the rest -------------------------------------------------


async def test_help_and_settings_say_how_to_leave_and_how_to_reach_the_rest() -> None:
    app = replay_app()
    async with running(app, (80, 24)) as pilot:
        await press(pilot, "?")
        assert "Esc closes" in screen_text(app)
        await press(pilot, "escape", "S")
        text = screen_text(app)
        assert "esc cancels" in text and "tab for more" in text


# ---- NO_COLOR: no heading is weaker than another ------------------------------------------------------------------


async def test_without_colour_a_warning_heading_keeps_the_text_colour_so_none_is_dimmer() -> None:
    app = replay_app()
    async with running(app, (120, 30)) as pilot:
        await into_the_storm(pilot, 20)
        view = app.screen._view()  # type: ignore[attr-defined]
        surge = WatchWarningArea("Storm Surge Warning", WatchWarning.SURGE_WARNING, ("Cape Lookout",))
        warning = WatchWarningArea("Tropical Storm Warning", WatchWarning.TROPICAL_STORM_WARNING, ("Beaufort Inlet",))
        coloured = replace(view, no_color=False)
        plain = replace(view, no_color=True)
        for area in (surge, warning):
            assert warning_list.area_marker(area, coloured)[1].startswith("#")
            assert warning_list.area_marker(area, plain)[1] == ""  # the same bold default text for every kind
