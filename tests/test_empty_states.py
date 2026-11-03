"""A screen with nothing to show says which of three things is true: none listed, still waiting, or the feed failed.

Regression tests for #166 (a blank Pictures screen whose footer advertised keys that do nothing) and #170 (tide gauge
rows that said "Waiting for the first water level" for as long as the CO-OPS feed was failing).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from eyewall.models.obs import TideStation
from eyewall.palette import FRESHNESS_CUES
from eyewall.poll import Freshness, FreshnessState
from eyewall.sources import protocol
from eyewall.state.store import Store
from eyewall.ui import station_view
from eyewall.ui import stations as st
from eyewall.ui.glyphs import ASCII, UNICODE
from eyewall.ui.screens.graphics import GraphicsScreen
from eyewall.ui.widgets import gallery as gallery_widget
from eyewall.ui.widgets.gallery import ImageView
from eyewall.units import PRESETS
from tests.test_ui_graphics import app_for, open_gallery, view_text
from tests.ui_support import press, running, screen_text, settle

NOW = datetime(2025, 8, 20, 21, 0, tzinfo=UTC)
GAUGE = TideStation("8721604", "Trident Pier", 28.4, -80.6)


def gauge_row(feed: Freshness | None, *, ascii_: bool = False) -> station_view.Row:
    store = Store()
    entry = st.Entry(GAUGE)
    glyphs = ASCII if ascii_ else UNICODE
    return station_view.gauge_row(store, entry, NOW, PRESETS["us"], glyphs, ascii_, feed)


def test_a_gauge_waits_only_while_its_feed_is_loading() -> None:
    row = gauge_row(Freshness(FreshnessState.LOADING))
    assert row.state == "waiting"
    assert "Waiting for the first water level" in row.detail


@pytest.mark.parametrize("ascii_", [False, True])
def test_a_gauge_says_the_tide_data_failed_with_the_reason(ascii_: bool) -> None:
    feed = Freshness(FreshnessState.ERROR, failures=3, reason="could not reach NOAA")
    row = gauge_row(feed, ascii_=ascii_)
    cue = FRESHNESS_CUES["error"]
    assert row.state == "failed"
    assert "Waiting" not in row.detail
    assert "Tide data unavailable" in row.detail
    assert "could not reach NOAA" in row.detail
    assert cue.word.capitalize() in row.detail  # a word and a glyph, so NO_COLOR loses nothing
    assert (cue.ascii_glyph if ascii_ else cue.glyph) in row.detail


async def test_an_empty_pictures_screen_explains_itself_and_hides_the_keys_that_do_nothing(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(gallery_widget, "DEBOUNCE_SECONDS", 0)
    monkeypatch.setattr(gallery_widget, "build_items", lambda *_a, **_k: [])
    app = app_for()
    async with running(app, (80, 24)) as pilot:
        panel = await open_gallery(pilot)
        await settle(pilot)
        assert isinstance(app.screen, GraphicsScreen)
        assert panel.items == []
        assert "No pictures are listed" in view_text(panel)
        for action in ("open_url", "copy_url"):
            assert panel.check_action(action, ()) is False
        footer = screen_text(app).splitlines()[-1]
        assert "copy URL" not in footer
        assert "open" not in footer
        await press(pilot, "escape")


async def test_a_pictures_screen_with_pictures_still_offers_open_and_copy() -> None:
    app = app_for()
    async with running(app, (80, 24)) as pilot:
        panel = await open_gallery(pilot)
        assert panel.items
        for action in ("open_url", "copy_url"):
            assert panel.check_action(action, ()) is True


@pytest.mark.parametrize("state", [FreshnessState.FRESH, FreshnessState.STALE])
def test_a_gauge_is_not_waiting_once_the_feed_has_answered(state: FreshnessState) -> None:
    row = gauge_row(Freshness(state, age=10.0))
    assert row.state == "dark"
    assert "Waiting" not in row.detail
    assert "no recent water level" in row.detail


def test_a_failed_row_wears_the_error_cue_and_sorts_with_the_rest() -> None:
    failed = gauge_row(Freshness(FreshnessState.ERROR, reason="could not reach NOAA"))
    text = station_view.row_text(failed, 80, PRESETS["us"])
    assert any(span.style == FRESHNESS_CUES["error"].style() for span in text.spans)
    ok = station_view.Row(
        kind=station_view.BUOY, id="1", name="A", distance_nm=5.0, bearing_deg=0.0, wind_kt=20.0,
        followed=True, state="ok", detail="x", age="",
    )  # fmt: skip
    for mode in station_view.SORTS:
        assert {r.id for r in station_view.sort_rows([failed, ok], mode)} == {failed.id, "1"}


# ---- the pictures screen ---------------------------------------------------------------------------------------


def feeds_as(monkeypatch, app, **states: Freshness) -> None:  # type: ignore[no-untyped-def]
    """Report these feeds (by protocol name) as they are given; every other feed is fresh."""
    fresh = Freshness(FreshnessState.FRESH, age=1.0)
    monkeypatch.setattr(app.poller, "freshness", lambda feed: states.get(feed, fresh))


@pytest.fixture
def listing(monkeypatch):  # type: ignore[no-untyped-def]
    """`build_items` as it is, unless `.empty` is set."""
    real = gallery_widget.build_items

    class Switch:
        empty = True

    switch = Switch()
    monkeypatch.setattr(gallery_widget, "DEBOUNCE_SECONDS", 0)
    monkeypatch.setattr(gallery_widget, "build_items", lambda *a, **k: [] if switch.empty else real(*a, **k))
    return switch


async def test_the_empty_message_follows_both_feeds_and_the_keys_follow_the_list(monkeypatch, listing) -> None:  # type: ignore[no-untyped-def]
    app = app_for()
    async with running(app, (80, 24)) as pilot:
        panel = await open_gallery(pilot)
        panel.query_one("#gal-list").focus()
        for feed, state, words in (
            (protocol.STORMS, FreshnessState.ERROR, "Failing: Pictures unavailable, could not reach NOAA"),
            (protocol.SATELLITE, FreshnessState.ERROR, "Failing: Pictures unavailable, could not reach NOAA"),
            (protocol.SATELLITE, FreshnessState.LOADING, "Waiting for the first list of pictures"),
            (protocol.STORMS, FreshnessState.FRESH, "No pictures are listed"),
        ):
            feeds_as(monkeypatch, app, **{feed: Freshness(state, reason="could not reach NOAA")})
            panel.refresh_data()
            assert words in " ".join(view_text(panel).split()), (feed, state)
            assert panel.check_action("open_url", ()) is False
        listing.empty = False  # the pictures arrive
        feeds_as(monkeypatch, app)
        panel.focus()
        panel.refresh_data()
        assert len(panel.items) > 1
        assert panel.check_action("open_url", ()) is True
        assert panel.query_one("#gal-list").has_focus  # the list came back, so did the keys
        listing.empty = True  # and go again
        panel.refresh_data()
        assert panel.check_action("copy_url", ()) is False
        assert "No pictures are listed" in " ".join(view_text(panel).split())


async def test_a_message_wraps_to_a_narrow_view_and_never_covers_a_picture(listing) -> None:  # type: ignore[no-untyped-def]
    app = app_for()
    async with running(app, (80, 24)) as pilot:
        panel = await open_gallery(pilot)
        view = panel.query_one(ImageView)
        await pilot.resize_terminal(30, 16)
        await settle(pilot)
        assert view._lines
        assert all(line.cell_length <= max(view.size.width, 12) for line in view._lines)
        assert "pictures" in " ".join(view_text(panel).split()).lower()
        view._is_picture = True  # a picture is on screen; the old message must not be drawn over it
        view._lines = []
        view.on_resize(None)  # type: ignore[arg-type]
        assert view._lines == []


async def test_the_stations_list_and_page_say_the_tide_feed_failed(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    app = app_for()
    async with running(app, (100, 40)) as pilot:
        await settle(pilot)
        feeds_as(monkeypatch, app, **{protocol.TIDES: Freshness(FreshnessState.ERROR, reason="could not reach NOAA")})
        app.open_station("coops", "8721604")
        await settle(pilot)
        text = " ".join(screen_text(app).split())
        assert "Tide data unavailable, could not reach NOAA" in text
        assert "Waiting for the first water level" not in text
