"""The map's marks with a real mouse and with the keyboard alone: click, near-miss click, overlap chooser, drag, hover,
n/N/Enter/Esc, at three terminal sizes. Everything runs over the Erin replay, 14 advisories in."""

from __future__ import annotations

import pytest
from textual.pilot import Pilot

from eyewall.render.hits import Mark
from eyewall.ui.screens.buoy_detail import BuoyDetailScreen
from eyewall.ui.screens.dashboard import DashboardScreen
from eyewall.ui.screens.detail import StormDetailScreen
from eyewall.ui.widgets.map_view import MapView, MarkChooser
from tests.ui_support import into_the_storm, press, replay_app, running, settle

SIZES = [(80, 24), (120, 30), (200, 50)]
STORM = Mark("storm", "al052025")


async def map_of(pilot: Pilot[None]) -> MapView:
    """The dashboard map, shown (at 80 columns the map is behind the m key)."""
    await into_the_storm(pilot)
    view = pilot.app.screen.query_one(MapView)
    if view.size.width < 1:
        await press(pilot, "m")
    assert view.size.width > 10 and view.hits.drawn
    return view


def alone(view: MapView, kind: str) -> tuple[Mark, tuple[int, int]]:
    """A mark of this kind that no other mark is within a cell of, and its cell."""
    for mark, cell in view.hits.drawn:
        if mark.kind == kind and view.hits.at(*cell) == (mark,):
            return mark, cell
    raise AssertionError(f"no lone {kind} on the map")


def empty_cell(view: MapView, away_from: tuple[int, int] | None = None) -> tuple[int, int]:
    for r in range(view.size.height):
        for c in range(view.size.width):
            if not view.hits.at(c, r) and (away_from is None or max(abs(c - away_from[0]), abs(r - away_from[1])) >= 2):
                return c, r
    raise AssertionError("no empty cell")


def crowded_cell(view: MapView) -> tuple[int, int]:
    """A cell where a click finds several marks: they share it, or sit equally close beside it."""
    for r in range(view.size.height):
        for c in range(view.size.width):
            if len(view.hits.at(c, r)) > 1:
                return c, r
    raise AssertionError("no overlapping marks")


async def back(pilot: Pilot[None]) -> None:
    await press(pilot, "escape")
    assert isinstance(pilot.app.screen, DashboardScreen)


@pytest.mark.parametrize("size", SIZES)
async def test_clicking_a_buoy_opens_its_page(size: tuple[int, int]) -> None:
    async with running(replay_app(), size) as pilot:
        view = await map_of(pilot)
        mark, (col, row) = alone(view, "buoy")
        await pilot.click(MapView, offset=(col, row))
        await settle(pilot)
        screen = pilot.app.screen
        assert isinstance(screen, BuoyDetailScreen) and screen.station_id == mark.id.upper()


@pytest.mark.parametrize("size", SIZES)
async def test_clicking_a_storm_opens_its_detail(size: tuple[int, int]) -> None:
    async with running(replay_app(), size) as pilot:
        view = await map_of(pilot)
        col, row = view.hits.cell_of(STORM) or (-1, -1)
        await pilot.click(MapView, offset=(col, row))
        await settle(pilot)
        assert isinstance(pilot.app.screen, StormDetailScreen)


@pytest.mark.parametrize("size", SIZES)
async def test_a_click_one_cell_from_a_small_mark_still_hits_it(size: tuple[int, int]) -> None:
    async with running(replay_app(), size) as pilot:
        view = await map_of(pilot)
        mark, (col, row) = alone(view, "buoy")
        beside = next(
            (col + dc, row + dr)
            for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1))
            if 0 <= col + dc < view.size.width
            and 0 <= row + dr < view.size.height
            and view.hits.at(col + dc, row + dr) == (mark,)
        )
        await pilot.click(MapView, offset=beside)
        await settle(pilot)
        assert isinstance(pilot.app.screen, BuoyDetailScreen)


@pytest.mark.parametrize("size", SIZES)
async def test_a_click_two_cells_from_any_mark_only_moves_the_cursor(size: tuple[int, int]) -> None:
    async with running(replay_app(), size) as pilot:
        view = await map_of(pilot)
        await pilot.click(MapView, offset=empty_cell(view))
        await settle(pilot)
        assert isinstance(pilot.app.screen, DashboardScreen) and view.cursor is not None


