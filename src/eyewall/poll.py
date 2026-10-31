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

**Intervals.** Away mode triples every interval; coming back from it makes the feeds due a few seconds apart. After a
failed poll the delay doubles per consecutive failure up to `backoff_max` and never drops below the normal
interval. A server that says 429 or 5xx counts as a failure even when the disk cache answered for it, and its
Retry-After sets a floor on the wait. `refresh()` wakes the loop and makes every feed due, but never sooner than
`REFRESH_MIN_GAP` after that feed's last attempt, so holding the key does not hammer NOAA. A feed that runs past
`FEED_DEADLINE` seconds is cut off, so one hung host cannot hold up the others.

**What is refetched.** `CurrentStorms` is polled on the storms interval; a storm's advisory text, GIS zips, best track
and graphics are fetched only when its advisory number or last-update time changes. The api.weather.gov copy of the
text is a gated fallback: asked for only when tgftp still serves the previous advisory, from the second attempt on. A
product that fails (a GIS zip not posted yet, a 503), a product the source could only answer from its disk cache, and
the advisory text while it is still behind are asked for again on the next polls, up to `PRODUCT_ATTEMPTS`; the
advisory is not settled before. The alerts feed is polled only while
a storm is a US threat.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from eyewall.clock import Clock, SystemClock
from eyewall.config import PollConfig
from eyewall.models.advisory import AdvisorySet
from eyewall.models.events import Event
from eyewall.models.obs import TideStation
from eyewall.models.watches import AlertsResult
from eyewall.net import FetchError, HttpError, RateLimited
from eyewall.providers.base import ParseError
from eyewall.sources import protocol
from eyewall.sources.protocol import DataSource, ThrottleReporting
from eyewall.state.alerts import AlertEngine
from eyewall.state.events import current_adv, fetched_adv, missing_products
from eyewall.state.store import Store, storm_key

STALE_FACTOR = 2.5
AWAY_FACTOR = 3.0
FALLBACK_ATTEMPTS = 3
PRODUCT_ATTEMPTS = 12  # polls (about an hour at the default interval) a failing product is asked for before giving up
REFRESH_MIN_GAP = 30.0  # seconds between attempts of one feed, however often the refresh key is pressed
FEED_DEADLINE = 300.0  # seconds one feed's poll may take in all
MAX_IN_FLIGHT = 4
STAGGER_SECONDS = 0.25
RETURN_STAGGER_SECONDS = 3.0  # between the feeds' first polls after the user comes back from away mode
MAX_BUOY_SERIES = 24
MAX_TIDE_GAUGES = 12
PERMANENT_STATUSES = frozenset({400, 404, 410})  # a station answered for good; see _is_permanent
STATION_REFRESH = 24 * 3600.0
_PRODUCTS = ("forecast_gis", "radii_gis", "track", "graphics")
_TEXT = "advisory"  # the text products, tracked beside the others in `_pending`
MAX_BACKOFF_EXPONENT = 16  # 2**failures overflows a float after about 1000 consecutive failures

# CO-OPS answers a water level request with HTTP 400 for a datum the gauge lacks; the Great Lakes need IGLD.
DATUM_COAST = "MLLW"
DATUM_GREAT_LAKES = "IGLD"

log = logging.getLogger(__name__)


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
    last_attempt: float | None = None
    not_before: float = 0.0  # a Retry-After or backoff window that the refresh key may not shorten


def _is_permanent(failure: Exception) -> bool:
    """A request NOAA answered for good: 400 (the station has no such datum), 404 and 410 (it is gone). Anything else
    says nothing about the station: 401, 403 and 408 mean NOAA is blocking or timing us out, and must back off."""
    return isinstance(failure, HttpError) and failure.status in PERMANENT_STATUSES


def _feed_failure(failures: list[Exception], requests: int) -> Exception | None:
    """The failure to raise when the feed is down, else None. The feed is down when every request failed and at least
    one of them was not a permanent answer (a mix of 400 and 503 is down; all 400s or 404s are just those stations)."""
    if len(failures) < requests:
        return None
    return next((f for f in failures if not _is_permanent(f)), None)


