"""The detail tabs, buoy tables, graphics view and buoy charts fit their area at every terminal size."""

from __future__ import annotations

import asyncio

import pytest
from rich.cells import cell_len
from rich.text import Text
from textual.widgets import DataTable, Tabs

from eyewall.ui.screens.buoy_detail import BuoyDetailScreen
from eyewall.ui.screens.detail import StormDetailScreen
from eyewall.ui.widgets.chart_view import ChartView
from eyewall.ui.widgets.gallery import GalleryPanel, ImageView
from tests.ui_support import into_the_storm, press, replay_app, running, screen_text, settle, wait_until

SIZES = [(80, 24), (120, 30), (100, 50), (200, 50), (280, 70)]
ROOMY = [s for s in SIZES if s[0] >= 100]  # the buoy table's twelve columns need about 100 columns
IDS = [f"{w}x{h}" for w, h in SIZES]


async def open_tab(pilot, key: str) -> StormDetailScreen:  # type: ignore[no-untyped-def]
    await into_the_storm(pilot)
    await press(pilot, "enter", key)
    assert isinstance(pilot.app.screen, StormDetailScreen)
    return pilot.app.screen


@pytest.mark.parametrize("size", ROOMY, ids=[f"{w}x{h}" for w, h in ROOMY])
async def test_buoys_table_shows_every_column_in_full(size) -> None:
    async with running(replay_app(), size) as pilot:
        screen = await open_tab(pilot, "7")
        table = screen.query_one("#buoys-table", DataTable)
        assert not table.show_horizontal_scrollbar, f"the buoys table scrolls sideways at {size}"
        text = screen_text(pilot.app)
        for needle in ("Closest", "76 nm 1h", "245 nm now"):
            assert needle in text, (needle, text)
        assert max(cell_len(line) for line in text.splitlines()) <= size[0]


async def test_buoys_name_column_gives_way_to_the_numbers_and_takes_spare_room() -> None:
    names = {}
    for size in [(100, 50), (280, 70)]:
        async with running(replay_app(), size) as pilot:
            await open_tab(pilot, "7")
            row = screen_text(pilot.app).splitlines()
            names[size] = next(line for line in row if "41002" in line)
    assert "…" in names[(100, 50)]
    assert "SOUTH HATTERAS - 225 NM South of Cape Hatteras" in names[(280, 70)]


@pytest.mark.parametrize("size", SIZES, ids=IDS)
async def test_summary_labels_and_values_are_two_columns(size) -> None:
    async with running(replay_app(), size) as pilot:
        await open_tab(pilot, "1")
        lines = screen_text(pilot.app).splitlines()
        at = next(i for i, line in enumerate(lines) if "Next advisory" in line)
        assert "Next advisory  Next" in lines[at], lines[at]
        value_column = lines[at].index("Next advisory  ") + len("Next advisory  ")
        # a wrapped value lines up under the value, never under its label
        if lines[at + 1].strip() and "Forecaster" not in lines[at + 1]:
            assert lines[at + 1][:value_column].strip() == "", lines[at + 1]
        for label in ("Advisory", "Updated", "Position", "Max wind", "Pressure", "Movement", "Forecaster"):
            row = next(ln for ln in lines if ln.lstrip().startswith(label))
            assert row.index(label) + 0 == 1 and row[value_column - 2 : value_column].strip() == "", row
            assert row[value_column] != " ", row  # every value starts in the same column


@pytest.mark.parametrize("size", SIZES, ids=IDS)
async def test_selected_tab_has_one_style_focused_or_not(size) -> None:
    async with running(replay_app(), size) as pilot:
        screen = await open_tab(pilot, "7")
        tabs = screen.query_one(Tabs)
        styles = []
        for focused in (False, True):
            if focused:
                tabs.focus()
            else:
                screen.query_one("#buoys-table").focus()
            await settle(pilot)
            active = tabs.query(".-active").first()
            style = active.rich_style
            assert style.bold and style.underline, f"selected tab lacks bold and underline (focused={focused})"
            styles.append((style.color, style.bgcolor, style.bold, style.underline))
        assert styles[0] == styles[1]


