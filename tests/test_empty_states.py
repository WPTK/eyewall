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
from eyewall.state.store import Store
from eyewall.ui import station_view
from eyewall.ui import stations as st
from eyewall.ui.glyphs import ASCII, UNICODE
from eyewall.ui.screens.graphics import GraphicsScreen
from eyewall.ui.widgets import gallery as gallery_widget
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
    feed = Freshness(FreshnessState.ERROR, age=125.0, failures=3, reason="could not reach NOAA")
    row = gauge_row(feed, ascii_=ascii_)
    cue = FRESHNESS_CUES["error"]
    assert row.state == "failed"
    assert "Waiting" not in row.detail
    assert "Tide data unavailable" in row.detail
    assert "could not reach NOAA" in row.detail
    assert "2m05s ago" in row.detail
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
