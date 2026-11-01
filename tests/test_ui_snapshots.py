"""SVG snapshots of the main screen (a storm, three sizes, and a quiet day) and the detail, buoy and settings screens
over the saved replay and outlook payloads.

Regenerate with `pytest tests/test_ui_snapshots.py --snapshot-update` after a deliberate layout change.
"""

from __future__ import annotations

import asyncio

from textual.pilot import Pilot

from eyewall.ui.chrome import Health
from tests.ui_support import into_the_storm, replay_app, scripted_app, settle


def _ready(app_factory, keys: tuple[str, ...] = (), *, storm: bool = False):  # type: ignore[no-untyped-def]
    async def run_before(pilot: Pilot[None]) -> None:
        await pilot.pause()
        await asyncio.wait_for(pilot.app.first_poll.wait(), 30)  # type: ignore[attr-defined]
        await settle(pilot)
        if storm:
            await into_the_storm(pilot)
            pilot.app.clear_notifications()  # toasts expire on the wall clock; a picture must not depend on it
        # Feed ages and the replay clock follow the wall clock; pin the top bar's slot so the picture is repeatable.
        pilot.app.health = lambda: Health("●", "data ok", "ok", "3m", "")  # type: ignore[attr-defined, method-assign]
        pilot.app.top_bar_extras = lambda: [("pinned", None)]  # type: ignore[attr-defined, method-assign]
        pilot.app._for_screens("refresh_status")  # type: ignore[attr-defined]
        for key in keys:
            await pilot.press(key)
            await settle(pilot)

    return run_before


def test_main_screen_snapshot(snap_compare) -> None:  # type: ignore[no-untyped-def]
    assert snap_compare(replay_app(), terminal_size=(140, 45), run_before=_ready(replay_app))


def test_main_screen_small_snapshot(snap_compare) -> None:  # type: ignore[no-untyped-def]
    assert snap_compare(replay_app(), terminal_size=(80, 24), run_before=_ready(replay_app))


def test_main_screen_large_snapshot(snap_compare) -> None:  # type: ignore[no-untyped-def]
    assert snap_compare(replay_app(), terminal_size=(200, 50), run_before=_ready(replay_app))


def test_forecast_tab_snapshot(snap_compare) -> None:  # type: ignore[no-untyped-def]
    assert snap_compare(replay_app(), terminal_size=(140, 45), run_before=_ready(replay_app, ("enter", "2")))


def test_quiet_main_screen_snapshot(snap_compare) -> None:  # type: ignore[no-untyped-def]
    assert snap_compare(scripted_app(), terminal_size=(140, 45), run_before=_ready(scripted_app))


def test_buoys_tab_snapshot(snap_compare) -> None:  # type: ignore[no-untyped-def]
    assert snap_compare(
        replay_app(), terminal_size=(140, 45), run_before=_ready(replay_app, ("enter", "7"), storm=True)
    )


def test_tides_tab_snapshot(snap_compare) -> None:  # type: ignore[no-untyped-def]
    assert snap_compare(
        replay_app(), terminal_size=(140, 45), run_before=_ready(replay_app, ("enter", "8"), storm=True)
    )


def test_buoy_detail_snapshot(snap_compare) -> None:  # type: ignore[no-untyped-def]
    assert snap_compare(
        replay_app(), terminal_size=(140, 45), run_before=_ready(replay_app, ("enter", "7", "enter"), storm=True)
    )


def test_watchlist_snapshot(snap_compare) -> None:  # type: ignore[no-untyped-def]
    assert snap_compare(replay_app(), terminal_size=(140, 45), run_before=_ready(replay_app, ("w",), storm=True))


def test_settings_snapshot(snap_compare) -> None:  # type: ignore[no-untyped-def]
    assert snap_compare(replay_app(), terminal_size=(100, 40), run_before=_ready(replay_app, ("S",)))
