"""Worlds: the app states of the UAT matrix, built deterministically (no network, no wall clock), and `W`, the handle
a check drives.

States (see `STATES`): first_run, offline, loading, stale, empty, quiet, busy, error, demo.

- `busy`, `stale` and `error` run a LIVE-style source (not a replay) that serves the Erin recording frozen at an
  advisory, so the health slot, the poller's freshness and the failure paths are the real ones.
- `quiet`, `empty`, `first_run`, `offline` use the scripted no-storm source from `tests.ui_support`.
- `loading` uses a source whose storms feed never answers.
- `demo` is the replay mode.
"""

from __future__ import annotations

import asyncio
import inspect
import tempfile
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from textual.pilot import Pilot
from textual.screen import Screen

from eyewall.app import EyewallApp
from eyewall.config import Config
from eyewall.models.outlook import Outlook
from eyewall.models.storm import CurrentStorms
from eyewall.poll import FreshnessState
from eyewall.sources import protocol
from eyewall.net import FetchError, HttpError, NetworkError
from eyewall.ui.screens.main import MainScreen
from tests.ui_support import EDT, ScriptedSource, replay_app, replay_source, screen_text, settle
from tests.uat.inventory.registry import World

STATES = ("first_run", "offline", "loading", "stale", "empty", "quiet", "busy", "error", "demo")
SIZES = ((100, 30), (120, 30), (200, 50), (280, 70), (80, 24))
STORM_ADVISORIES = 15  # the replay opens on advisory 1 by itself; the app's own UAT stands 14 more in


class OffsetClock:
    """The poller's clock plus a jump, to age every feed without waiting."""

    def __init__(self, base: Any, source: Any = None) -> None:
        self.base = base
        self.source = source
        self._offset = 0.0

    @property
    def offset(self) -> float:
        return self._offset

    @offset.setter
    def offset(self, seconds: float) -> None:
        self._offset = seconds
        if self.source is not None:
            self.source.shift = timedelta(seconds=seconds)  # the source's "now" moves with the poller's

    def now(self):  # type: ignore[no-untyped-def]
        return self.base.now() + timedelta(seconds=self.offset)

    def monotonic(self) -> float:
        return self.base.monotonic() + self.offset


class LiveErin:
    """A live-style source (so the app polls it on its own clock) over the Erin recording frozen at an advisory.
    `fail` is a factory for the error every feed call raises, or None."""

    name = "live-erin"

    def __init__(self, steps: int = STORM_ADVISORIES) -> None:
        self.replay = replay_source()
        for _ in range(steps):
            self.replay.step_advisory(1)
        self.fail: Callable[[str], FetchError] | None = None
        self.shift = timedelta(0)

    def now(self) -> Any:
        return self.replay.now() + self.shift

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self.replay, name)
        if inspect.iscoroutinefunction(attr):

            async def call(*args: Any, **kwargs: Any) -> Any:
                if self.fail is not None:
                    raise self.fail(f"scripted://{name}")
                return await attr(*args, **kwargs)

            return call
        return attr


def network_down(url: str) -> FetchError:
    return NetworkError(url, "network is unreachable")


def server_error(url: str) -> FetchError:
    return HttpError(url, 500)


class BlockedSource(ScriptedSource):
    """The storms feed never answers: the app stays in its loading state."""

    async def storms(self) -> CurrentStorms:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class DownSource(ScriptedSource):
    """Every feed fails the way a dead network does."""

    def __init__(self, error: Callable[[str], FetchError] = network_down) -> None:
        super().__init__()
        self.error = error
        self.fail = True

    def _check(self) -> None:
        raise self.error("scripted://source")


def build(state: str) -> EyewallApp:
    cfg = Config()
    if state == "demo":
        return replay_app()
    if state == "first_run":
        path = Path(tempfile.mkdtemp(prefix="eyewall-uat-")) / "config.toml"
        return EyewallApp(cfg, ScriptedSource(), local_tz=EDT, config_path=path)
    if state == "offline":
        return EyewallApp(cfg, DownSource(), local_tz=EDT)
    if state == "loading":
        return EyewallApp(cfg, BlockedSource(), local_tz=EDT)
    if state == "empty":
        return EyewallApp(cfg, ScriptedSource(Outlook()), local_tz=EDT)
    if state == "quiet":
        return EyewallApp(cfg, ScriptedSource(), local_tz=EDT)
    if state in ("busy", "stale", "error"):
        return EyewallApp(cfg, LiveErin(), local_tz=EDT)  # type: ignore[arg-type]
    raise ValueError(state)


async def after_first_poll(app: EyewallApp, pilot: Pilot[None], state: str) -> None:
    """Move a state past its first poll: age the feeds (stale) or break them (error)."""
    if state == "stale":
        clock = OffsetClock(app.poller.clock, app.source)
        app.poller.clock = clock  # type: ignore[assignment]
        clock.offset = 6 * 3600.0
    elif state == "error":
        app.source.fail = server_error  # type: ignore[attr-defined]
        clock = OffsetClock(app.poller.clock, app.source)
        app.poller.clock = clock  # type: ignore[assignment]
        clock.offset = 900.0
        app.poller.refresh()
        await app.poller.tick()
    app._for_screens("refresh_data")
    app._for_screens("refresh_status")
    await settle(pilot)


