"""The help hint on the status line survives the crowded worst case at 80 columns."""

from __future__ import annotations

from eyewall.poll import Freshness, FreshnessState
from tests.ui_support import replay_app, running, screen_text


async def test_help_hint_stays_visible_on_a_crowded_status_line() -> None:
    app = replay_app()
    async with running(app, (80, 24)) as pilot:
        app.poller.freshness = lambda feed: Freshness(FreshnessState.STALE, age=7500.0)  # type: ignore[method-assign]
        app.poller.active = lambda feed: True  # type: ignore[method-assign]
        app.alert_log = [object()] * 12  # type: ignore[list-item]
        app.screen.refresh_status()  # type: ignore[attr-defined]
        await pilot.pause(0.5)
        last = screen_text(app).splitlines()[-1]
        assert last.rstrip().endswith("? help"), last
