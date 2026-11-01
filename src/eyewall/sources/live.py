"""The live data source: the NHC, NDBC and CO-OPS clients over one cached HTTP client.

`LiveSource` builds a single `httpx.AsyncClient` whose transport is `CachingTransport`, so every feed is conditional
(ETag / Last-Modified from the disk cache) and an offline launch is answered from the last responses, with the feed
marked stale. The poller decides when to call; this module only fetches and parses.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from eyewall.clock import Clock, SystemClock
from eyewall.coops.client import CoopsClient
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
from eyewall.models.outlook import Outlook, OutlookGis
from eyewall.models.storm import Basin, CurrentStorms, Storm
from eyewall.models.track import BestTrack
from eyewall.models.watches import AlertsResult
from eyewall.models.wind import WindRadiiGis
from eyewall.ndbc.client import NdbcClient
from eyewall.net import FetchError, HttpError, RateLimited, new_client
from eyewall.providers.base import ParseError
from eyewall.providers.nhc.client import NhcClient
from eyewall.render.images import fetch_image
from eyewall.sources import protocol
from eyewall.sources.cache import Cache, CachingTransport, watch_stale

CACHE_MAX_AGE = timedelta(days=7)
INVEST_MAX_AGE = timedelta(hours=48)
OUTLOOK_KEEP = timedelta(hours=48)  # how long a part of the outlook that now fails is shown from its last good answer
MAX_INVESTS = 6
SATELLITE_PRODUCT = "GEOCOLOR"
FLOATER_LISTING_TTL = 60.0  # seconds a NESDIS listing of storms is reused, so one satellite poll asks for it once
PREDICTION_DAYS_BEHIND = 2  # predictions start at midnight UTC this many days back, so the URL (and its cache entry)
PREDICTION_HOURS = 120  # changes once a day instead of every poll, and the range reaches into the next day or two


def _items[T](parsed: Parsed[T] | None, what: str) -> tuple[T, ...]:
    """The records of a parsed listing. A body that held none and came with a message (an HTML page, bad XML) is not
    "no records": it raises, so the store keeps its last good listing and the feed shows the failure."""
    if parsed is None:
        return ()
    if not parsed.items and parsed.message:
        raise ParseError(f"{what}: {parsed.message}")
    return parsed.items


def _is_nesdis(url: str) -> bool:
    """True when the address's parsed host is nesdis.noaa.gov or one of its subdomains."""
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return False
    return host == "nesdis.noaa.gov" or host.endswith(".nesdis.noaa.gov")