@pytest.mark.parametrize("size", SIZES)
async def test_a_click_on_overlapping_marks_asks_which(size: tuple[int, int]) -> None:
    async with running(replay_app(), size) as pilot:
        view = await map_of(pilot)
        cell = crowded_cell(view)
        marks = view.hits.at(*cell)
        await pilot.click(MapView, offset=cell)
        await settle(pilot)
        chooser = pilot.app.screen
        assert isinstance(chooser, MarkChooser)
        assert [m for m, _ in chooser.marks] == list(marks)
        await press(pilot, "down", "enter")  # the second one
        second = marks[1]
        screen = pilot.app.screen
        if second.kind == "buoy":
            assert isinstance(screen, BuoyDetailScreen) and screen.station_id == second.id.upper()
        else:
            assert isinstance(screen, DashboardScreen)  # a gauge is pinned; it has no page yet


async def test_escape_leaves_the_chooser_without_opening_anything() -> None:
    async with running(replay_app(), (120, 30)) as pilot:
        view = await map_of(pilot)
        await pilot.click(MapView, offset=crowded_cell(view))
        await settle(pilot)
        assert isinstance(pilot.app.screen, MarkChooser)
        await press(pilot, "escape")
        assert isinstance(pilot.app.screen, DashboardScreen)
        assert view.focused_mark is None


async def test_clicking_a_gauge_says_what_it_reads_and_changes_nothing() -> None:
    async with running(replay_app(), (200, 50)) as pilot:
        view = await map_of(pilot)
        mark, cell = alone(view, "gauge")
        before = pilot.app.config  # type: ignore[attr-defined]
        shown = len(pilot.app._notifications)
        await pilot.click(MapView, offset=cell)
        await settle(pilot)
        await pilot.pause(0.3)
        notes = list(pilot.app._notifications)[shown:]
        assert len(notes) == 1 and f"Gauge {mark.id}" in notes[0].message
        assert pilot.app.config is before  # type: ignore[attr-defined]  # nothing was pinned
        assert isinstance(pilot.app.screen, DashboardScreen)


async def test_a_drag_that_ends_without_a_click_does_not_swallow_the_next_click() -> None:
    async with running(replay_app(), (120, 30)) as pilot:
        view = await map_of(pilot)
        mark, (col, row) = alone(view, "buoy")
        await pilot.mouse_down(MapView, offset=(col, row))
        await pilot.hover(MapView, offset=(col + 3, row + 2))
        await pilot.mouse_up(MapView, offset=(col + 3, row + 2))
        await settle(pilot)
        view._dragged = True  # as if the release had produced no Click event
        _, (col, row) = alone(view, "buoy")
        await pilot.click(MapView, offset=(col, row))
        await settle(pilot)
        assert isinstance(pilot.app.screen, BuoyDetailScreen)


async def test_a_map_with_no_room_has_no_marks_and_clicks_nothing() -> None:
    async with running(replay_app(), (80, 24)) as pilot:
        await into_the_storm(pilot)
        view = pilot.app.screen.query_one(MapView)
        assert view.size.width < 1
        assert view.hits.drawn == () and view.hits.order == ()
        view.action_mark(1)
        view.action_open_mark()
        assert view.focused_mark is None and isinstance(pilot.app.screen, DashboardScreen)


@pytest.mark.parametrize("size", SIZES)
async def test_dragging_pans_the_map_and_is_not_a_click(size: tuple[int, int]) -> None:
    async with running(replay_app(), size) as pilot:
        view = await map_of(pilot)
        mark, (col, row) = alone(view, "buoy")
        before = view.viewport
        assert before is not None
        await pilot.mouse_down(MapView, offset=(col, row))
        await pilot.hover(MapView, offset=(col + 3, row + 2))
        await pilot.mouse_up(MapView, offset=(col + 3, row + 2))
        await settle(pilot)
        after = view.viewport
        assert after is not None and not view.auto_fit
        assert after.center_lon < before.center_lon  # pulled east, so the view moved west
        assert after.center_lat > before.center_lat  # pulled south, so the view moved north
        assert isinstance(pilot.app.screen, DashboardScreen)  # releasing the button opened nothing
        moved = view.hits.cell_of(mark)  # the mark followed the pointer, give or take a dot of rounding
        assert moved is not None and max(abs(moved[0] - col - 3), abs(moved[1] - row - 2)) <= 1


