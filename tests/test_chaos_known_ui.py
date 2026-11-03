"""Defects the chaos run found, pinned until their fixes merge (audit #183).

Each test is a strict xfail: it fails today and is the failing test of its issue. When the fix merges the test passes,
strict mode reports that as a failure, and the mark is deleted in the fix's PR.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from textual.widgets import DataTable

from eyewall.models.events import Event, EventKind
from eyewall.ui.screens.main import MainScreen
from tests.chaos_support import MutableSource
from tests.state_support import T0
from tests.test_chaos_ui import shown
from tests.ui_support import running, scripted_app, settle


@pytest.mark.xfail(strict=True, reason="#179: a second TooSmallScreen is pushed and dismissed twice", raises=Exception)
async def test_help_opened_under_the_too_small_notice_survives_enlarging() -> None:
    app = scripted_app(MutableSource())
    async with running(app, (120, 40)) as pilot:
        await pilot.resize_terminal(59, 15)
        await settle(pilot)
        await pilot.press("question_mark")
        await settle(pilot)
        await pilot.resize_terminal(120, 40)
        await pilot.resize_terminal(60, 16)
        await settle(pilot)
        assert app.is_running
        assert isinstance(app.screen, MainScreen) or type(app.screen).__name__ == "HelpScreen"


def fill_alert_log(app, count: int = 60) -> None:  # type: ignore[no-untyped-def]
    app.alert_log = [
        Event(EventKind.NEW_ADVISORY, f"k{i}", f"Advisory {i} for Ana", T0 + timedelta(minutes=i), "al012026")
        for i in range(count)
    ]


@pytest.mark.xfail(strict=True, reason="#180: the alert log is rebuilt with clear() on every poll")
async def test_alert_log_keeps_its_cursor_and_scroll_when_a_poll_lands() -> None:
    source = MutableSource()
    app = scripted_app(source)
    async with running(app, (100, 24)) as pilot:
        fill_alert_log(app)
        await pilot.press("A")
        await settle(pilot)
        for _ in range(30):
            await pilot.press("down")
        await settle(pilot)
        table = app.screen.query_one("#alert-table", DataTable)
        before = (table.cursor_coordinate, table.scroll_y)
        assert before[0].row == 30 and before[1] > 0, before
        source.set_state("one")
        async with app._tick_lock:
            app.poller.refresh()
            await app.poller.tick()
        await settle(pilot)
        table = app.screen.query_one("#alert-table", DataTable)
        assert (table.cursor_coordinate, table.scroll_y) == before


@pytest.mark.xfail(strict=True, reason="#182: the empty Buoys list is focused, then hidden")
async def test_focus_is_visible_on_the_buoys_screen_with_no_buoys() -> None:
    source = MutableSource()
    source.set_state("one")  # with a storm on the map and no buoys near it the list is hidden; on a quiet day it is not
    app = scripted_app(source)
    async with running(app, (120, 40)) as pilot:
        await pilot.press("b")
        await settle(pilot)
        focused = app.focused
        assert focused is None or shown(focused), f"focus on a hidden {focused!r}"
