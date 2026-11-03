"""On a terminal under the minimum no toast is drawn over the "Needs at least 60x16" message."""

from __future__ import annotations

import pytest

from tests.ui_support import into_the_storm, replay_app, running, screen_text, settle


@pytest.mark.parametrize("size", [(59, 16), (60, 15), (40, 10)])
async def test_replay_toasts_do_not_cover_the_size_message(size: tuple[int, int]) -> None:
    app = replay_app()
    async with running(app, size) as pilot:
        await into_the_storm(pilot, 2)  # advisories land and would toast
        app.notify("New advisory", markup=False)
        await settle(pilot)
        assert type(app.screen).__name__ == "TooSmallScreen"
        assert not app._notifications
        assert "Needs at least 60x16" in screen_text(app)


async def test_toasts_already_showing_are_cleared_when_the_terminal_shrinks() -> None:
    app = replay_app()
    async with running(app, (100, 30)) as pilot:
        app.notify("New storm", markup=False)
        await settle(pilot)
        assert app._notifications
        await pilot.resize_terminal(50, 12)
        await settle(pilot)
        assert not app._notifications
        assert "Needs at least 60x16" in screen_text(app)
