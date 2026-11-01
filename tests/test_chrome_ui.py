"""The shared chrome on real screens: top bar, footer, clicks, Esc and q, `m`, and the command palette."""

from __future__ import annotations

import pytest
from textual.pilot import Pilot
from textual.widgets import Input

from eyewall.ui.chrome import ChromeBar, FooterBar, TopBar
from eyewall.ui.screens.buoy_detail import BuoyDetailScreen
from eyewall.ui.screens.detail import StormDetailScreen
from eyewall.ui.screens.feeds import FeedsScreen
from eyewall.ui.screens.help import HelpScreen
from eyewall.ui.screens.main import MainScreen
from eyewall.ui.screens.watchlist import WatchlistScreen
from tests.ui_support import into_the_storm, press, replay_app, running, scripted_app, settle, wait_until

SIZES = [(80, 24), (120, 30), (200, 50)]


def row(app, y: int) -> str:  # type: ignore[no-untyped-def]
    return "\n".join(s.text for s in app.screen._compositor.render_strips()).splitlines()[y]


def top(app) -> str:  # type: ignore[no-untyped-def]
    return row(app, 0)


def bottom(app) -> str:  # type: ignore[no-untyped-def]
    return row(app, app.size.height - 1)


async def click(pilot: Pilot[None], bar: type[ChromeBar], action: str) -> None:
    widget = pilot.app.screen.query_one(bar)
    target = next(t for t in widget.row.targets if t.action == action)
    await pilot.click(bar, offset=(target.start + 1, 0))
    await settle(pilot)


# ---- the two bars at every size ---------------------------------------------------------------------------------


@pytest.mark.parametrize("size", SIZES)
async def test_main_chrome_at_each_size(size: tuple[int, int]) -> None:
    app = replay_app()
    async with running(app, size) as pilot:
        await into_the_storm(pilot)
        assert top(app).startswith(" Home")
        assert "replay" in top(app).rstrip().split("  ")[-1]  # the health slot, whole, at the right edge
        foot = bottom(app).rstrip()
        assert foot.endswith("? help  ^p menu  q quit"), foot
        assert "enter open" in foot and "esc" not in foot  # nothing to go back to on the first screen
        assert len(foot) <= size[0]


@pytest.mark.parametrize("size", SIZES)
async def test_detail_chrome_has_a_breadcrumb_and_esc_back(size: tuple[int, int]) -> None:
    app = replay_app()
    async with running(app, size) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "enter")
        assert isinstance(app.screen, StormDetailScreen)
        assert top(app).startswith(" Home › Erin")
        foot = bottom(app).rstrip()
        assert foot.endswith("? help  ^p menu  esc back"), foot
        assert "q quit" not in foot
        assert len(foot) <= size[0]


async def test_the_health_slot_says_ok_on_a_live_style_source() -> None:
    app = scripted_app()
    async with running(app, (80, 24)) as pilot:
        await wait_until(pilot, lambda: "data ok" in top(app))
        assert top(app).rstrip().endswith("● data ok" + top(app).rstrip().split("data ok")[1])


async def test_every_screen_has_both_bars() -> None:
    app = replay_app()
    async with running(app, (120, 30)) as pilot:
        await into_the_storm(pilot)
        for key in ("A", "w"):
            await press(pilot, key)
            assert len(app.screen.query(TopBar)) == 1 and len(app.screen.query(FooterBar)) == 1
            assert "? help" in bottom(app)
            await press(pilot, "escape")
        await press(pilot, "enter", "g")
        assert top(app).startswith(" Home › Erin › Graphics")


# ---- esc, q and m -----------------------------------------------------------------------------------------------


async def test_esc_goes_back_and_q_quits_only_on_the_first_screen() -> None:
    app = replay_app()
    async with running(app, (120, 30)) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "enter")
        await press(pilot, "q")
        assert isinstance(app.screen, StormDetailScreen) and not app._exit
        await press(pilot, "escape")
        assert isinstance(app.screen, MainScreen)
        await press(pilot, "escape")
        assert isinstance(app.screen, MainScreen) and not app._exit  # nothing to go back to
        await press(pilot, "q")
        assert app._exit


async def test_esc_leaves_the_full_screen_map_before_anything_else() -> None:
    app = replay_app()
    async with running(app, (140, 45)) as pilot:
        await press(pilot, "M")
        assert app.screen._full_map  # type: ignore[attr-defined]
        assert "esc back" in bottom(app)
        await press(pilot, "escape")
        assert not app.screen._full_map  # type: ignore[attr-defined]
        assert "q quit" in bottom(app)


@pytest.mark.parametrize("size", [(80, 24), (140, 45)])
async def test_m_goes_to_the_map_from_any_screen(size: tuple[int, int]) -> None:
    app = replay_app()
    async with running(app, size) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "enter")
        await press(pilot, "m")
        assert isinstance(app.screen, MainScreen)
        assert app.screen.map_view.display


# ---- clicks -----------------------------------------------------------------------------------------------------


async def test_clicking_a_footer_key_does_what_the_key_does() -> None:
    app = replay_app()
    async with running(app, (120, 30)) as pilot:
        await into_the_storm(pilot)
        await click(pilot, FooterBar, "key:enter")
        assert isinstance(app.screen, StormDetailScreen)


async def test_clicking_the_pinned_keys() -> None:
    app = replay_app()
    async with running(app, (80, 24)) as pilot:
        await into_the_storm(pilot)
        await click(pilot, FooterBar, "app:help")
        assert isinstance(app.screen, HelpScreen)
        await press(pilot, "escape")
        await press(pilot, "enter")
        assert isinstance(app.screen, StormDetailScreen)
        await click(pilot, FooterBar, "app:back")
        assert isinstance(app.screen, MainScreen)


