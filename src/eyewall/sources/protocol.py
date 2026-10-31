"""The one interface between the app and its data: `DataSource`.

Two implementations exist, `LiveSource` (the real NOAA services through a disk cache) and `ReplaySource` (a recorded
bundle on a virtual clock). The store, the poller and the UI cannot tell them apart.

Every method is an async fetch of one feed's current content. A fetch that fails raises `eyewall.net.FetchError`; a
product that does not exist (no GIS zip yet, a buoy that is dark) is an empty value, not an error. Sources do not
decide when to fetch: the poller does, and calls the heavy ones (`advisory`, the GIS zips, `graphics`) only when a
storm's advisory number changes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

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

# The feed names shared by the source, the poller and the status bar.
STORMS = "storms"
OUTLOOK = "outlook"
ALERTS = "alerts"
BUOYS = "buoys"
TIDES = "tides"
SATELLITE = "satellite"
FEEDS = (STORMS, OUTLOOK, ALERTS, BUOYS, TIDES, SATELLITE)


class DataSource(Protocol):
    name: str

    def now(self) -> datetime:
        """The source's current moment: the system clock for live data, the virtual clock for a replay."""
        ...

    def stale(self, feed: str) -> bool:
        """True when the last fetch of this feed was answered from the disk cache because the network failed."""
        ...

    def start_poll(self, feed: str) -> None:
        """Called before each poll of a feed, so `stale` reports only that poll's requests."""
        ...

    async def storms(self) -> CurrentStorms: ...

    async def advisory(self, storm: Storm, *, fallback: bool = False) -> AdvisorySet:
        """The four text products. `fallback` allows the slower api.weather.gov copy when tgftp has nothing current."""
        ...

    async def forecast_gis(self, storm: Storm) -> ForecastGis | None: ...

    async def radii_gis(self, storm: Storm) -> WindRadiiGis | None: ...

    async def track(self, storm: Storm) -> BestTrack | None: ...

    async def graphics(self, storm: Storm) -> tuple[GraphicLink, ...]: ...

    async def satellite(self, storm: Storm) -> tuple[FloaterProduct, ...]: ...

    async def outlook(self) -> Outlook: ...

    async def alerts(self) -> AlertsResult: ...

    async def ndbc_stations(self) -> tuple[Station, ...]: ...

    async def ndbc_latest(self) -> tuple[LatestObservation, ...]: ...

    async def ndbc_series(self, station_id: str) -> ObservationSeries: ...

    async def ndbc_supplemental(self, station_id: str) -> Parsed[SupplementalReading]:
        """The `.supl` file: lowest pressure and peak wind per interval. Fetched on demand by the buoy detail."""
        ...

    async def coops_stations(self) -> tuple[TideStation, ...]: ...

    async def coops_series(self, station: TideStation, datum: str) -> TideSeries:
        """Water level at the datum and the predicted tide, plus wind and pressure when the gauge offers them."""
        ...