class LiveSource:
    """`DataSource` over the real services."""

    name = "live"

    def __init__(
        self,
        *,
        cache_dir: Path | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._clock: Clock = clock or SystemClock()
        self.cache = Cache(cache_dir)
        self._pruned: asyncio.Task[int] | None = None  # the first request starts it; every request waits for it
        self._http = new_client(transport=CachingTransport(self.cache, transport))
        self.nhc = NhcClient(self._http)
        self.ndbc = NdbcClient(self._http)
        self.coops = CoopsClient(self._http)
        self._stale: dict[str, bool] = {}
        self._answers: dict[str, int] = {}
        self._outlook_kept: dict[
            str, tuple[Any, datetime]
        ] = {}  # the last good part of the outlook, by part, for a part that fails
        self._throttled: dict[str, tuple[FetchError, float | None]] = {}
        self._predictions: dict[tuple[str, str, str], Parsed] = {}  # (gauge, datum, UTC date) -> the day's answer
        self._shared: dict[str, tuple[asyncio.Task[Any], float]] = {}  # request key -> (its task, when it started)

    async def aclose(self) -> None:
        await self._http.aclose()

    def now(self) -> datetime:
        return self._clock.now()

    def stale(self, feed: str) -> bool:
        return self._stale.get(feed, False)

    def _prune(self) -> int:
        try:
            return self.cache.prune(CACHE_MAX_AGE, self._clock.now())
        except Exception:  # the cache is an optimization; a broken directory is not a reason to fail a request
            return 0

    def cache_answers(self, feed: str) -> int:
        return self._answers.get(feed, 0)

    def start_poll(self, feed: str) -> None:
        self._stale[feed] = False
        self._answers[feed] = 0
        self._throttled.pop(feed, None)

    def throttle(self, feed: str) -> tuple[FetchError, float | None] | None:
        """The 429 or 5xx the cache covered for in this feed's last poll, and the server's Retry-After."""
        return self._throttled.get(feed)

    @contextlib.asynccontextmanager
    async def _feed(self, feed: str, *, report: bool = True) -> AsyncIterator[None]:
        """Record whether any request made for this feed was answered from the cache instead of the network. A fetch
        a screen asks for on its own (an image, a gallery product) passes `report=False`: the poll in flight reads the
        feed's state when it ends, and a cached picture must not make that poll look stale or failed."""
        if self._pruned is None:  # old cache entries go on a worker thread, before the first request reads any
            self._pruned = asyncio.ensure_future(asyncio.to_thread(self._prune))
        await asyncio.shield(self._pruned)
        with watch_stale() as marker:
            try:
                yield
            finally:
                if report:
                    self._stale[feed] = self._stale.get(feed, False) or marker.hit  # any request in the poll counts
                    self._answers[feed] = self._answers.get(feed, 0) + len(marker.urls)
                    if marker.failure is not None and feed not in self._throttled:
                        self._throttled[feed] = (marker.failure, marker.retry_after)

    async def _shared_call[T](self, key: str, call: Callable[[], Awaitable[T]], reuse: float = 0.0) -> T:
        """One request for every caller that asks for `key` while it is in flight, and for `reuse` seconds after it
        started if it succeeded. A failure is never kept. Callers are shielded, so a cancelled one does not cancel the
        others."""
        now = self._clock.monotonic()
        kept = self._shared.get(key)
        if kept is not None:
            task, started = kept
            if not task.done() or (not task.cancelled() and task.exception() is None and now - started < reuse):
                return await asyncio.shield(task)
        task = asyncio.ensure_future(call())
        task.add_done_callback(
            lambda t: t.cancelled() or t.exception()
        )  # retrieved here; each caller re-raises its own
        self._shared[key] = (task, now)
        return await asyncio.shield(task)

    async def _floater_storms(self) -> tuple[str, ...]:
        """The storms NESDIS lists, asked for once across the panels and storms that want it."""
        response = await self._shared_call("floater-storms", self.nhc.fetch_floater_storms, FLOATER_LISTING_TTL)
        return response.value or ()

    async def _floater_product(self, storm_id: str, product: str) -> FloaterProduct | None:
        found = await self._shared_call(
            f"floater:{storm_id}:{product}", lambda: self.nhc.fetch_floater_product(storm_id, product)
        )
        return found.value

    # ---- storms -----------------------------------------------------------------------------------------------

    async def storms(self) -> CurrentStorms:
        async with self._feed(protocol.STORMS):
            return await self.nhc.storms()

    async def advisory(self, storm: Storm, *, fallback: bool = False) -> AdvisorySet:
        async with self._feed(protocol.STORMS):
            return await self.nhc.advisory(storm, fallback=fallback)

    async def forecast_gis(self, storm: Storm) -> ForecastGis | None:
        async with self._feed(protocol.STORMS):
            return await self.nhc.forecast_gis(storm)

    async def radii_gis(self, storm: Storm) -> WindRadiiGis | None:
        async with self._feed(protocol.STORMS):
            return await self.nhc.radii_gis(storm)

    async def track(self, storm: Storm) -> BestTrack | None:
        async with self._feed(protocol.STORMS):
            return await self.nhc.track(storm)

    async def graphics(self, storm: Storm) -> tuple[GraphicLink, ...]:
        async with self._feed(protocol.STORMS):
            return await self.nhc.graphics(storm)

    async def satellite(self, storm: Storm) -> tuple[FloaterProduct, ...]:
        """The newest GEOCOLOR still and loop. The product listing is large, so only a storm NESDIS lists is asked."""
        async with self._feed(protocol.SATELLITE):
            try:
                if storm.id.upper() not in await self._floater_storms():
                    return ()
                product = await self._floater_product(storm.id, SATELLITE_PRODUCT)
            except ParseError:
                return ()
            return () if product is None else (product,)

    async def satellite_product(self, storm: Storm, product: str) -> FloaterProduct | None:
        """One more NESDIS product for a storm, fetched when the gallery opens; None when NESDIS does not list it."""
        async with self._feed(protocol.SATELLITE, report=False):
            try:
                if storm.id.upper() not in await self._floater_storms():
                    return None
                return await self._floater_product(storm.id, product)
            except ParseError:
                return None

    async def image(self, url: str) -> bytes:
        async with self._feed(protocol.SATELLITE if _is_nesdis(url) else protocol.STORMS, report=False):
            return await fetch_image(self._http, url)

    # ---- outlook and alerts -----------------------------------------------------------------------------------

    async def outlook(self) -> Outlook:
        """The outlook text of each basin, the areas and the invests. A part that fails keeps its last good answer (for
        at most OUTLOOK_KEEP, and invests only while their newest fix is within INVEST_MAX_AGE) and the failure is
        reported to the poller, which backs off and shows it. A part that has never succeeded has no answer, and
        "unknown" must not pass for "none": the failure is raised and the store keeps what it had (nothing, on the first
        poll, so the screen keeps waiting and the first real answer is the event baseline)."""
        failures: list[Exception] = []
        unknown: list[Exception] = []

        async def part[T](name: str, call: Callable[[], Awaitable[T]], default: T) -> T:
            try:
                value = await call()
            except (FetchError, ParseError) as exc:
                failures.append(exc)
                kept = self._outlook_kept.get(name)
                if kept is None or self.now() - kept[1] > OUTLOOK_KEEP:
                    self._outlook_kept.pop(name, None)
                    unknown.append(exc)
                    return default
                return kept[0]
            self._outlook_kept[name] = (value, self.now())
            return value

        try:
            async with self._feed(protocol.OUTLOOK):
                texts = [
                    text
                    for basin in (Basin.AL, Basin.EP, Basin.CP)
                    if (text := await part(basin.value, lambda b=basin: self.nhc.outlook_basin(b), None)) is not None  # type: ignore[misc]
                ]
                gis = await part("gis", self.nhc.outlook_gis, OutlookGis(None))
                no_invests: tuple[BestTrack, ...] = ()
                invests = await part("invests", self._invests, no_invests)
                if unknown:
                    raise unknown[0]
                now = self.now()
                invests = tuple(t for t in invests if t.latest is not None and now - t.latest.time <= INVEST_MAX_AGE)
                return Outlook(tuple(texts), gis, invests)
        finally:
            if failures:
                self._note_failures(protocol.OUTLOOK, failures)

    def _note_failures(self, feed: str, failures: list[Exception]) -> None:
        """Report the failures of the parts of a feed to the poller: the first as the error (a 429 over the rest), and
        the longest Retry-After of any of them, whether it came from a part's own answer or from a cached copy."""
        waits = [f.retry_after for f in failures if isinstance(f, RateLimited) and f.retry_after is not None]
        held = self._throttled.get(feed)
        if held is not None and held[1] is not None:
            waits.append(held[1])
        if held is not None:
            error = held[0]
        else:
            first = next((f for f in failures if isinstance(f, RateLimited)), failures[0])
            error = first if isinstance(first, FetchError) else FetchError(feed, f"{type(first).__name__}: {first}")
        self._throttled[feed] = (error, max(waits, default=None))

    async def _invests(self) -> tuple[BestTrack, ...]:
        """Invest b-decks touched in the last two days whose newest fix is just as recent."""
        listing = (await self.nhc.fetch_bdeck_index()).value or ()  # a failure fails the feed
        now = self.now()
        recent = [f for f in listing if f.is_invest and f.modified is not None and now - f.modified <= INVEST_MAX_AGE]
        recent.sort(key=lambda f: f.modified or now, reverse=True)
        found: list[BestTrack] = []
        for entry in recent[:MAX_INVESTS]:
            try:
                track = (await self.nhc.fetch_bdeck(entry.storm_id)).value
            except (FetchError, ParseError, ValueError):
                continue
            latest = track.latest if track else None
            if track is not None and latest is not None and now - latest.time <= INVEST_MAX_AGE:
                found.append(track)
        return tuple(found)

    async def alerts(self) -> AlertsResult:
        async with self._feed(protocol.ALERTS):
            return (await self.nhc.fetch_alerts()).value or AlertsResult()

    # ---- buoys and tide gauges --------------------------------------------------------------------------------

    async def ndbc_stations(self) -> tuple[Station, ...]:
        async with self._feed(protocol.BUOYS):
            response = await self.ndbc.stations()
            if response.value is not None and not response.value.items:  # a catalog without stations is not one
                raise ParseError(f"the NDBC station catalog: {response.value.message or 'no stations'}")
            return _items(response.value, "the NDBC station catalog")

    async def ndbc_latest(self) -> tuple[LatestObservation, ...]:
        async with self._feed(protocol.BUOYS):
            response = await self.ndbc.latest_obs()
            return _items(response.value, "the NDBC latest observations")

    async def ndbc_series(self, station_id: str) -> ObservationSeries:
        async with self._feed(protocol.BUOYS):
            response = await self.ndbc.series(station_id)
            series = response.value or ObservationSeries(station_id.upper())
            if not series.observations and series.skipped:  # an HTML page or a table of unreadable rows: not data
                raise ParseError(f"the NDBC file of {station_id} has no readable rows")
            return series

    async def ndbc_supplemental(self, station_id: str) -> Parsed[SupplementalReading]:
        async with self._feed(protocol.BUOYS, report=False):
            response = await self.ndbc.supplemental(station_id)
            return response.value or Parsed()

    async def coops_stations(self) -> tuple[TideStation, ...]:
        async with self._feed(protocol.TIDES):
            stations = await self.coops.all_stations()
            if not stations:  # the listings answered with something that is not a station list
                raise ParseError("the CO-OPS station listings have no stations")
            return stations

    async def coops_series(self, station: TideStation, datum: str) -> TideSeries:
        """Water level (an HTTP error here, such as a 400 for the wrong datum, propagates) plus wind and pressure.

        Wind and pressure are asked only of gauges the `met` listing names, and a failure there leaves that product
        empty with the reason rather than discarding the water level.
        """
        async with self._feed(protocol.TIDES):
            level = await self.coops.water_level(station.id, datum=datum, date="recent")
            wind: Parsed = Parsed()
            pressure: Parsed = Parsed()
            if "met" in station.products:
                try:
                    wind = await self.coops.wind(station.id, date="recent")
                except FetchError as exc:
                    wind = Parsed(message=str(exc))
                try:
                    pressure = await self.coops.air_pressure(station.id, date="recent")
                except FetchError as exc:
                    pressure = Parsed(message=str(exc))
            predictions = await self._predictions_for(station, datum)
            return TideSeries(station.id, datum, level, wind, pressure, predictions)

    async def _predictions_for(self, station: TideStation, datum: str) -> Parsed:
        """The gauge's 6-minute predictions, asked for once per UTC day and remembered, empty answers included: the
        window starts at a UTC midnight, so a second request the same day would return the same thing. Great Lakes
        gauges (IGLD) have no predictions, so none is asked for."""
        if station.great_lakes:
            return Parsed(message="no tide predictions for the Great Lakes")
        begin = (self._clock.now() - timedelta(days=PREDICTION_DAYS_BEHIND)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        key = (station.id, datum, begin.date().isoformat())
        if key in self._predictions:
            return self._predictions[key]
        try:
            found: Parsed = await self.coops.predictions(
                station.id, datum=datum, interval=None, begin=begin, hours=PREDICTION_HOURS
            )
        except HttpError as exc:
            found = Parsed(message=str(exc))
            if not 400 <= exc.status < 500 or isinstance(exc, RateLimited):
                return found  # a 5xx or 429 passes: ask again next poll
            # a subordinate station answers with a 4xx; the answer will not change today, so it is remembered
        except FetchError as exc:
            return Parsed(message=str(exc))  # the network failed (timeout, no connection): ask again next poll
        self._predictions = {k: v for k, v in self._predictions.items() if k[2] == key[2]}
        self._predictions[key] = found
        return found
