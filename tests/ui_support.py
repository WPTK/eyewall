"""Helpers for the interface tests: apps over the Erin bundle and over scripted live-style sources, and screen text."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from textual.pilot import Pilot

from eyewall.app import EyewallApp
from eyewall.config import Config
from eyewall.models.advisory import AdvisorySet
from eyewall.models.forecast import ForecastGis
from eyewall.models.graphics import FloaterProduct, GraphicLink
from eyewall.models.obs import (
    LatestObservation,
    ObservationSeries,
    Parsed,
    Station,
    SupplementalReading,
    TideSeries,
    TideStation,
)
from eyewall.models.outlook import Outlook
from eyewall.models.storm import CurrentStorms, Storm
from eyewall.models.track import BestTrack
from eyewall.models.watches import AlertsResult
from eyewall.models.wind import WindRadiiGis
from eyewall.net import FetchError
from eyewall.providers.nhc.text import parse_two
from eyewall.providers.nhc.two import parse_gtwo_zip
from eyewall.sources import bundle
from eyewall.sources.replay import ReplaySource

FIXTURES = Path(__file__).parent / "fixtures"
EDT = timezone(timedelta(hours=-4), "EDT")
QUIET_NOW = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)


def replay_source() -> ReplaySource:
    return ReplaySource(bundle.resolve_bundle(bundle.DEMO))


def replay_app(config: Config | None = None, **kwargs: object) -> EyewallApp:
    """An app over the bundled Erin replay, paused, with a fixed local zone so tables do not depend on the machine."""
    return EyewallApp(config or Config(), replay_source(), autoplay=False, local_tz=EDT, **kwargs)  # type: ignore[arg-type]


def screen_text(app: EyewallApp) -> str:
    """The plain text on the screen, one line per row."""
    return "\n".join(strip.text.rstrip() for strip in app.screen._compositor.render_strips())


@asynccontextmanager
async def running(app: EyewallApp, size: tuple[int, int] = (140, 45)) -> AsyncIterator[Pilot[None]]:
    """Run the app headless at a size and wait until the first storms poll has landed."""
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        await asyncio.wait_for(app.first_poll.wait(), 30)
        await settle(pilot)
        yield pilot


STORM_STEPS = 14  # advisory 14 of the Erin recording: a hurricane off the Carolinas with buoys and gauges around it


async def into_the_storm(pilot, steps: int = STORM_STEPS) -> None:  # type: ignore[no-untyped-def]
    """Move the replay clock forward by advisories and poll once, instead of paying for a full poll on every step."""
    app = pilot.app
    async with app._tick_lock:
        for _ in range(steps):
            app.replay.step_advisory(1)
        app.poller.refresh()
        await app.poller.tick()
    await settle(pilot)


async def settle(pilot: Pilot[None], times: int = 3) -> None:
    for _ in range(times):
        await pilot.pause()
    await pilot.pause(0.1)


async def press(pilot: Pilot[None], *keys: str) -> None:
    for key in keys:
        await pilot.press(key)
        await settle(pilot)


# ---- a source with no storms, for the quiet-day and failure journeys ----------------------------------------------


def quiet_outlook() -> Outlook:
    """The 31 October 2026 outlook: nothing in the Atlantic, one Central Pacific area, from saved NOAA payloads."""
    texts = tuple(
        parse_two((FIXTURES / "nhc" / "two" / name).read_text(encoding="utf-8"))
        for name in ("at_20261031.txt", "ep_20261031.txt", "cp_20261031.txt")
    )
    gis = parse_gtwo_zip((FIXTURES / "gis" / "gtwo_20261031.zip").read_bytes())
    return Outlook(texts, gis, ())


class ScriptedSource:
    """A live-style source (not a ReplaySource, so the app polls it on its own clock) serving a fixed outlook and no
    storms. `fail` makes every feed raise the way a dead network does."""

    name = "scripted"

    def __init__(
        self,
        outlook: Outlook | None = None,
        stations: tuple[Station, ...] = (),
        gauges: tuple[TideStation, ...] = (),
    ) -> None:
        self._outlook = outlook if outlook is not None else quiet_outlook()
        self._stations = stations
        self._gauges = gauges
        self.fail = False
        self.calls: dict[str, int] = {}

    def now(self) -> datetime:
        return QUIET_NOW

    def stale(self, feed: str) -> bool:
        return False

    def cache_answers(self, feed: str) -> int:
        return 0

    def start_poll(self, feed: str) -> None:
        self.calls[feed] = self.calls.get(feed, 0) + 1

    def _check(self) -> None:
        if self.fail:
            raise FetchError("scripted://source", "outage")

    async def storms(self) -> CurrentStorms:
        self._check()
        return CurrentStorms()

    async def outlook(self) -> Outlook:
        self._check()
        return self._outlook

    async def alerts(self) -> AlertsResult:
        self._check()
        return AlertsResult()

    async def advisory(self, storm: Storm, *, fallback: bool = False) -> AdvisorySet:
        return AdvisorySet()

    async def forecast_gis(self, storm: Storm) -> ForecastGis | None:
        return None

    async def radii_gis(self, storm: Storm) -> WindRadiiGis | None:
        return None

    async def track(self, storm: Storm) -> BestTrack | None:
        return None

    async def graphics(self, storm: Storm) -> tuple[GraphicLink, ...]:
        return ()

    async def satellite(self, storm: Storm) -> tuple[FloaterProduct, ...]:
        return ()

    async def satellite_product(self, storm: Storm, product: str) -> FloaterProduct | None:
        return None

    async def image(self, url: str) -> bytes:
        raise FetchError(url, "no images in this fake")

    async def ndbc_stations(self) -> tuple[Station, ...]:
        return self._stations

    async def ndbc_latest(self) -> tuple[LatestObservation, ...]:
        return ()

    async def ndbc_series(self, station_id: str) -> ObservationSeries:
        return ObservationSeries(station_id)

    async def ndbc_supplemental(self, station_id: str) -> Parsed[SupplementalReading]:
        return Parsed(message="scripted: no supplemental file")

    async def coops_stations(self) -> tuple[TideStation, ...]:
        return self._gauges

    async def coops_series(self, station: TideStation, datum: str) -> TideSeries:
        raise FetchError("scripted://tides", "no gauges")


def scripted_app(source: ScriptedSource | None = None, config: Config | None = None) -> EyewallApp:
    return EyewallApp(config or Config(), source or ScriptedSource(), local_tz=EDT)


def with_poll(config: Config, **changes: float) -> Config:
    """The config with some `[poll]` intervals replaced."""
    return replace(config, poll=replace(config.poll, **changes))


Predicate = Callable[[], bool]


async def wait_until(pilot: Pilot[None], condition: Predicate, seconds: float = 10.0) -> None:
    """Pause until the condition holds, failing the test after `seconds`."""
    deadline = asyncio.get_running_loop().time() + seconds
    while not condition():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not reached in time")
        await pilot.pause(0.05)


# The default watchlist (41010, 42001, 41047 and gauge 8721604) at their real positions, for a quiet day with marks.
WATCHLIST_BUOYS = (
    Station("41010", "Canaveral East", 28.878, -78.485),
    Station("42001", "Mid Gulf", 25.897, -89.668),
    Station("41047", "NE Bahamas", 27.465, -71.49),
)
WATCHLIST_GAUGES = (TideStation("8721604", "Trident Pier, Port Canaveral", 28.416, -80.593),)
