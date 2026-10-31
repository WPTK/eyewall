"""A thin client for the NHC, CPHC and NWS feeds: fetch with `eyewall.net`, hand the bytes to a parser.

No caching, no polling and no scheduling live here; M4 adds those. Two layers:

- `fetch_*` methods take optional `etag`/`last_modified` validators and return a `Response`: the parsed value, or None
  for a 304 or a 404, together with the `Fetched` so a cache can store the validators and the raw body.
- Provider methods (`storms`, `advisory`, `forecast_gis`, `track`, `outlook_text`, `outlook_gis`, `graphics`) implement
  `StormProvider`. They return parsed values, swallow a failed or unparsable product as None (or an empty tuple) and
  apply the staleness rule: text is only used when its storm id and advisory number match the storm's listing.

Heavy things are explicit: a GIS zip is 40 to 600 KB and a NESDIS product listing for a long storm is over a megabyte,
so callers fetch them when a storm's advisory number changes (zips) or when the user looks (listings), not on every
poll.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

import httpx

from eyewall.models.advisory import AdvisorySet, ApiProduct
from eyewall.models.forecast import ForecastGis
from eyewall.models.graphics import FloaterProduct, GraphicLink
from eyewall.models.outlook import OutlookGis, OutlookText
from eyewall.models.storm import AdvNum, Basin, CurrentStorms, ProductRef, Storm
from eyewall.models.track import BDeckFile, BestTrack, BestTrackGis
from eyewall.models.watches import AlertsResult
from eyewall.models.wind import WindRadiiGis
from eyewall.net import Fetched, FetchError, fetch_bytes
from eyewall.providers.base import ParseError
from eyewall.providers.nhc import ids
from eyewall.providers.nhc.alerts import parse_alerts, parse_product, parse_product_list
from eyewall.providers.nhc.atcf import parse_bdeck, parse_btk_index
from eyewall.providers.nhc.current import parse_current_storms
from eyewall.providers.nhc.gis import parse_best_track_zip, parse_forecast_zip, parse_radii_zip
from eyewall.providers.nhc.graphics import (
    parse_floater_listing,
    parse_floater_products,
    parse_floater_storms,
    parse_graphics_page,
)
from eyewall.providers.nhc.ids import Bin, ProductKind
from eyewall.providers.nhc.tcm import parse_tcm
from eyewall.providers.nhc.text import parse_pws, parse_tcd, parse_tcp, parse_two
from eyewall.providers.nhc.two import parse_gtwo_zip


class _Identified(Protocol):
    """What every parsed storm text product has: the storm id and advisory number it claims to be."""

    @property
    def storm_id(self) -> str | None: ...

    @property
    def adv_num(self) -> AdvNum | None: ...


@dataclass(frozen=True, slots=True)
class Response[T]:
    """A parsed value and the raw fetch it came from. `value` is None for a 304 (unchanged) or a 404 (missing)."""

    value: T | None
    fetched: Fetched
    source: str = ""

    @property
    def not_modified(self) -> bool:
        return self.fetched.not_modified

    @property
    def missing(self) -> bool:
        return self.fetched.missing


class NhcClient:
    """Fetches NHC, CPHC and NWS products over a shared `httpx.AsyncClient` from `eyewall.net.new_client`."""

    name = "NHC"

    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        retries: int = 2,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._http = http
        self._retries = retries
        self._sleep = sleep

    # ---- plumbing -------------------------------------------------------------------------------------------------

    async def _fetch(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
        allow_404: bool = True,
    ) -> Fetched:
        return await fetch_bytes(
            self._http,
            url,
            params=params,
            etag=etag,
            last_modified=last_modified,
            allow_404=allow_404,
            retries=self._retries,
            sleep=self._sleep,
        )

    async def _get[T](
        self,
        url: str,
        parse: Callable[[bytes], T],
        *,
        params: dict[str, str] | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
        allow_404: bool = True,
    ) -> Response[T]:
        fetched = await self._fetch(url, params=params, etag=etag, last_modified=last_modified, allow_404=allow_404)
        if fetched.not_modified or fetched.missing:
            return Response(None, fetched)
        return Response(parse(fetched.body), fetched)

    # ---- fetch layer ----------------------------------------------------------------------------------------------

    async def fetch_current_storms(
        self, *, etag: str | None = None, last_modified: str | None = None
    ) -> Response[CurrentStorms]:
        return await self._get(
            ids.CURRENT_STORMS_URL, parse_current_storms, etag=etag, last_modified=last_modified, allow_404=False
        )

    async def fetch_text(
        self,
        kind: ProductKind,
        bin_: Bin,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
        fallback: bool = True,
    ) -> Response[str]:
        """The raw text of a storm product from tgftp, or api.weather.gov when tgftp fails and `fallback` is set."""
        try:
            response = await self._get(
                ids.tgftp_url(kind, bin_),
                lambda body: body.decode("utf-8", errors="replace"),
                etag=etag,
                last_modified=last_modified,
            )
        except FetchError:
            if not fallback:
                raise
            return await self.fetch_api_text(kind, bin_.name)
        if response.not_modified or (response.value and response.value.strip()):
            return Response(response.value, response.fetched, "tgftp")
        return await self.fetch_api_text(kind, bin_.name) if fallback else response

    async def fetch_outlook_text(
        self,
        basin: Basin,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
        fallback: bool = True,
    ) -> Response[str]:
        try:
            response = await self._get(
                ids.outlook_url(basin),
                lambda body: body.decode("utf-8", errors="replace"),
                etag=etag,
                last_modified=last_modified,
            )
        except FetchError:
            if not fallback:
                raise
            return await self.fetch_api_text(ProductKind.TWO, ids.outlook_location(basin))
        if response.not_modified or (response.value and response.value.strip()):
            return Response(response.value, response.fetched, "tgftp")
        return await self.fetch_api_text(ProductKind.TWO, ids.outlook_location(basin)) if fallback else response

    async def fetch_api_text(
        self, kind: ProductKind, location: str, *, etag: str | None = None, last_modified: str | None = None
    ) -> Response[str]:
        """The newest api.weather.gov product of a type at a bin or basin: a list request, then the product.

        The validators apply to the list request, which is the one repeated on every poll; a 304 there means the newest
        product is the one already held and the product itself is not fetched.
        """
        listing = await self._get(
            ids.api_products_url(kind, location), parse_product_list, etag=etag, last_modified=last_modified
        )
        if not listing.value:
            return Response(None, listing.fetched, "api")
        product = await self.fetch_api_product(listing.value[0].id)
        text = product.value.text if product.value else None
        return Response(text, product.fetched, "api")

    async def fetch_api_product(self, product_id: str) -> Response[ApiProduct]:
        return await self._get(ids.api_product_url(product_id), parse_product)

    async def fetch_alerts(self) -> Response[AlertsResult]:
        return await self._get(ids.alerts_url(), parse_alerts, params=ids.alerts_params(), allow_404=False)

    async def fetch_bdeck(self, storm_id: str) -> Response[BestTrack]:
        return await self._get(ids.bdeck_url(storm_id), parse_bdeck)

    async def fetch_bdeck_index(self) -> Response[tuple[BDeckFile, ...]]:
        return await self._get(ids.BTK_INDEX_URL, parse_btk_index)

    async def fetch_forecast_gis(self, zip_url: str) -> Response[ForecastGis]:
        return await self._get(zip_url, parse_forecast_zip)

    async def fetch_radii_gis(self, zip_url: str) -> Response[WindRadiiGis]:
        return await self._get(zip_url, parse_radii_zip)

    async def fetch_best_track_gis(self, zip_url: str) -> Response[BestTrackGis]:
        return await self._get(zip_url, parse_best_track_zip)

    async def fetch_outlook_gis(
        self, *, etag: str | None = None, last_modified: str | None = None
    ) -> Response[OutlookGis]:
        return await self._get(
            ids.GTWO_ZIP_URL, parse_gtwo_zip, etag=etag, last_modified=last_modified, allow_404=False
        )

    async def fetch_graphics(self, landing_url: str) -> Response[tuple[GraphicLink, ...]]:
        return await self._get(landing_url, lambda body: parse_graphics_page(body, landing_url))

    async def fetch_floater_storms(self) -> Response[tuple[str, ...]]:
        return await self._get(ids.floater_url(), parse_floater_storms)

    async def fetch_floater_products(self, storm_id: str) -> Response[tuple[str, ...]]:
        return await self._get(ids.floater_url(storm_id), parse_floater_products)

    async def fetch_floater_product(self, storm_id: str, product: str) -> Response[FloaterProduct]:
        """The newest still and loop of one product. The listing is large for a long storm; fetch it on demand."""
        return await self._get(
            ids.floater_url(storm_id, product), lambda body: parse_floater_listing(body, storm_id, product)
        )

    # ---- provider layer -------------------------------------------------------------------------------------------

    async def storms(self) -> CurrentStorms:
        response = await self.fetch_current_storms()
        return response.value or CurrentStorms()

    async def _product[P: _Identified](
        self, storm: Storm, kind: ProductKind, ref: ProductRef | None, parse: Callable[[str], P], *, fallback: bool
    ) -> P | None:
        """Fetch, parse and staleness-check one text product for a storm; None when it is missing or not current."""
        if storm.bin_number is None or ref is None:
            return None
        try:
            response = await self.fetch_text(kind, ids.parse_bin(storm.bin_number), fallback=fallback)
            if not response.value:
                return None
            parsed = parse(response.value)
        except (FetchError, ParseError, ValueError):
            return None
        if not ids.text_is_current(storm, ref, storm_id=parsed.storm_id, adv_num=parsed.adv_num):
            return None
        return parsed

    async def advisory(self, storm: Storm, *, fallback: bool = False) -> AdvisorySet:
        """The four text products for a storm, each None when it is missing, unparsable or stale.

        tgftp is the source. `fallback` also allows the api.weather.gov copy (two more requests per product) when tgftp
        fails or has nothing; the poller sets it only after tgftp has failed to produce a current product, so the
        fallback is not paid for on every poll.
        """
        return AdvisorySet(
            forecast=await self._product(storm, ProductKind.TCM, storm.forecast_advisory, parse_tcm, fallback=fallback),
            public=await self._product(storm, ProductKind.TCP, storm.public_advisory, parse_tcp, fallback=fallback),
            discussion=await self._product(
                storm, ProductKind.TCD, storm.forecast_discussion, parse_tcd, fallback=fallback
            ),
            wind_probabilities=await self._product(
                storm, ProductKind.PWS, storm.wind_speed_probabilities, parse_pws, fallback=fallback
            ),
        )

    async def forecast_gis(self, storm: Storm) -> ForecastGis | None:
        ref = storm.forecast_track or storm.track_cone
        if ref is None or not ref.zip_url:
            return None
        try:
            return (await self.fetch_forecast_gis(ref.zip_url)).value
        except (FetchError, ParseError):
            return None

    async def radii_gis(self, storm: Storm) -> WindRadiiGis | None:
        ref = storm.forecast_wind_radii
        if ref is None or not ref.zip_url:
            return None
        try:
            return (await self.fetch_radii_gis(ref.zip_url)).value
        except (FetchError, ParseError):
            return None

    async def track(self, storm: Storm) -> BestTrack | None:
        try:
            return (await self.fetch_bdeck(storm.id)).value
        except (FetchError, ParseError, ValueError):
            return None

    async def outlook_text(self, *, fallback: bool = False) -> tuple[OutlookText, ...]:
        """The outlook text for each basin that could be fetched and parsed (tgftp only unless `fallback`)."""
        found: list[OutlookText] = []
        for basin in (Basin.AL, Basin.EP, Basin.CP):
            try:
                response = await self.fetch_outlook_text(basin, fallback=fallback)
                if response.value:
                    found.append(parse_two(response.value))
            except (FetchError, ParseError):
                continue
        return tuple(found)

    async def outlook_gis(self) -> OutlookGis:
        try:
            return (await self.fetch_outlook_gis()).value or OutlookGis(None)
        except (FetchError, ParseError):
            return OutlookGis(None)

    async def graphics(self, storm: Storm) -> tuple[GraphicLink, ...]:
        landing = storm.forecast_graphics.url if storm.forecast_graphics else None
        if landing is None and storm.bin_number is not None:
            landing = ids.graphics_landing_url(ids.parse_bin(storm.bin_number))
        if landing is None:
            return ()
        try:
            return (await self.fetch_graphics(landing)).value or ()
        except (FetchError, ParseError, ValueError):
            return ()
