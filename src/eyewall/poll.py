"""The multi-feed poller and the freshness model.

Plain asyncio with no Textual in it, adapted from cfbtui's PollScheduler. The scheduler owns six feeds, each with its
own interval (`[poll]` in the config), failure count and freshness. A feed fetches from the `DataSource`, applies the
result to the `Store` and passes the events that follow through the `AlertEngine`. Clocks and sleeping are injectable,
so tests and the headless replay drive it on a `VirtualClock` without waiting.

**What "stale" means.** `Freshness` measures the age of the feed's last successful fetch, never the age of the last
change: a quiet storm produces polls that diff to nothing, and those are fresh. Data is only old when polls stop
succeeding or stop happening, or when the source had to answer from its disk cache because the network failed.

- `loading`: nothing fetched yet and nothing has failed.
- `fresh`: the last attempt worked and its age is within `stale_after` (2.5 intervals, so one missed poll does not
  flicker and two do).
- `stale`: the last attempt worked but the age exceeds `stale_after`, or the answer came from the cache.
- `error`: the last attempt failed. The store keeps the last good data.

**Intervals.** Away mode triples every interval. After a failed poll the delay doubles per consecutive failure up to
`backoff_max` and never drops below the normal interval. `refresh()` wakes the loop and makes every feed due.

**What is refetched.** `CurrentStorms` is polled on the storms interval; a storm's advisory text, GIS zips, best track
and graphics are fetched only when its advisory number or last-update time changes. The api.weather.gov copy of the
text is a gated fallback: asked for only when tgftp still serves the previous advisory, from the second attempt on, and
given up after `FALLBACK_ATTEMPTS`. The alerts feed is polled only while a storm is a US threat.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from eyewall.clock import Clock, SystemClock
from eyewall.config import PollConfig
from eyewall.models.events import Event
from eyewall.models.obs import TideStation
from eyewall.net import FetchError
from eyewall.providers.base import ParseError
from eyewall.sources import protocol
from eyewall.sources.protocol import DataSource
from eyewall.state.alerts import AlertEngine
from eyewall.state.events import current_adv, fetched_adv
from eyewall.state.store import Store, storm_key

STALE_FACTOR = 2.5
AWAY_FACTOR = 3.0
FALLBACK_ATTEMPTS = 3
MAX_IN_FLIGHT = 4
STAGGER_SECONDS = 0.25
MAX_BUOY_SERIES = 24
MAX_TIDE_GAUGES = 12
STATION_REFRESH = 24 * 3600.0

# CO-OPS answers a water level request with HTTP 400 for a datum the gauge lacks; the Great Lakes need IGLD.
DATUM_COAST = "MLLW"
DATUM_GREAT_LAKES = "IGLD"


class FreshnessState(StrEnum):
    LOADING = "loading"
    FRESH = "fresh"
    STALE = "stale"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class Freshness:
    state: FreshnessState = FreshnessState.LOADING
    age: float | None = None
    stale_after: float = 0.0
    failures: int = 0
    error: str | None = None
    from_cache: bool = False

    @property
    def data_old(self) -> bool:
        return self.from_cache or (self.age is not None and self.age > self.stale_after)


@dataclass(frozen=True, slots=True)
class PollResult:
    """One feed's attempt."""

    feed: str
    freshness: Freshness
    events: tuple[Event, ...] = ()
    error: Exception | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass(slots=True)
class _FeedState:
    interval: float
    failures: int = 0
    last_ok: float | None = None
    last_error: Exception | None = None
    next_at: float = 0.0
    from_cache: bool = False
    polls: int = 0


async def no_sleep(_seconds: float) -> None:
    """A sleep that returns at once, for runs on a virtual clock."""
    return None