@pytest.mark.parametrize("size", SIZES)
async def test_hovering_a_mark_names_it(size: tuple[int, int]) -> None:
    async with running(replay_app(), size) as pilot:
        view = await map_of(pilot)
        mark, cell = alone(view, "buoy")
        await pilot.hover(MapView, offset=cell)
        await settle(pilot)
        assert view.tooltip is not None and f"Buoy {mark.id}" in str(view.tooltip)
        await pilot.hover(MapView, offset=view.hits.cell_of(STORM))
        await settle(pilot)
        assert "Storm Erin" in str(view.tooltip) and "kt" in str(view.tooltip)
        await pilot.hover(MapView, offset=empty_cell(view))
        await settle(pilot)
        assert view.tooltip is None


@pytest.mark.parametrize("size", SIZES)
async def test_n_and_enter_reach_the_same_screens_as_a_click(size: tuple[int, int]) -> None:
    async with running(replay_app(), size) as pilot:
        view = await map_of(pilot)
        order = view.hits.order
        assert order[0] == STORM
        await press(pilot, "n")
        assert view.focused_mark == STORM and pilot.app.focused is view
        await press(pilot, "enter")
        assert isinstance(pilot.app.screen, StormDetailScreen)
        await back(pilot)
        await press(pilot, "n")  # the next one after the storm
        assert view.focused_mark == order[1]
        await press(pilot, "N")
        assert view.focused_mark == STORM
        await press(pilot, "N")  # wraps to the last
        assert view.focused_mark == order[-1]


async def test_every_buoy_in_the_keyboard_order_opens_by_enter() -> None:
    async with running(replay_app(), (120, 30)) as pilot:
        view = await map_of(pilot)
        buoys = [m for m in view.hits.order if m.kind == "buoy"]
        assert len(buoys) >= 3
        for mark in buoys[:3]:
            while view.focused_mark != mark:
                await press(pilot, "n")
            await press(pilot, "enter")
            screen = pilot.app.screen
            assert isinstance(screen, BuoyDetailScreen) and screen.station_id == mark.id.upper()
            await back(pilot)


def reversed_columns(view: MapView) -> list[tuple[int, int]]:
    """The cells drawn in reverse video, as (column, row)."""
    out = []
    for row in range(view.size.height):
        col = 0
        for seg in view.render_line(row):
            if seg.style is not None and seg.style.reverse:
                out.extend((col + i, row) for i in range(len(seg.text)))
            col += len(seg.text)
    return out


async def test_the_focused_mark_is_drawn_in_reverse_video_and_escape_clears_it() -> None:
    async with running(replay_app(), (120, 30)) as pilot:
        view = await map_of(pilot)
        assert reversed_columns(view) == []
        await press(pilot, "n")
        assert reversed_columns(view) == [view.hits.cell_of(STORM)]
        await press(pilot, "escape")
        assert view.focused_mark is None and reversed_columns(view) == []


async def test_enter_still_belongs_to_the_screen_while_no_mark_is_focused() -> None:
    async with running(replay_app(), (120, 30)) as pilot:
        view = await map_of(pilot)
        view.focus()
        await settle(pilot)
        await press(pilot, "enter")  # the dashboard's own enter: the selected storm's detail
        assert isinstance(pilot.app.screen, StormDetailScreen)


async def test_the_mark_ring_survives_the_scene_being_redrawn() -> None:
    async with running(replay_app(), (120, 30)) as pilot:
        view = await map_of(pilot)
        await press(pilot, "n", "n")
        mark = view.focused_mark
        assert mark is not None and mark.kind != "storm"
        pilot.app.screen.refresh_data()  # type: ignore[attr-defined]
        await settle(pilot)
        assert view.focused_mark == mark