@pytest.mark.parametrize("size", SIZES, ids=IDS)
async def test_graphics_picture_stays_above_the_footer(size) -> None:
    async with running(replay_app(), size) as pilot:
        screen = await open_tab(pilot, "9")
        panel = screen.query_one(GalleryPanel)
        view = screen.query_one("#gal-view", ImageView)
        await wait_until(pilot, lambda: view._is_picture)
        status = screen.query_one("#detail-status")
        assert view.region.bottom < status.region.y, "the picture area touches the footer"
        assert panel.region.bottom <= status.region.y
        assert view.region.width >= 20


@pytest.mark.parametrize("size", [(120, 30), (100, 50), (60, 16)], ids=["120x30", "100x50", "60x16"])
async def test_buoy_charts_share_one_plot_edge(size) -> None:
    async with running(replay_app(), size) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "b", "enter")
        screen = pilot.app.screen
        assert isinstance(screen, BuoyDetailScreen)
        await settle(pilot)
        charts = list(screen.query(ChartView))
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


async def test_buoy_panel_wave_height_agrees_with_the_wave_chart() -> None:
    async with running(replay_app(), (120, 30)) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "b", "enter")
        screen = pilot.app.screen
        assert isinstance(screen, BuoyDetailScreen)
        wave_chart = screen.query_one("#chart-wave", ChartView)
        assert wave_chart._has_data()
        line = next(
            ln for ln in screen_text(pilot.app).splitlines() if "Wave height" in ln and "ft" in ln and "(" in ln
        )
        assert " ago)" in line, line  # the newest row has no wave; the last reading is shown with its age
        assert "supplemental file." in screen_text(pilot.app) and "The recording has no" in screen_text(pilot.app)


@pytest.mark.parametrize("size", [(120, 30), (80, 24)], ids=["120x30", "80x24"])
async def test_search_result_is_one_row(size) -> None:
    async with running(replay_app(), size) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "slash", "4", "1", "0", "0", "2")
        lines = screen_text(pilot.app).splitlines()
        at = next(i for i, ln in enumerate(lines) if "41002" in ln and "buoy" in ln)
        assert "NDBC" not in lines[at + 1] and "buoy" not in lines[at + 1], lines[at : at + 2]


@pytest.mark.parametrize(
    "size", [(60, 10), (100, 50), (120, 30), (120, 12)], ids=["60x10", "100x50", "120x30", "120x12"]
)
async def test_station_table_with_more_rows_than_height_still_fits(size) -> None:
    from textual.app import App

    from eyewall.ui.stations import BUOY_COLUMNS
    from eyewall.ui.widgets.station_table import StationTable

    cells = (
        "41000",
        "A fairly long buoy name for testing the fit",
        "10 nm",
        "N",
        "5 kt",
        "6 kt",
        "1000 mb",
        "--",
        "--",
        "80 F",
        "0s",
        "10 nm 1h",
    )
    rows = [(str(i), tuple(Text(c) for c in cells)) for i in range(70)]

    class Host(App[None]):
        def compose(self):
            yield StationTable(id="t")

    async with Host().run_test(size=size) as pilot:
        table = pilot.app.query_one("#t", StationTable)
        table.set_rows(BUOY_COLUMNS, rows)
        await settle(pilot)
        assert table.show_vertical_scrollbar
        if size[0] >= 100:
            assert not table.show_horizontal_scrollbar, f"{table.size} {table.virtual_size}"


async def test_buoy_detail_asks_for_the_supplemental_file_again_once_it_expires() -> None:
    async with running(replay_app(), (120, 30)) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "b", "enter")
        screen = pilot.app.screen
        assert isinstance(screen, BuoyDetailScreen)
        asked: list[float] = []
        screen._load_supplemental = lambda: asked.append(screen._supl_asked) or asyncio.sleep(0)  # type: ignore[method-assign]
        screen.refresh_data()  # a poll result right away: the app still holds the file
        assert asked == []
        screen._supl_asked -= 601.0  # SUPL_TTL has passed
        screen.refresh_data()
        assert len(asked) == 1
