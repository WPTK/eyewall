"""Fetch every live NHC, CPHC and NWS endpoint eyewall uses once, parse it, and print a one-line summary of each.

    python scripts/spot_check_nhc.py [--delay SECONDS] [--floater-product]

It reads the real services, so it is a format-drift check, not a test: run it before a release and from the weekly
canary. Exit status is 1 when any endpoint fails to fetch or parse, or when a structural assertion fails. A quiet day is
fine: the storm list is then empty, and the checks that need a storm use the most recent storm in each basin, whose last
advisory the bins and `*_latest.zip` files still hold.

What is fetched, in order, one request at a time with the eyewall User-Agent and a pause between requests:

- CurrentStorms.json, and for each active storm its four text products, forecast GIS, wind radii GIS, best track and
  b-deck (the cone must have at least one ring and every watch/warning code must be a known TCWW code).
- The last forecast/advisory in all fifteen product bins; the last public advisory, discussion and wind probabilities in
  bin 1 of each basin.
- The three tropical weather outlook texts, the api.weather.gov product fallback for one of them, the outlook
  shapefile zip and the active tropical alerts.
- The ATCF `btk` directory, and for the newest storm of each basin its b-deck and `5day_latest.zip` (plus the wind radii
  and best track zips for the newest Atlantic storm).
- The graphics landing page of the first Atlantic bin and the NESDIS floater storm and product directories. The floater
  product listing is over a megabyte for a long storm, so it is only fetched with --floater-product.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from typing import Any

from eyewall.models.forecast import ForecastGis
from eyewall.models.storm import Basin, CurrentStorms
from eyewall.net import FetchError, new_client
from eyewall.providers.base import ParseError
from eyewall.providers.nhc import ids
from eyewall.providers.nhc.client import NhcClient, Response
from eyewall.providers.nhc.ids import ProductKind
from eyewall.providers.nhc.tcm import parse_tcm
from eyewall.providers.nhc.text import parse_pws, parse_tcd, parse_tcp, parse_two

KNOWN_TCWW = {"TWA", "TWR", "HWA", "HWR"}
PRODUCT_PARSERS: dict[ProductKind, Callable[[str], Any]] = {
    ProductKind.TCM: parse_tcm,
    ProductKind.TCP: parse_tcp,
    ProductKind.TCD: parse_tcd,
    ProductKind.PWS: parse_pws,
}


class Report:
    def __init__(self) -> None:
        self.failures = 0
        self.checks = 0

    async def run(self, name: str, work: Callable[[], Awaitable[str]], delay: float) -> None:
        self.checks += 1
        started = time.monotonic()
        try:
            summary = await work()
            status = "ok  "
        except (FetchError, ParseError, AssertionError, ValueError, KeyError, IndexError) as exc:
            self.failures += 1
            summary = f"{type(exc).__name__}: {exc}"
            status = "FAIL"
        print(f"{status} {name:<34} {summary}  ({time.monotonic() - started:.1f}s)", flush=True)
        await asyncio.sleep(delay)


def _gis_summary(gis: ForecastGis) -> str:
    rings = len(gis.cone)
    if gis.points:
        assert rings >= 1, "forecast points but no cone polygon"
    codes = Counter(segment.code for segment in gis.watch_warnings)
    unknown = set(codes) - KNOWN_TCWW
    assert not unknown, f"unknown watch/warning codes {sorted(unknown)}"
    vertices = sum(len(ring) for ring in gis.cone)
    return (
        f"adv {gis.adv_num} cone rings={rings} ({vertices} vertices) points={len(gis.points)} "
        f"track lines={len(gis.track)} ww={dict(sorted(codes.items())) or 'none'}"
    )


def _missing(response: Response[Any]) -> str | None:
    return "missing (404)" if response.value is None else None


async def check_active_storms(client: NhcClient, report: Report, delay: float, current: CurrentStorms) -> None:
    for storm in current.storms:
        label = f"{storm.id} {storm.name}"
        advisory_set = await client.advisory(storm)
        found = [
            name
            for name, product in (
                ("tcm", advisory_set.forecast),
                ("tcp", advisory_set.public),
                ("tcd", advisory_set.discussion),
                ("pws", advisory_set.wind_probabilities),
            )
            if product is not None
        ]

        async def storm_text(found: list[str] = found, storm_adv: object = storm.adv_num) -> str:
            assert found, "no current text product matched the storm's advisory number"
            return f"adv {storm_adv} products: {', '.join(found)}"

        await report.run(f"{label} text", storm_text, delay)
        for attr, parse_name in (
            ("forecast_track", "forecast zip"),
            ("forecast_wind_radii", "radii zip"),
            ("best_track", "best track zip"),
        ):
            ref = getattr(storm, attr)
            if ref is None or not ref.zip_url:
                continue

            async def fetch_zip(ref: Any = ref, attr: str = attr) -> str:
                if attr == "forecast_track":
                    response = await client.fetch_forecast_gis(ref.zip_url)
                    return _missing(response) or _gis_summary(response.value)
                if attr == "forecast_wind_radii":
                    radii = await client.fetch_radii_gis(ref.zip_url)
                    return _missing(radii) or f"initial={len(radii.value.initial)} forecast={len(radii.value.forecast)}"
                best = await client.fetch_best_track_gis(ref.zip_url)
                return _missing(best) or f"points={len(best.value.points)} segments={len(best.value.segments)}"

            await report.run(f"{label} {parse_name}", fetch_zip, delay)

        async def bdeck(storm_id: str = storm.id) -> str:
            response = await client.fetch_bdeck(storm_id)
            return _missing(response) or f"{len(response.value.fixes)} fixes, name {response.value.name}"

        await report.run(f"{label} b-deck", bdeck, delay)


async def check_bins(client: NhcClient, report: Report, delay: float) -> None:
    for basin in (Basin.AL, Basin.EP, Basin.CP):
        for bin_ in ids.bins_for(basin):

            async def tcm(bin_: ids.Bin = bin_) -> str:
                response = await client.fetch_text(ProductKind.TCM, bin_, fallback=False)
                if response.value is None:
                    return "missing (404)"
                parsed = parse_tcm(response.value)
                return f"{parsed.storm_id} {parsed.kind} {parsed.name} adv {parsed.adv_num} fixes={len(parsed.fixes)}"

            await report.run(f"TCM {bin_.name}", tcm, delay)
        first = ids.bins_for(basin)[0]
        for kind in (ProductKind.TCP, ProductKind.TCD, ProductKind.PWS):

            async def other(kind: ProductKind = kind, first: ids.Bin = first) -> str:
                response = await client.fetch_text(kind, first, fallback=False)
                if response.value is None:
                    return "missing (404)"
                parsed = PRODUCT_PARSERS[kind](response.value)
                extra = f" rows={len(parsed.rows)}" if kind is ProductKind.PWS else ""
                return f"{parsed.storm_id} adv {parsed.adv_num}{extra}"

            await report.run(f"{kind.value} {first.name}", other, delay)


async def check_outlooks(client: NhcClient, report: Report, delay: float) -> None:
    for basin in (Basin.AL, Basin.EP, Basin.CP):

        async def two(basin: Basin = basin) -> str:
            response = await client.fetch_outlook_text(basin, fallback=False)
            assert response.value, "empty outlook"
            parsed = parse_two(response.value)
            return f"{len(parsed.areas)} areas, quiet={parsed.quiet}, issued {parsed.issued:%Y-%m-%d %H:%MZ}"

        await report.run(f"TWO {basin.value}", two, delay)

    async def fallback() -> str:
        response = await client.fetch_api_text(ProductKind.TWO, ids.outlook_location(Basin.AL))
        assert response.value, "api.weather.gov returned no outlook text"
        return f"{len(parse_two(response.value).areas)} areas via api.weather.gov"

    await report.run("TWO AT (api.weather.gov)", fallback, delay)

    async def gtwo() -> str:
        response = await client.fetch_outlook_gis()
        systems = response.value.systems
        return f"{len(systems)} systems: " + ", ".join(
            f"{s.basin_label} {s.area_id} {s.prob_2day}%/{s.prob_7day}%" for s in systems
        )

    await report.run("gtwo_shapefiles.zip", gtwo, delay)

    async def alerts() -> str:
        response = await client.fetch_alerts()
        alerts_ = response.value
        return f"{len(alerts_.alerts)} active tropical alerts, {alerts_.skipped} skipped"

    await report.run("api.weather.gov alerts", alerts, delay)


async def check_latest_storms(client: NhcClient, report: Report, delay: float) -> None:
    """The newest storm in each basin from the btk listing: its b-deck and last GIS, quiet day or not."""
    index: list[Any] = []

    async def listing() -> str:
        response = await client.fetch_bdeck_index()
        index.extend(response.value or ())
        invests = [f.storm_id for f in index if f.is_invest]
        return f"{len(index)} b-decks, invests: {', '.join(invests) or 'none'}"

    await report.run("ATCF btk listing", listing, delay)
    if not index:
        return
    year = max(f.year for f in index)
    newest: dict[str, Any] = {}
    for f in index:
        if f.year != year or f.is_invest or f.is_training:
            continue
        if f.basin_code not in newest or f.number > newest[f.basin_code].number:
            newest[f.basin_code] = f
    for code in ("AL", "EP", "CP"):
        latest = newest.get(code)
        if latest is None:
            continue

        async def bdeck(storm_id: str = latest.storm_id) -> str:
            response = await client.fetch_bdeck(storm_id)
            track = response.value
            return (
                _missing(response)
                or f"{len(track.fixes)} fixes, name {track.name}, last {track.latest.time:%Y-%m-%d %H}Z"
            )

        await report.run(f"b-deck {latest.storm_id}", bdeck, delay)

        async def zip5(storm_id: str = latest.storm_id) -> str:
            response = await client.fetch_forecast_gis(ids.forecast_zip_url(storm_id, None))
            return _missing(response) or _gis_summary(response.value)

        await report.run(f"5day latest {latest.storm_id}", zip5, delay)
    atlantic = newest.get("AL")
    if atlantic is not None:

        async def radii() -> str:
            response = await client.fetch_radii_gis(ids.forecast_zip_url(atlantic.storm_id, None, "fcst"))
            return (
                _missing(response) or f"initial={len(response.value.initial)} forecast={len(response.value.forecast)}"
            )

        await report.run(f"fcst latest {atlantic.storm_id}", radii, delay)

        async def best() -> str:
            response = await client.fetch_best_track_gis(ids.best_track_zip_url(atlantic.storm_id))
            return _missing(response) or f"points={len(response.value.points)} segments={len(response.value.segments)}"

        await report.run(f"best track {atlantic.storm_id}", best, delay)


async def check_graphics(client: NhcClient, report: Report, delay: float, floater_product: bool) -> None:
    async def landing() -> str:
        url = ids.graphics_landing_url(ids.parse_bin("AT1"))
        response = await client.fetch_graphics(url)
        links = response.value or ()
        return f"{len(links)} storm graphics linked"

    await report.run("graphics_at1.shtml", landing, delay)
    storms: list[str] = []

    async def floater_root() -> str:
        response = await client.fetch_floater_storms()
        storms.extend(response.value or ())
        assert storms, "no storm directories listed"
        return f"{len(storms)} storm directories, newest {storms[-1]}"

    await report.run("NESDIS FLOATER/data/", floater_root, delay)
    if not storms:
        return
    current_year = storms[-1][-4:]
    recent = [s for s in storms if s.endswith(current_year)]
    chosen = recent[-1]

    async def products() -> str:
        response = await client.fetch_floater_products(chosen)
        return f"{len(response.value or ())} product directories: {', '.join((response.value or ())[:6])}..."

    await report.run(f"NESDIS {chosen}/", products, delay)
    if floater_product:

        async def product() -> str:
            response = await client.fetch_floater_product(chosen, "GEOCOLOR")
            found = response.value
            assert found is not None and (found.still_url or found.loop_url), "no GEOCOLOR still or loop"
            return f"still {found.still_time:%Y-%m-%d %H:%MZ}, loop {'yes' if found.loop_url else 'no'}"

        await report.run(f"NESDIS {chosen} GEOCOLOR", product, delay)


async def main_async(delay: float, floater_product: bool) -> int:
    report = Report()
    async with new_client() as http:
        client = NhcClient(http)
        current_holder: list[CurrentStorms] = []

        async def current() -> str:
            response = await client.fetch_current_storms()
            current_holder.append(response.value or CurrentStorms())
            storms = current_holder[0].storms
            if not storms:
                return "0 active storms (activeStorms is empty)"
            return f"{len(storms)} active: " + ", ".join(f"{s.id} {s.name} {s.classification.value}" for s in storms)

        await report.run("CurrentStorms.json", current, delay)
        if current_holder:
            await check_active_storms(client, report, delay, current_holder[0])
        await check_bins(client, report, delay)
        await check_outlooks(client, report, delay)
        await check_latest_storms(client, report, delay)
        await check_graphics(client, report, delay, floater_product)
    print(f"\n{report.checks - report.failures} of {report.checks} checks passed")
    return 1 if report.failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--delay", type=float, default=0.4, help="seconds to wait between checks (default 0.4)")
    parser.add_argument("--floater-product", action="store_true", help="also fetch one NESDIS product listing (large)")
    args = parser.parse_args(argv)
    return asyncio.run(main_async(max(args.delay, 0.0), args.floater_product))


if __name__ == "__main__":
    sys.exit(main())
