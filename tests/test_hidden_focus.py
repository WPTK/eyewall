"""Focus never rests on a widget the user cannot see: arrows and paging would go nowhere and no focus would show."""

from __future__ import annotations

from dataclasses import replace

from textual.widget import Widget

from eyewall.config import Config, WatchlistConfig
from eyewall.ui.screens.buoys import BuoysScreen
from eyewall.ui.screens.station import StationScreen
from tests.ui_support import press, replay_app, running, settle


def is_visible(widget: Widget | None) -> bool:
    """Displayed, with every ancestor displayed too."""
    return widget is not None and all(w.display for w in (widget, *widget.ancestors_with_self))


async def test_an_empty_buoys_screen_does_not_focus_its_hidden_list() -> None:
    app = replay_app(replace(Config(), watchlist=WatchlistConfig(ndbc=(), coops=())))
    async with running(app, (100, 40)) as pilot:
        await app.push_screen(BuoysScreen(None))
        await settle(pilot)
        assert not app.screen.query_one("#buoys-list").display  # nothing followed: the list is hidden
        assert app.focused is None or is_visible(app.focused)


async def test_the_station_charts_view_does_not_focus_the_hidden_readings() -> None:
    app = replay_app()
    async with running(app, (100, 40)) as pilot:
        await app.push_screen(StationScreen("ndbc", "41002"))
        await settle(pilot)
        assert app.focused is None or is_visible(app.focused)
        await press(pilot, "r")  # the readings table is shown now and takes focus
        assert app.focused is not None and app.focused.id == "station-readings"
        await press(pilot, "r")
        assert app.focused is None or is_visible(app.focused)
