"""The live data source: the NHC, NDBC and CO-OPS clients over one cached HTTP client.

`LiveSource` builds a single `httpx.AsyncClient` whose transport is `CachingTransport`, so every feed is conditional
(ETag / Last-Modified from the disk cache) and an offline launch is answered from the last responses, with the feed
marked stale. The poller decides when to call; this module only fetches and parses.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from pathlib import Path

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
from eyewall.models.outlook import Outlook
from eyewall.models.storm import CurrentStorms, Storm
from eyewall.models.track import BestTrack
from eyewall.models.watches import AlertsResult
from eyewall.models.wind import WindRadiiGis
from eyewall.ndbc.client import NdbcClient
from eyewall.net import FetchError, new_client
from eyewall.providers.base import ParseError
from eyewall.providers.nhc.client import NhcClient
from eyewall.render.images import fetch_image
from eyewall.sources import protocol
from eyewall.sources.cache import Cache, CachingTransport, watch_stale

CACHE_MAX_AGE = timedelta(days=7)
INVEST_MAX_AGE = timedelta(hours=48)
MAX_INVESTS = 6
SATELLITE_PRODUCT = "GEOCOLOR"
PREDICTION_DAYS_BEHIND = 2  # predictions start at midnight UTC this many days back, so the URL (and its cache entry)
PREDICTION_HOURS = 120  # changes once a day instead of every poll, and the range reaches into the next day or two


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
        self.cache.prune(CACHE_MAX_AGE, self._clock.now())
        self._http = new_client(transport=CachingTransport(self.cache, transport))
        self.nhc = NhcClient(self._http)
        self.ndbc = NdbcClient(self._http)
        self.coops = CoopsClient(self._http)
        self._stale: dict[str, bool] = {}
        self._predictions: dict[tuple[str, str, str], Parsed] = {}  # (gauge, datum, UTC date) -> the day's answer

    async def aclose(self) -> None:
        await self._http.aclose()

    def now(self) -> datetime:
        return self._clock.now()

    def stale(self, feed: str) -> bool:
        return self._stale.get(feed, False)

    def start_poll(self, feed: str) -> None:
        self._stale[feed] = False

    @contextlib.asynccontextmanager
    async def _feed(self, feed: str) -> AsyncIterator[None]:
        """Record whether any request made for this feed was answered from the cache instead of the network."""
        with watch_stale() as marker:
            try:
                yield
            finally:
                self._stale[feed] = self._stale.get(feed, False) or marker.hit  # any request in the poll counts

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
                listed = (await self.nhc.fetch_floater_storms()).value or ()
                if storm.id.upper() not in listed:
                    return ()
                product = (await self.nhc.fetch_floater_product(storm.id, SATELLITE_PRODUCT)).value
            except ParseError:
                return ()
            return () if product is None else (product,)

    async def satellite_product(self, storm: Storm, product: str) -> FloaterProduct | None:
        """One more NESDIS product for a storm, fetched when the gallery opens; None when NESDIS does not list it."""
        async with self._feed(protocol.SATELLITE):
            try:
                listed = (await self.nhc.fetch_floater_storms()).value or ()
                if storm.id.upper() not in listed:
                    return None
                return (await self.nhc.fetch_floater_product(storm.id, product)).value
            except ParseError:
                return None

    async def image(self, url: str) -> bytes:
        async with self._feed(protocol.SATELLITE if "nesdis" in url else protocol.STORMS):
            return await fetch_image(self._http, url)

    # ---- outlook and alerts -----------------------------------------------------------------------------------

    async def outlook(self) -> Outlook:
        async with self._feed(protocol.OUTLOOK):
            texts = await self.nhc.outlook_text()
            gis = await self.nhc.outlook_gis()
            return Outlook(texts, gis, await self._invests())

    async def _invests(self) -> tuple[BestTrack, ...]:
        """Invest b-decks touched in the last two days whose newest fix is just as recent."""
        try:
            listing = (await self.nhc.fetch_bdeck_index()).value or ()
        except (FetchError, ParseError):
            return ()
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
            return response.value.items if response.value else ()

    async def ndbc_latest(self) -> tuple[LatestObservation, ...]:
        async with self._feed(protocol.BUOYS):
            response = await self.ndbc.latest_obs()
            return response.value.items if response.value else ()

    async def ndbc_series(self, station_id: str) -> ObservationSeries:
        async with self._feed(protocol.BUOYS):
            response = await self.ndbc.series(station_id)
            return response.value or ObservationSeries(station_id.upper())

    async def ndbc_supplemental(self, station_id: str) -> Parsed[SupplementalReading]:
        async with self._feed(protocol.BUOYS):
            response = await self.ndbc.supplemental(station_id)
            return response.value or Parsed()

    async def coops_stations(self) -> tuple[TideStation, ...]:
        async with self._feed(protocol.TIDES):
            return await self.coops.all_stations()

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
        except FetchError as exc:
            found = Parsed(message=str(exc))  # a subordinate station answers with an error; do not ask again today
        self._predictions = {k: v for k, v in self._predictions.items() if k[2] == key[2]}
        self._predictions[key] = found
        return found