def _by_rank[T](lists: list[list[T]]) -> list[T]:
    """The lists interleaved nearest first (every storm's nearest station, then every storm's second), so a cap on the
    total never gives one storm all the stations."""
    longest = max((len(items) for items in lists), default=0)
    return [items[rank] for rank in range(longest) for items in lists if rank < len(items)]


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
        self._pending: dict[tuple[str, tuple[str | None, datetime | None]], set[str]] = {}
        self._stations_at: dict[str, float] = {}
        self.fetch_counts: dict[str, int] = {}
        self.extra_buoys: set[str] = set()  # stations an open screen wants polled, watchlisted or not
        self.feed_deadline = FEED_DEADLINE
        self._partial: list[Event] = []  # events a feed produced before its deadline cut it off

    # ---- timing -----------------------------------------------------------------------------------------------

    def _base(self, feed: str) -> float:
        return float(getattr(self.config, feed))

    def interval(self, feed: str) -> float:
        """The normal interval in the current mode: tripled while the user is away."""
        return self._base(feed) * (AWAY_FACTOR if self.away else 1.0)

    def set_away(self, away: bool) -> None:
        """Enter or leave away mode. Coming back polls every feed soon, one `RETURN_STAGGER_SECONDS` after the other
        (storms first), never all at once."""
        returning = self.away and not away
        self.away = away
        if returning:
            now = self.clock.monotonic()
            for index, name in enumerate(protocol.FEEDS):
                self._feeds[name].next_at = now + index * RETURN_STAGGER_SECONDS
            if not self.polling:
                self._wake.set()

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
            return max(base, min(self.config.backoff_max, base * 2 ** min(state.failures, MAX_BACKOFF_EXPONENT)))
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

    def active(self, feed: str) -> bool:
        """Whether the feed is being polled now: alerts only during a US threat, stations while a storm exists or the
        watchlist names a station of that kind."""
        return self._enabled(feed)

    def _enabled(self, feed: str) -> bool:
        if feed == protocol.STORMS or feed == protocol.OUTLOOK:
            return True
        if feed == protocol.ALERTS:
            return self.store.us_threat()
        if feed == protocol.BUOYS:
            return bool(self.store.storms or self.store.config.watchlist.ndbc or self.extra_buoys)
        if feed == protocol.TIDES:
            return bool(self.store.storms or self.store.config.watchlist.coops)
        return bool(self.store.storms)

    # ---- running ----------------------------------------------------------------------------------------------

    def refresh(self, *, throttled: bool = False) -> None:
        """Make every feed due now and wake the loop. With `throttled` (the refresh key on live data) a feed attempted
        less than `REFRESH_MIN_GAP` ago becomes due when that gap has passed instead."""
        now = self.clock.monotonic()
        for state in self._feeds.values():
            floor = state.not_before
            if throttled and state.last_attempt is not None:
                floor = max(floor, state.last_attempt + REFRESH_MIN_GAP)
            if throttled and floor > now:
                state.next_at = min(state.next_at, floor)
            else:
                state.next_at = 0.0
        if not self.polling:
            self._wake.set()

    def refresh_feeds(self, *feeds: str) -> None:
        """Make just these feeds due now (the watchlist changed) and wake the loop."""
        for name in feeds:
            self._feeds[name].next_at = 0.0
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
        state.last_attempt = self.clock.monotonic()
        self.source.start_poll(feed)
        self._partial = []
        retry_after: float | None = None
        try:
            async with asyncio.timeout(self.feed_deadline):
                events = await self._fetchers[feed]()
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            error = TimeoutError(f"the {feed} feed took more than {self.feed_deadline:.0f} s")
            events = self._partial
        except Exception as exc:  # a parser bug must not kill the poll loop either
            error = exc
            events = self._partial
        if error is None and isinstance(self.source, ThrottleReporting):
            throttled = self.source.throttle(feed)
            if throttled is not None:  # a 429 or 5xx the cache answered for: old data, but still a failure
                error, retry_after = throttled
        if isinstance(error, RateLimited):
            retry_after = error.retry_after
        state.polls += 1
        if error is None:
            state.failures = 0
            state.last_error = None
            state.last_ok = self.clock.monotonic()
            state.from_cache = self.source.stale(feed)
        else:
            state.failures += 1
            state.last_error = error
        wait = self.delay(feed)
        if retry_after:
            wait = max(wait, min(retry_after, self.config.backoff_max))
        state.next_at = self.clock.monotonic() + wait
        state.not_before = state.next_at if (state.failures or retry_after) else 0.0
        shown: list[Event] = []
        try:
            shown = self.engine.process(events, self.source.now()) if events else []
        except Exception:  # an alert engine bug must not stop the polling either
            log.exception("alert engine failed on the %s feed", feed)
        if shown and self.on_events is not None:
            self._callback(self.on_events, shown)
        result = PollResult(feed, self.freshness(feed), tuple(shown), error)
        if self.on_result is not None:
            self._callback(self.on_result, result)
        return result

    @staticmethod
    def _callback[T](callback: Callable[[T], object], value: T) -> None:
        """Call a listener; one that raises is logged and the polling goes on."""
        try:
            callback(value)
        except Exception:
            log.exception("a poller listener failed")

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
        self._partial = events  # the store has moved on; these events must survive a failure or a deadline below
        failure: Exception | None = None
        for storm_id, state in list(self.store.storms.items()):
            key = storm_key(state.storm)
            if state.fetched_key == key:
                continue
            try:
                events += await self._fetch_products(storm_id, key)
            except Exception as exc:  # one storm's bad product must not cost the others theirs, nor the events above
                if self._attempts.get((storm_id, key), 0) >= PRODUCT_ATTEMPTS:
                    log.warning("giving up on the products of %s", storm_id, exc_info=True)
                    self.store.apply_products(storm_id, now, key=key)  # settled, without them
                else:
                    log.debug("fetching the products of %s failed", storm_id, exc_info=True)
                    failure = failure or exc
        if failure is not None:
            raise failure  # after the other storms: the feed backs off, and poll_feed keeps `_partial`
        if not self.store.us_threat():
            self.store.apply_alerts(AlertsResult())  # the alerts feed is off now; do not keep showing its last answer
        return events

    async def _fetch_products(self, storm_id: str, key: tuple[str | None, datetime | None]) -> list[Event]:
        """The heavy products for a storm whose advisory number or update time just changed."""
        storm = self.store.storms[storm_id].storm
        now = self.source.now()
        attempt = self._attempts.get((storm_id, key), 0) + 1
        self._attempts[(storm_id, key)] = attempt
        pending = self._pending.get((storm_id, key))  # set once the text is in: only failed products remain
        if pending is None:
            pending = {_TEXT, *_PRODUCTS}
        failed: set[str] = set()
        advisories: AdvisorySet | None = None
        if _TEXT in pending:
            advisories = await self.source.advisory(storm, fallback=attempt >= 2)
            wanted = current_adv(storm)
            have = fetched_adv(advisories)
            behind = (wanted is not None and have != wanted) or missing_products(storm, advisories)
            if behind and attempt < FALLBACK_ATTEMPTS:
                # tgftp still serves the previous advisory, or one product of this one. Keep the old products and
                # ask again next poll, the second time through api.weather.gov.
                return []
            if behind:
                failed.add(_TEXT)  # the other products settle below; the text is asked for again
                if have is None:
                    advisories = None
        got: dict[str, object] = {}
        for name in _PRODUCTS:
            if name in pending:
                answered = self.source.cache_answers(protocol.STORMS)
                got[name] = await self._optional(getattr(self.source, name)(storm), name, failed, storm_id)
                if self.source.cache_answers(protocol.STORMS) > answered:  # came from the disk cache: use it, ask again
                    failed.add(name)
        retry = bool(failed) and attempt < PRODUCT_ATTEMPTS  # a failed product is asked for again, within the cap
        if retry:
            self._pending[(storm_id, key)] = failed
        else:
            self._pending.pop((storm_id, key), None)
            self._attempts = {k: v for k, v in self._attempts.items() if k[0] != storm_id or k == (storm_id, key)}
        return self.store.apply_products(
            storm_id,
            now,
            key=None if retry else key,
            advisories=advisories,
            forecast_gis=got.get("forecast_gis"),  # type: ignore[arg-type]
            radii_gis=got.get("radii_gis"),  # type: ignore[arg-type]
            track=got.get("track"),  # type: ignore[arg-type]
            graphics=got.get("graphics"),  # type: ignore[arg-type]
        )

    @staticmethod
    async def _optional[T](call: Awaitable[T], name: str, failed: set[str], storm_id: str) -> T | None:
        """A product that fails does not discard the others; it is noted in `failed` so the storm is tried again."""
        try:
            return await call
        except (FetchError, ParseError) as exc:  # routine: NOAA has not posted it yet, or answered badly
            log.debug("the %s of %s could not be fetched: %s", name, storm_id, exc)
            failed.add(name)
            return None
        except Exception:  # any other failure: the other products still count, and this one is asked for again
            log.warning("the %s of %s could not be fetched", name, storm_id, exc_info=True)
            failed.add(name)
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
        # A full series is fetched only for the stations an open page shows and the ones nearest a storm, at most
        # MAX_BUOY_SERIES in all. A watchlist-only buoy is covered by `latest_obs`, which is one file for every buoy.
        nearby = [[e.station.id.upper() for e in self.store.nearby_buoys(sid)] for sid in self.store.storms]
        extra = sorted(sid.upper() for sid in self.extra_buoys)[:MAX_BUOY_SERIES]
        wanted = list(dict.fromkeys([*extra, *_by_rank(nearby)]))[:MAX_BUOY_SERIES]
        for sid in {sid for ranked in nearby for sid in ranked} - set(wanted):
            self.store.series.pop(sid, None)  # a series nobody refreshes any more must not read as "stopped reporting"
        semaphore = asyncio.Semaphore(MAX_IN_FLIGHT)

        failures: list[Exception] = []

        async def one(index: int, station_id: str) -> None:
            async with semaphore:
                await self._sleep(index % MAX_IN_FLIGHT * STAGGER_SECONDS)
                try:
                    self.store.apply_series(await self.source.ndbc_series(station_id))
                except Exception as exc:  # one station's bad answer must not fail the others
                    log.debug("the series of buoy %s could not be fetched", station_id, exc_info=True)
                    failures.append(exc)

        await asyncio.gather(*(one(i, sid) for i, sid in enumerate(wanted)))
        if wanted and (down := _feed_failure(failures, len(wanted))) is not None:
            raise down  # every request failed: the feed backs off instead of reporting fresh
        if self.source.stale(protocol.BUOYS):
            return []  # answered from the disk cache: old rows say nothing about whether a buoy is still reporting
        return self.store.buoy_events(self.source.now())

    async def _poll_tides(self) -> list[Event]:
        if not self.store.tide_stations or self._station_catalog_due("coops"):
            self.store.apply_tide_stations(await self.source.coops_stations())
            self._stations_at["coops"] = self.clock.monotonic()
        gauges: dict[str, TideStation] = {}
        ranked = [[e.station for e in self.store.nearby_tides(sid)] for sid in self.store.storms]
        for station in _by_rank(ranked):
            if len(gauges) >= MAX_TIDE_GAUGES:
                break
            gauges[station.id] = station
        known = {g.id.upper(): g for g in self.store.tide_stations}
        for station_id in self.store.config.watchlist.coops:
            gauge = known.get(station_id.upper())
            if gauge is not None and len(gauges) < MAX_TIDE_GAUGES:
                gauges.setdefault(gauge.id, gauge)  # the storm's gauges and the watchlist share the same cap
        semaphore = asyncio.Semaphore(MAX_IN_FLIGHT)

        async def one(index: int, station: TideStation) -> None:
            datum = DATUM_GREAT_LAKES if station.great_lakes else DATUM_COAST
            async with semaphore:
                await self._sleep(index % MAX_IN_FLIGHT * STAGGER_SECONDS)
                try:
                    self.store.apply_tide_series(await self.source.coops_series(station, datum))
                except Exception as exc:  # one gauge's bad answer must not fail the others
                    self.store.apply_tide_error(station.id, str(exc) or type(exc).__name__)
                    failures.append(exc)

        failures: list[Exception] = []
        await asyncio.gather(*(one(i, g) for i, g in enumerate(gauges.values())))
        if gauges and (down := _feed_failure(failures, len(gauges))) is not None:
            raise down
        return []

    async def _poll_satellite(self) -> list[Event]:
        failures: list[Exception] = []
        storms = list(self.store.storms.items())
        for storm_id, state in storms:
            try:
                self.store.apply_satellite(storm_id, await self.source.satellite(state.storm))
            except Exception as exc:
                log.debug("the satellite listing of %s could not be fetched", storm_id, exc_info=True)
                failures.append(exc)
        if storms and (down := _feed_failure(failures, len(storms))) is not None:
            raise down
        return []