class Poller:
    def __init__(
        self,
        source: DataSource,
        store: Store,
        engine: AlertEngine,
        config: PollConfig | None = None,
        *,
        clock: Clock | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        on_events: Callable[[list[Event]], None] | None = None,
        on_result: Callable[[PollResult], None] | None = None,
        idle_for: Callable[[], float | None] | None = None,
    ) -> None:
        """`idle_for` reports seconds since the user last touched the machine (None means unknown, never away)."""
        self.source = source
        self.store = store
        self.engine = engine
        self.config = config or PollConfig()
        self.clock: Clock = clock or SystemClock()
        self._sleep = sleep
        self.on_events = on_events
        self.on_result = on_result
        self._idle_for = idle_for
        self.away = False
        self.polling = False
        self._wake = asyncio.Event()
        self._stopped = False
        self._feeds: dict[str, _FeedState] = {name: _FeedState(self._base(name)) for name in protocol.FEEDS}
        self._fetchers: dict[str, Callable[[], Awaitable[list[Event]]]] = {
            protocol.STORMS: self._poll_storms,
            protocol.OUTLOOK: self._poll_outlook,
            protocol.ALERTS: self._poll_alerts,
            protocol.BUOYS: self._poll_buoys,
            protocol.TIDES: self._poll_tides,
            protocol.SATELLITE: self._poll_satellite,
        }
        self._attempts: dict[tuple[str, tuple[str | None, datetime | None]], int] = {}
        self._stations_at: dict[str, float] = {}
        self.fetch_counts: dict[str, int] = {}

    # ---- timing -----------------------------------------------------------------------------------------------

    def _base(self, feed: str) -> float:
        return float(getattr(self.config, feed))

    def interval(self, feed: str) -> float:
        """The normal interval in the current mode: tripled while the user is away."""
        return self._base(feed) * (AWAY_FACTOR if self.away else 1.0)

    def set_away(self, away: bool) -> None:
        """Enter or leave away mode. Coming back polls everything at once."""
        returning = self.away and not away
        self.away = away
        if returning:
            self.refresh()

    def observe_presence(self) -> bool:
        """Call about once a second from the app. Returns True on the moment the user comes back."""
        if self._idle_for is None:
            return False
        idle = self._idle_for()
        away = idle is not None and idle >= self.config.away_after
        was_away = self.away
        self.set_away(away)
        return was_away and not away

    def delay(self, feed: str) -> float:
        """Seconds to wait after the last attempt: the interval, or the exponential backoff after failures."""
        state = self._feeds[feed]
        base = self.interval(feed)
        if state.failures:
            return max(base, min(self.config.backoff_max, base * 2**state.failures))
        return base

    def due(self) -> list[str]:
        now = self.clock.monotonic()
        return [name for name in protocol.FEEDS if self._feeds[name].next_at <= now and self._enabled(name)]

    def seconds_until_next(self) -> float | None:
        """Seconds until the earliest enabled feed is due; None when nothing is enabled."""
        waits = [self._feeds[n].next_at for n in protocol.FEEDS if self._enabled(n)]
        return max(0.0, min(waits) - self.clock.monotonic()) if waits else None

    def freshness(self, feed: str) -> Freshness:
        state = self._feeds[feed]
        age = None if state.last_ok is None else max(0.0, self.clock.monotonic() - state.last_ok)
        stale_after = STALE_FACTOR * self.interval(feed)
        if state.failures:
            kind = FreshnessState.ERROR
        elif age is None:
            kind = FreshnessState.LOADING
        elif age > stale_after or state.from_cache:
            kind = FreshnessState.STALE
        else:
            kind = FreshnessState.FRESH
        error = None
        if state.last_error is not None and state.failures:
            error = f"{type(state.last_error).__name__}: {state.last_error}"
        return Freshness(kind, age, stale_after, state.failures, error, state.from_cache)

    def _enabled(self, feed: str) -> bool:
        if feed == protocol.STORMS or feed == protocol.OUTLOOK:
            return True
        if feed == protocol.ALERTS:
            return self.store.us_threat()
        return bool(self.store.storms)

    # ---- running ----------------------------------------------------------------------------------------------

    def refresh(self) -> None:
        """Make every feed due now and wake the loop."""
        for state in self._feeds.values():
            state.next_at = 0.0
        if not self.polling:
            self._wake.set()

    def stop(self) -> None:
        self._stopped = True
        self._wake.set()

    async def tick(self) -> list[PollResult]:
        """Poll every feed that is due, in dependency order (storms first). Never raises on a bad fetch."""
        results: list[PollResult] = []
        self.polling = True
        try:
            for name in protocol.FEEDS:  # re-checked per feed: the storms poll decides whether the others apply
                if self._feeds[name].next_at <= self.clock.monotonic() and self._enabled(name):
                    results.append(await self.poll_feed(name))
        finally:
            self.polling = False
        return results

    async def poll_feed(self, feed: str) -> PollResult:
        state = self._feeds[feed]
        events: list[Event] = []
        error: Exception | None = None
        self.fetch_counts[feed] = self.fetch_counts.get(feed, 0) + 1
        try:
            events = await self._fetchers[feed]()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # a parser bug must not kill the poll loop either
            error = exc
        state.polls += 1
        if error is None:
            state.failures = 0
            state.last_error = None
            state.last_ok = self.clock.monotonic()
            state.from_cache = self.source.stale(feed)
        else:
            state.failures += 1
            state.last_error = error
        state.next_at = self.clock.monotonic() + self.delay(feed)
        shown = self.engine.process(events, self.source.now()) if events else []
        if shown and self.on_events is not None:
            self.on_events(shown)
        result = PollResult(feed, self.freshness(feed), tuple(shown), error)
        if self.on_result is not None:
            self.on_result(result)
        return result

    async def run(self) -> None:
        """Poll forever until `stop` or cancellation."""
        while not self._stopped:
            self._wake.clear()
            await self.tick()
            wait = self.seconds_until_next()
            if wait is None:
                wait = self.interval(protocol.STORMS)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=wait)

    # ---- the feeds --------------------------------------------------------------------------------------------

    async def _poll_storms(self) -> list[Event]:
        now = self.source.now()
        events = self.store.apply_storms(await self.source.storms(), now)
        for storm_id, state in list(self.store.storms.items()):
            key = storm_key(state.storm)
            if state.fetched_key == key:
                continue
            events += await self._fetch_products(storm_id, key)
        return events

    async def _fetch_products(self, storm_id: str, key: tuple[str | None, datetime | None]) -> list[Event]:
        """The heavy products for a storm whose advisory number or update time just changed."""
        storm = self.store.storms[storm_id].storm
        now = self.source.now()
        attempt = self._attempts.get((storm_id, key), 0) + 1
        self._attempts[(storm_id, key)] = attempt
        advisories = await self.source.advisory(storm, fallback=attempt >= 2)
        wanted = current_adv(storm)
        have = fetched_adv(advisories)
        behind = wanted is not None and have != wanted
        if behind and attempt < FALLBACK_ATTEMPTS:
            # tgftp still serves the previous advisory. Keep the old products and ask again next poll, the second
            # time through api.weather.gov.
            return []
        forecast_gis = await self._optional(self.source.forecast_gis(storm))
        radii_gis = await self._optional(self.source.radii_gis(storm))
        track = await self._optional(self.source.track(storm))
        graphics = await self._optional(self.source.graphics(storm))
        self._attempts = {k: v for k, v in self._attempts.items() if k[0] != storm_id or k == (storm_id, key)}
        return self.store.apply_products(
            storm_id,
            now,
            key=key,
            advisories=advisories if not behind or have is not None else None,
            forecast_gis=forecast_gis,
            radii_gis=radii_gis,
            track=track,
            graphics=graphics,
        )

    @staticmethod
    async def _optional[T](call: Awaitable[T]) -> T | None:
        """A product that fails does not discard the others; the next advisory change tries it again."""
        try:
            return await call
        except (FetchError, ParseError, ValueError):
            return None

    async def _poll_outlook(self) -> list[Event]:
        return self.store.apply_outlook(await self.source.outlook(), self.source.now())

    async def _poll_alerts(self) -> list[Event]:
        self.store.apply_alerts(await self.source.alerts())
        return []

    def _station_catalog_due(self, name: str) -> bool:
        last = self._stations_at.get(name)
        return last is None or self.clock.monotonic() - last >= STATION_REFRESH

    async def _poll_buoys(self) -> list[Event]:
        if not self.store.stations or self._station_catalog_due("ndbc"):
            self.store.apply_stations(await self.source.ndbc_stations())
            self._stations_at["ndbc"] = self.clock.monotonic()
        self.store.apply_latest(await self.source.ndbc_latest())
        wanted: dict[str, None] = {}
        for storm_id in self.store.storms:
            for entry in self.store.nearby_buoys(storm_id)[:MAX_BUOY_SERIES]:
                wanted[entry.station.id.upper()] = None
        semaphore = asyncio.Semaphore(MAX_IN_FLIGHT)

        async def one(index: int, station_id: str) -> None:
            async with semaphore:
                await self._sleep(index % MAX_IN_FLIGHT * STAGGER_SECONDS)
                try:
                    self.store.apply_series(await self.source.ndbc_series(station_id))
                except (FetchError, ParseError):
                    return

        await asyncio.gather(*(one(i, sid) for i, sid in enumerate(wanted)))
        return self.store.buoy_events(self.source.now())

    async def _poll_tides(self) -> list[Event]:
        if not self.store.tide_stations or self._station_catalog_due("coops"):
            self.store.apply_tide_stations(await self.source.coops_stations())
            self._stations_at["coops"] = self.clock.monotonic()
        gauges: dict[str, TideStation] = {}
        for storm_id in self.store.storms:
            for entry in self.store.nearby_tides(storm_id)[:MAX_TIDE_GAUGES]:
                gauges[entry.station.id] = entry.station
        semaphore = asyncio.Semaphore(MAX_IN_FLIGHT)

        async def one(index: int, station: TideStation) -> None:
            datum = DATUM_GREAT_LAKES if station.great_lakes else DATUM_COAST
            async with semaphore:
                await self._sleep(index % MAX_IN_FLIGHT * STAGGER_SECONDS)
                try:
                    self.store.apply_tide_series(await self.source.coops_series(station, datum))
                except (FetchError, ParseError) as exc:
                    self.store.apply_tide_error(station.id, str(exc))

        await asyncio.gather(*(one(i, g) for i, g in enumerate(gauges.values())))
        return []

    async def _poll_satellite(self) -> list[Event]:
        for storm_id, state in list(self.store.storms.items()):
            try:
                self.store.apply_satellite(storm_id, await self.source.satellite(state.storm))
            except (FetchError, ParseError):
                continue
        return []
