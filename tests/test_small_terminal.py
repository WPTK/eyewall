"""Below the smallest usable size the app shows one line saying what it needs, and recovers when enlarged."""

from __future__ import annotations

import pytest

from eyewall.ui.screens.dashboard import DashboardScreen
from eyewall.ui.screens.small import TooSmallScreen
from tests.ui_support import into_the_storm, replay_app, running, screen_text, scripted_app, settle

NOTICE = "Needs at least 60x16"


@pytest.mark.parametrize("size", [(59, 24), (80, 15), (40, 12), (10, 3)])
@pytest.mark.parametrize("make", [replay_app, scripted_app])
async def test_too_small_shows_the_notice_and_does_not_crash(make, size) -> None:  # type: ignore[no-untyped-def]
    app = make()
    async with running(app, size) as pilot:
        await settle(pilot)
        assert isinstance(app.screen, TooSmallScreen)


async def test_the_notice_names_the_size() -> None:
    app = replay_app()
    async with running(app, (40, 12)) as pilot:
        await settle(pilot)
        assert NOTICE in screen_text(app)


async def test_the_dashboard_returns_when_enlarged_and_again_after_shrinking() -> None:
    app = replay_app()
    async with running(app, (40, 12)) as pilot:
        await into_the_storm(pilot)
        assert isinstance(app.screen, TooSmallScreen)
        await pilot.resize_terminal(80, 24)
        await settle(pilot)
        assert isinstance(app.screen, DashboardScreen)
        assert "ERIN" in screen_text(app)
        await pilot.resize_terminal(50, 14)
        await settle(pilot)
        assert isinstance(app.screen, TooSmallScreen)
        await pilot.resize_terminal(60, 16)
        await settle(pilot)
        assert isinstance(app.screen, DashboardScreen)
