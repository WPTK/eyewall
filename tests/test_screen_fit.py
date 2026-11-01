"""The graphics view, the Storm screen, the station charts and the buoy's supplemental file fit their area."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from rich.cells import cell_len

from eyewall.models.obs import Parsed, SupplementalReading
from eyewall.net import FetchError
from eyewall.ui.chrome import FooterBar
from eyewall.ui.screens.station import StationScreen
from eyewall.ui.screens.storm import StormScreen
from eyewall.ui.widgets.chart_view import ChartView
from eyewall.ui.widgets.gallery import GalleryPanel, ImageView
from tests.ui_support import into_the_storm, press, replay_app, running, screen_text, settle, wait_until

SIZES = [(80, 24), (120, 30), (100, 50), (200, 50), (280, 70)]
IDS = [f"{w}x{h}" for w, h in SIZES]


async def open_station(pilot) -> StationScreen:  # type: ignore[no-untyped-def]
    await into_the_storm(pilot)
    await press(pilot, "enter", "b", "enter")
    screen = pilot.app.screen
    assert isinstance(screen, StationScreen)
    await settle(pilot)
    return screen


@pytest.mark.parametrize("size", SIZES, ids=IDS)
async def test_the_storm_screen_fits_and_keeps_its_lines_whole(size) -> None:
    async with running(replay_app(), size) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "enter")
        assert isinstance(pilot.app.screen, StormScreen)
        text = screen_text(pilot.app)
        assert max(cell_len(line) for line in text.splitlines()) <= size[0]
        assert "Next advisory" in text or "Next full advisory" in text or "advisory" in text


async def open_graphics(pilot) -> StormScreen:  # type: ignore[no-untyped-def]
    await into_the_storm(pilot)
    await press(pilot, "enter", "g")
    return pilot.app.screen


@pytest.mark.parametrize("size", SIZES, ids=IDS)
async def test_graphics_picture_stays_above_the_footer(size) -> None:
    async with running(replay_app(), size) as pilot:
        screen = await open_graphics(pilot)
        panel = screen.query_one(GalleryPanel)
        view = screen.query_one("#gal-view", ImageView)
        await wait_until(pilot, lambda: view._is_picture)
        status = screen.query_one(FooterBar)
        assert view.region.bottom < status.region.y, "the picture area touches the footer"
        assert panel.region.bottom <= status.region.y
        assert view.region.width >= 20


@pytest.mark.parametrize("size", [(120, 40), (100, 50), (200, 50)], ids=["120x40", "100x50", "200x50"])
async def test_buoy_charts_share_one_plot_edge(size) -> None:
    async with running(replay_app(), size) as pilot:
        screen = await open_station(pilot)
        charts = [c for c in screen.query(ChartView) if c.display]
        assert len(charts) == 3
        assert len({c.min_gutter for c in charts}) == 1
        assert charts[0].min_gutter == max(c.natural_gutter for c in charts)
        edges = set()
        lines = screen_text(pilot.app).splitlines()
        for chart in charts:
            region = chart.region
            rows = [lines[y][region.x : region.right] for y in range(region.y, region.bottom)]
            axis = next(row for row in reversed(rows) if "─" in row or "━" in row)
            edges.add(min(axis.index(c) for c in "─━" if c in axis))
        assert len(edges) == 1, f"the plots start in different columns: {edges}"


async def test_buoy_wave_chart_has_data_and_the_page_has_a_lead() -> None:
    async with running(replay_app(), (120, 30)) as pilot:
        screen = await open_station(pilot)
        assert screen.query_one("#chart-wave", ChartView)._has_data()
        assert screen.query_one("#station-lead").region.height >= 1


async def test_station_gets_new_supplemental_data_once_the_apps_copy_expires() -> None:
    app = replay_app()
    first = Parsed((SupplementalReading(datetime(2025, 8, 20, 1, tzinfo=UTC), peak_wind_mps=10.0),))
    second = Parsed((SupplementalReading(datetime(2025, 8, 20, 2, tzinfo=UTC), peak_wind_mps=20.0),))
    answers = [first, second]
    calls: list[str] = []

    async def fake(station_id: str) -> Parsed[SupplementalReading]:
        calls.append(station_id)
        return answers[len(calls) - 1]

    app.source.ndbc_supplemental = fake  # type: ignore[method-assign]
    async with running(app, (120, 30)) as pilot:
        screen = await open_station(pilot)
        await wait_until(pilot, lambda: screen.supl is first)
        screen.refresh_data()  # a poll result right away: the app still holds the file
        await settle(pilot)
        assert len(calls) == 1 and screen.supl is first
        for station_id, (asked, kept) in list(app._supl.items()):
            app._supl[station_id] = (asked - 601.0, kept)  # SUPL_TTL has passed
        screen.refresh_data()
        await wait_until(pilot, lambda: screen.supl is second)
        assert len(calls) == 2


async def test_a_failed_refresh_keeps_the_earlier_supplemental_file() -> None:
    app = replay_app()
    first = Parsed((SupplementalReading(datetime(2025, 8, 20, 1, tzinfo=UTC), peak_wind_mps=10.0),))
    results: list[object] = [first, FetchError("x", "down")]

    async def fake(station_id: str) -> Parsed[SupplementalReading]:
        result = results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result  # type: ignore[return-value]

    app.source.ndbc_supplemental = fake  # type: ignore[method-assign]
    async with running(app, (120, 30)) as pilot:
        screen = await open_station(pilot)
        await wait_until(pilot, lambda: screen.supl is first)
        for station_id, (asked, kept) in list(app._supl.items()):
            app._supl[station_id] = (asked - 601.0, kept)
        screen.refresh_data()
        await wait_until(pilot, lambda: not results)
        await settle(pilot)
        assert screen.supl is first  # the failed refresh keeps the earlier file