async def feeds_done(app: EyewallApp, pilot: Pilot[None], state: str) -> None:
    """Wait until every feed being polled has answered once (or failed), so a state is not caught half-loaded."""
    if state == "loading":
        return
    for _ in range(400):
        loading = [
            f for f in protocol.FEEDS if app.poller.active(f) and app.poller.freshness(f).state is FreshnessState.LOADING
        ]
        if not loading and not app.poller.polling:
            return
        await pilot.pause(0.05)


@asynccontextmanager
async def launch(world: World) -> AsyncIterator[W]:
    app = build(world.state)
    async with app.run_test(size=world.size) as pilot:
        await pilot.pause()
        if world.state != "loading":
            await asyncio.wait_for(app.first_poll.wait(), 30)
        await feeds_done(app, pilot, world.state)
        await settle(pilot)
        if world.state == "demo":
            from tests.ui_support import into_the_storm

            await into_the_storm(pilot)
        await after_first_poll(app, pilot, world.state)
        yield W(app, pilot, world)


SCREEN_NAMES = (
    "main",
    "full_map",
    "storm",
    "text",
    "buoys_near",
    "buoys_yours",
    "station_buoy",
    "station_gauge",
    "alerts",
    "graphics",
    "help",
    "feeds",
    "settings",
    "layers",
    "palette",
    "search",
)
MODAL_NAMES = ("help", "feeds", "settings", "layers", "palette", "search", "chooser")
GONE = "al992026"  # a storm id that is not in the store: the "no longer active" pages


@dataclass
class W:
    app: EyewallApp
    pilot: Pilot[None]
    world: World

    # ---- looking --------------------------------------------------------------------------------------------

    @property
    def screen(self) -> Screen[Any]:
        return self.app.screen

    def text(self) -> str:
        return screen_text(self.app)

    @property
    def storm_id(self) -> str:
        return next(iter(self.app.store.storms), GONE)

    @property
    def has_storm(self) -> bool:
        return bool(self.app.store.storms)

    # ---- driving --------------------------------------------------------------------------------------------

    async def settle(self) -> None:
        await self.pilot.pause()
        await self.pilot.pause(0.04)

    async def press(self, *keys: str) -> None:
        for key in keys:
            await self.pilot.press(key)
            await self.settle()

    async def click(self, widget: Any, offset: tuple[int, int] = (0, 0)) -> None:
        await self.pilot.click(widget, offset=offset)
        await self.settle()

    async def after_tick(self) -> None:
        """Wait past the next refresh: a poll result and the screens' own redraw (what un-sticks a selection)."""
        app = self.app
        app._for_screens("refresh_data")
        app._for_screens("refresh_status")
        await self.pilot.pause(0.3)
        await settle(self.pilot)

    async def home(self) -> MainScreen:
        app = self.app
        for _ in range(12):
            if len(app.screen_stack) <= 1:
                break
            await app.pop_screen()
        await self.settle()
        main = app.screen
        assert isinstance(main, MainScreen), f"the root screen is {main!r}"
        if main._full_map:
            main.action_full_map()
        main.map_view.focused_mark = None
        await self.settle()
        return main

    async def goto(self, name: str) -> Screen[Any]:
        """Open a screen from the root, directly (the keys that open them have their own checks)."""
        from eyewall.ui.screens.buoys import BuoysScreen
        from eyewall.ui.screens.graphics import GraphicsScreen
        from eyewall.ui.screens.nhc_text import NhcTextScreen
        from eyewall.ui.screens.station import StationScreen
        from eyewall.ui.screens.storm import StormScreen

        app = self.app
        main = await self.home()
        sid = self.storm_id
        if name == "main":
            pass
        elif name == "full_map":
            main.action_full_map()
        elif name == "storm":
            app.push_screen(StormScreen(sid))
        elif name == "text":
            app.push_screen(NhcTextScreen(sid if self.has_storm else None))
        elif name == "buoys_near":
            app.push_screen(BuoysScreen(sid))
        elif name == "buoys_yours":
            app.push_screen(BuoysScreen(None))
        elif name == "station_buoy":
            app.push_screen(StationScreen("ndbc", self.buoy_id()))
        elif name == "station_gauge":
            app.push_screen(StationScreen("coops", self.gauge_id()))
        elif name == "alerts":
            app.action_alerts()
        elif name == "graphics":
            app.push_screen(GraphicsScreen(sid))
        elif name == "help":
            app.action_help()
        elif name == "feeds":
            app.action_feeds()
        elif name == "settings":
            app.action_settings()
        elif name == "layers":
            app.open_layers()
        elif name == "palette":
            await self.pilot.press("ctrl+p")
        elif name == "search":
            await self.pilot.press("slash")
        else:
            raise ValueError(name)
        await self.settle()
        await self.pilot.pause(0.1)
        return app.screen

    def buoy_id(self) -> str:
        if self.has_storm:
            near = self.app.store.nearby_buoys(self.storm_id, self.app.now())
            if near:
                return near[0].station.id
        return Config().watchlist.ndbc[0]

    def gauge_id(self) -> str:
        if self.has_storm:
            near = self.app.store.nearby_tides(self.storm_id, self.app.now())
            if near:
                return near[0].station.id
        return Config().watchlist.coops[0]


Check = Callable[[W], Awaitable[None]]
