"""With `NO_COLOR` set, every line the self-painting widgets draw must survive Textual's monochrome filter.

The filter reads the style of every segment, so a segment with no style used to crash the whole app (issue 33).
"""

from __future__ import annotations

import pytest
from rich.color import Color
from textual.filter import Monochrome
from textual.widget import Widget

from eyewall.ui.screens.station import StationScreen
from eyewall.ui.widgets.chart_view import ChartView
from eyewall.ui.widgets.gallery import ImageView
from eyewall.ui.widgets.map_view import MapView
from tests.test_ui_graphics import ImageSource, app_for, loaded, open_gallery, pick
from tests.ui_support import into_the_storm, replay_app, running, settle

PAINTERS = (ImageView, ChartView, MapView)


@pytest.fixture(autouse=True)
def _no_colour(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")


def paint_everything(app) -> int:  # type: ignore[no-untyped-def]
    """Draw every line of every self-painting widget on screen, through the monochrome filter; return how many."""
    lines = 0
    for widget in app.screen.walk_children(Widget):
        if isinstance(widget, PAINTERS):
            for y in range(widget.size.height):
                strip = widget.render_line(y)
                assert all(segment.style is not None for segment in strip), (type(widget).__name__, y)
                Monochrome().apply(list(strip), Color.parse("black"))  # type: ignore[arg-type]
                lines += 1
    return lines


async def test_the_dashboard_map_survives_no_colour_and_a_resize() -> None:
    app = replay_app()
    async with running(app, (140, 45)) as pilot:
        await into_the_storm(pilot)
        assert app.no_color
        assert paint_everything(app) > 0
        await pilot.resize_terminal(100, 30)
        await settle(pilot)
        assert paint_everything(app) > 0


async def test_the_gallery_still_and_loop_survive_no_colour_and_a_resize() -> None:
    app = app_for(ImageSource())
    async with running(app) as pilot:
        panel = await open_gallery(pilot)
        await loaded(pilot, panel, "Cone, 5 day")
        assert paint_everything(app) > 0
        for title in ("GEOCOLOR still", "GEOCOLOR loop"):
            await pick(pilot, panel, title)
            await loaded(pilot, panel, title)
            assert paint_everything(app) > 0
            await pilot.resize_terminal(90, 30)
            await settle(pilot)
            assert paint_everything(app) > 0
            await pilot.resize_terminal(140, 45)
            await settle(pilot)


async def test_the_buoy_charts_survive_no_colour_and_a_resize() -> None:
    app = replay_app()
    async with running(app, (140, 45)) as pilot:
        await into_the_storm(pilot)
        app.open_station("ndbc", "41002")
        for _ in range(50):
            await pilot.pause()
            if isinstance(app.screen, StationScreen):
                break
        await settle(pilot)
        assert paint_everything(app) > 0
        await pilot.resize_terminal(100, 30)
        await settle(pilot)
        assert paint_everything(app) > 0
