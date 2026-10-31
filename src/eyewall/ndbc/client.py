"""Thin NDBC client: build the URL, fetch it through `eyewall.net`, hand the body to the matching parser.

NDBC has no JSON API and asks callers to keep retrievals minimal, so this client does no polling, caching or
concurrency of its own; the poller decides when to ask and passes the validators it saved from last time. Every method
returns a Response: a 304 has no value, and a 404 for a station file (a buoy that stopped reporting, which is normal)
has an empty value rather than raising.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import httpx

from eyewall.models.obs import LatestObservation, ObservationSeries, Parsed, Station, SupplementalReading, WaveSummary
from eyewall.ndbc.historical import parse_historical
from eyewall.ndbc.latest import parse_latest_obs
from eyewall.ndbc.spec import parse_spec
from eyewall.ndbc.stations import parse_stations
from eyewall.ndbc.stdmet import parse_stdmet
from eyewall.ndbc.supl import parse_supl
from eyewall.net import Fetched, fetch_bytes

BASE_URL = "https://www.ndbc.noaa.gov"
STATIONS_URL = f"{BASE_URL}/activestations.xml"
LATEST_OBS_URL = f"{BASE_URL}/data/latest_obs/latest_obs.txt"

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_STATION_ID = re.compile(r"^[A-Za-z0-9]{3,10}$")

SeriesWindow = Literal["5day", "realtime"]


def _check_id(station_id: str) -> str:
    if not _STATION_ID.fullmatch(station_id):
        raise ValueError(f"not an NDBC station id: {station_id!r}")
    return station_id


def five_day_url(station_id: str, suffix: str = "txt") -> str:
    """The 5-day station file (`txt`), its supplemental extremes (`supl`) or its wave summary (`spec`)."""
    return f"{BASE_URL}/data/5day2/{_check_id(station_id).upper()}_5day.{suffix}"


def realtime_url(station_id: str) -> str:
    """The 45-day station file, about 600 KB; fetch it only when someone asks for more than 5 days."""
    return f"{BASE_URL}/data/realtime2/{_check_id(station_id).upper()}.txt"


def yearly_url(station_id: str, year: int) -> str:
    """A whole past year: `data/historical/stdmet/{id}h{yyyy}.txt.gz` with the id in lower case."""
    return f"{BASE_URL}/data/historical/stdmet/{_check_id(station_id).lower()}h{year}.txt.gz"


def monthly_url(station_id: str, month: int, year: int) -> str:
    """A finished month of the current year: `data/stdmet/{Mon}/{id}{M}{yyyy}.txt.gz`, with no zero padding on {M}.

    Observed for 41010 in July and August 2026 (a 404 for January 2026, so older months may be gone). The names for
    October to December have not been observed, because that directory is empty until the month closes, so they raise
    instead of guessing; use the yearly file for a past year.
    """
    if not 1 <= month <= 9:
        raise ValueError("monthly file names are known for months 1 to 9 only (October to December are unverified)")
    return f"{BASE_URL}/data/stdmet/{_MONTHS[month - 1]}/{_check_id(station_id).lower()}{month}{year}.txt.gz"


def previous_month_url(station_id: str, month: int) -> str:
    """The most recently finished month is a plain `data/stdmet/{Mon}/{id}.txt`, with no year in the name."""
    if not 1 <= month <= 12:
        raise ValueError("month must be 1 to 12")
    return f"{BASE_URL}/data/stdmet/{_MONTHS[month - 1]}/{_check_id(station_id).lower()}.txt"


@dataclass(frozen=True, slots=True)
class Response[T]:
    """A fetch and its parse. value is None only for a 304; a 404 carries the caller-supplied empty value."""

    status: int
    value: T | None = None
    etag: str | None = None
    last_modified: str | None = None

    @property
    def not_modified(self) -> bool:
        return self.status == 304

    @property
    def missing(self) -> bool:
        return self.status == 404


class NdbcClient:
    """NDBC fetches over a shared httpx client (build one with `eyewall.net.new_client`); the caller closes it."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def _get[T](
        self,
        url: str,
        parse: Callable[[Fetched], T],
        *,
        missing: Callable[[], T] | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> Response[T]:
        fetched = await fetch_bytes(
            self._client, url, etag=etag, last_modified=last_modified, allow_404=missing is not None
        )
        if fetched.not_modified:
            return Response(304, None, fetched.etag or etag, fetched.last_modified or last_modified)
        if fetched.missing and missing is not None:
            return Response(404, missing())
        return Response(fetched.status, parse(fetched), fetched.etag, fetched.last_modified)

    async def stations(self, *, etag: str | None = None, last_modified: str | None = None) -> Response[Parsed[Station]]:
        """The station catalog. Changes slowly; the poller asks about once a day."""
        return await self._get(STATIONS_URL, lambda f: parse_stations(f.body), etag=etag, last_modified=last_modified)

    async def latest_obs(
        self, *, etag: str | None = None, last_modified: str | None = None
    ) -> Response[Parsed[LatestObservation]]:
        """Every station's newest observation in one request. The CDN holds it for 10 minutes."""
        return await self._get(
            LATEST_OBS_URL, lambda f: parse_latest_obs(f.text()), etag=etag, last_modified=last_modified
        )

    async def series(
        self,
        station_id: str,
        *,
        window: SeriesWindow = "5day",
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> Response[ObservationSeries]:
        """A station's observations, newest first. A 404 is a station that is not reporting: an empty series."""
        url = five_day_url(station_id) if window == "5day" else realtime_url(station_id)
        return await self._get(
            url,
            lambda f: parse_stdmet(f.text(), station_id),
            missing=lambda: ObservationSeries(station_id.upper()),
            etag=etag,
            last_modified=last_modified,
        )

    async def supplemental(
        self, station_id: str, *, etag: str | None = None, last_modified: str | None = None
    ) -> Response[Parsed[SupplementalReading]]:
        """Interval minimum pressure and peak wind for the last 5 days; a 404 is an empty result."""
        return await self._get(
            five_day_url(station_id, "supl"),
            lambda f: parse_supl(f.text()),
            missing=Parsed,
            etag=etag,
            last_modified=last_modified,
        )

    async def waves(
        self, station_id: str, *, etag: str | None = None, last_modified: str | None = None
    ) -> Response[Parsed[WaveSummary]]:
        """The wave summary for the last 5 days; a 404 (no wave sensor, or dark) is an empty result."""
        return await self._get(
            five_day_url(station_id, "spec"),
            lambda f: parse_spec(f.text()),
            missing=Parsed,
            etag=etag,
            last_modified=last_modified,
        )

    async def historical_year(self, station_id: str, year: int) -> Response[ObservationSeries]:
        """A whole past year for replay recording. A 404 is an empty series."""
        return await self._get(
            yearly_url(station_id, year),
            lambda f: parse_historical(f.body, station_id),
            missing=lambda: ObservationSeries(station_id.upper()),
        )

    async def historical_month(self, station_id: str, month: int, year: int) -> Response[ObservationSeries]:
        """A finished month of the current year for replay recording. A 404 is an empty series."""
        return await self._get(
            monthly_url(station_id, month, year),
            lambda f: parse_historical(f.body, station_id),
            missing=lambda: ObservationSeries(station_id.upper()),
        )
