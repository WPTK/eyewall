"""SVG snapshots of the dashboard, one detail tab and the outlook over the saved replay and outlook payloads.

Regenerate with `pytest tests/test_ui_snapshots.py --snapshot-update` after a deliberate layout change.
"""

from __future__ import annotations

import asyncio

from rich.text import Text
from textual.pilot import Pilot

from tests.ui_support import replay_app, scripted_app, settle


def _ready(app_factory, keys: tuple[str, ...] = ()):  # type: ignore[no-untyped-def]
    async def run_before(pilot: Pilot[None]) -> None:
        await pilot.pause()
        await asyncio.wait_for(pilot.app.first_poll.wait(), 30)  # type: ignore[attr-defined]
        await settle(pilot)
        # Feed ages and the poll countdown follow the wall clock; pin the bar so the picture is repeatable.
        pilot.app.status_text = lambda width: Text(" status bar pinned for the snapshot")  # type: ignore[attr-defined, method-assign]
        pilot.app._for_screens("refresh_status")  # type: ignore[attr-defined]
        for key in keys:
            await pilot.press(key)
            await settle(pilot)

    return run_before


def test_dashboard_snapshot(snap_compare) -> None:  # type: ignore[no-untyped-def]
    assert snap_compare(replay_app(), terminal_size=(140, 45), run_before=_ready(replay_app))


def test_forecast_tab_snapshot(snap_compare) -> None:  # type: ignore[no-untyped-def]
    assert snap_compare(replay_app(), terminal_size=(140, 45), run_before=_ready(replay_app, ("enter", "2")))


def test_outlook_snapshot(snap_compare) -> None:  # type: ignore[no-untyped-def]
    assert snap_compare(scripted_app(), terminal_size=(140, 45), run_before=_ready(scripted_app, ("O",)))
