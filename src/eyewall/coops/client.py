"""Thin CO-OPS client: one request per gauge per call, parsed into models.

CO-OPS throttles heavy users, so each method makes exactly one request and the poller decides how often to call (every
6 minutes at most, the data's own cadence). Every request carries `application=eyewall` as well as the eyewall
User-Agent. A 200 with an error object (a product the station does not offer) comes back as an empty result with a
message; an HTTP error such as a 400 for a datum the station lacks raises `eyewall.net.HttpError`.
"""

from __future__ import annotations

from datetime import datetime

import httpx

from eyewall.coops.data import (
    DATAGETTER_URL,
    DEFAULT_DATUM,
    Interval,
    Latest,
    datagetter_params,
    parse_air_pressure,
    parse_predictions,
    parse_water_level,
    parse_wind,
)
from eyewall.coops.stations import LISTING_TYPES, MET, WATER_LEVEL, merge_tide_stations, parse_tide_stations
from eyewall.models.obs import Parsed, Prediction, TidePressure, TideStation, TideWind, WaterLevelReading
from eyewall.net import fetch_bytes

STATIONS_URL = "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json"


class CoopsClient:
    """CO-OPS fetches over a shared httpx client (build one with `eyewall.net.new_client`); the caller closes it."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def stations(self, product: str = WATER_LEVEL) -> Parsed[TideStation]:
        """One station listing: "water_level" for the tide gauges or "met" for wind and pressure stations."""
        if product not in LISTING_TYPES:
            raise ValueError(f"unknown station listing {product!r}; use one of {sorted(LISTING_TYPES)}")
        fetched = await fetch_bytes(self._client, STATIONS_URL, params={"type": LISTING_TYPES[product]})
        return parse_tide_stations(fetched.body, product)

    async def all_stations(self) -> tuple[TideStation, ...]:
        """Both listings merged: each station once, with every product it offers. Two requests; cache for a day."""
        return merge_tide_stations([await self.stations(WATER_LEVEL), await self.stations(MET)])

    async def _get(self, params: dict[str, str]) -> bytes:
        return (await fetch_bytes(self._client, DATAGETTER_URL, params=params)).body

    async def water_level(
        self,
        station: str,
        *,
        datum: str = DEFAULT_DATUM,
        date: Latest | None = None,
        begin: datetime | None = None,
        end: datetime | None = None,
        hours: int | None = None,
    ) -> Parsed[WaterLevelReading]:
        """Observed water level in feet above the datum (MLLW unless told otherwise), newest first."""
        params = datagetter_params("water_level", station, datum=datum, date=date, begin=begin, end=end, hours=hours)
        return parse_water_level(await self._get(params))

    async def predictions(
        self,
        station: str,
        *,
        datum: str = DEFAULT_DATUM,
        interval: Interval | None = "hilo",
        date: Latest | None = None,
        begin: datetime | None = None,
        end: datetime | None = None,
        hours: int | None = None,
    ) -> Parsed[Prediction]:
        """Predicted tides in feet, soonest first: high and low tides by default, or 6-minute values with interval=None.

        With no window given this asks for today's predictions. Pass begin and hours to look ahead from a given moment.
        """
        if date is None and begin is None and end is None and hours is None:
            date = "today"
        params = datagetter_params(
            "predictions", station, datum=datum, interval=interval, date=date, begin=begin, end=end, hours=hours
        )
        return parse_predictions(await self._get(params))

    async def air_pressure(
        self,
        station: str,
        *,
        date: Latest | None = None,
        begin: datetime | None = None,
        end: datetime | None = None,
        hours: int | None = None,
    ) -> Parsed[TidePressure]:
        """Air pressure in millibars, newest first. Only gauges with a barometer have it."""
        params = datagetter_params("air_pressure", station, date=date, begin=begin, end=end, hours=hours)
        return parse_air_pressure(await self._get(params))

    async def wind(
        self,
        station: str,
        *,
        date: Latest | None = None,
        begin: datetime | None = None,
        end: datetime | None = None,
        hours: int | None = None,
    ) -> Parsed[TideWind]:
        """Wind in knots, newest first. Only gauges with an anemometer have it."""
        params = datagetter_params("wind", station, date=date, begin=begin, end=end, hours=hours)
        return parse_wind(await self._get(params))