async def test_clicking_a_breadcrumb_goes_back_to_it() -> None:
    app = replay_app()
    async with running(app, (140, 45)) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "enter")
        station = next(iter(app.store.stations))
        app.open_buoy(station)
        await settle(pilot)
        assert isinstance(app.screen, BuoyDetailScreen)
        assert top(app).startswith(f" Home › Erin › Buoy {station}")
        await click(pilot, TopBar, "app:crumb(1)")
        assert isinstance(app.screen, StormDetailScreen)
        await click(pilot, TopBar, "app:crumb(0)")
        assert isinstance(app.screen, MainScreen)


async def test_clicking_the_health_slot_opens_the_feed_list_and_d_does_too() -> None:
    app = replay_app()
    async with running(app, (80, 24)) as pilot:
        await click(pilot, TopBar, "app:feeds")
        assert isinstance(app.screen, FeedsScreen)
        await press(pilot, "escape")
        await press(pilot, "D")
        assert isinstance(app.screen, FeedsScreen)
        await press(pilot, "D")
        assert isinstance(app.screen, MainScreen)


# ---- the command palette ----------------------------------------------------------------------------------------


async def palette(pilot: Pilot[None], text: str) -> None:
    await press(pilot, "ctrl+p")
    assert pilot.app.screen.query(Input), "the command palette did not open"
    await pilot.press(*text)
    await pilot.pause(0.6)


async def test_the_palette_opens_and_runs_an_action() -> None:
    app = replay_app()
    async with running(app, (120, 30)) as pilot:
        await palette(pilot, "watchlist")
        await pilot.press("enter")
        await wait_until(pilot, lambda: isinstance(app.screen, WatchlistScreen))


async def test_the_palette_lists_every_screen_and_action_before_anything_is_typed() -> None:
    app = replay_app()
    async with running(app, (120, 30)) as pilot:
        await press(pilot, "ctrl+p")
        await pilot.pause(0.6)
        text = "\n".join(s.text for s in app.screen._compositor.render_strips())
        assert "Open the watchlist" in text and "Go to the map" in text
        assert "Change theme" not in text  # Textual's own commands are not offered


async def test_the_palette_finds_a_storm_and_a_station() -> None:
    app = replay_app()
    async with running(app, (120, 30)) as pilot:
        await into_the_storm(pilot)
        await palette(pilot, "erin")
        await pilot.press("enter")
        await wait_until(pilot, lambda: isinstance(app.screen, StormDetailScreen))
        await press(pilot, "escape")
        station = next(iter(app.store.stations))
        await palette(pilot, station)
        await pilot.press("enter")
        await wait_until(pilot, lambda: isinstance(app.screen, BuoyDetailScreen))
        assert app.screen.station_id == station.upper()  # type: ignore[attr-defined]


async def test_the_palette_hides_replay_commands_on_a_live_source() -> None:
    app = scripted_app()
    async with running(app, (120, 30)) as pilot:
        await press(pilot, "ctrl+p")
        await pilot.press(*"replay")
        await pilot.pause(0.6)
        text = "\n".join(s.text for s in app.screen._compositor.render_strips())
        assert "Replay slower" not in text


# ---- review follow-ups ------------------------------------------------------------------------------------------


async def test_a_cancelled_search_does_not_cancel_the_catalog_fetch() -> None:
    import asyncio

    from eyewall.ui.nav import EyewallCommands

    app = scripted_app()
    async with running(app, (120, 30)):
        calls: list[int] = []
        finished: list[int] = []

        async def slow() -> bool:
            calls.append(1)
            await asyncio.sleep(0.3)
            finished.append(1)
            return False

        app.ensure_catalogs = slow  # type: ignore[method-assign]
        app.store.stations.clear()
        provider = EyewallCommands(app.screen, None)

        async def drain(query: str) -> None:
            async for _ in provider.search(query):
                pass

        first = asyncio.ensure_future(drain("41"))
        await asyncio.sleep(0.05)
        first.cancel()  # the next keystroke
        await drain("410")
        assert calls == [1] and finished == [1]  # one fetch, run to the end


async def test_the_alert_count_outranks_the_replay_clock_at_80_columns_on_a_deep_screen() -> None:
    app = replay_app()
    async with running(app, (80, 24)) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "enter")
        app.open_buoy(next(iter(app.store.stations)))
        app.alert_log = [object()] * 3  # type: ignore[list-item]
        await settle(pilot)
        app._for_screens("refresh_status")
        await settle(pilot)
        assert isinstance(app.screen, BuoyDetailScreen)
        assert "3 alerts" in top(app)


async def test_q_quits_from_the_too_small_screen() -> None:
    app = replay_app()
    async with running(app, (40, 12)) as pilot:
        await settle(pilot)
        assert "q quit" in "\n".join(s.text for s in app.screen._compositor.render_strips())
        await press(pilot, "q")
        assert app._exit


async def test_the_palette_offers_no_commands_while_a_dialog_is_open() -> None:
    app = replay_app()
    async with running(app, (120, 30)) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "D")
        assert isinstance(app.screen, FeedsScreen)
        await press(pilot, "ctrl+p")
        await pilot.pause(0.6)
        text = "\n".join(s.text for s in app.screen._compositor.render_strips())
        assert "Open the watchlist" not in text and "Go to the map" not in text


async def test_q_does_nothing_inside_the_full_screen_map_and_the_footer_agrees() -> None:
    app = replay_app()
    async with running(app, (140, 45)) as pilot:
        await press(pilot, "M")
        assert "q quit" not in bottom(app)
        await press(pilot, "q")
        assert not app._exit
