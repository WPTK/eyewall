"""Fetch every NDBC and CO-OPS feed once, parse it with eyewall's parsers and print a summary.

This is the check to run after a milestone, or when a parser starts failing, to see whether the live services still
look the way the code expects. It makes about 14 requests, a second apart, with the eyewall User-Agent. It exits 1 when
a feed does not parse as expected, 2 when the only problems are feeds that were down, unreachable or empty (an outage
is not a format change), and 0 otherwise. A line starting `DOWN` is an outage, one starting `FAIL` is a format failure.

    python scripts/spot_check_obs.py
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from functools import partial

import httpx

from eyewall.clock import format_age
from eyewall.coops.client import CoopsClient
from eyewall.models.obs import Observation, Station
from eyewall.ndbc.client import NdbcClient
from eyewall.net import FetchError, new_client
from eyewall.state.nearby import TrackFix, nearby_stations
from eyewall.state.trends import station_trends

PAUSE_SECONDS = 1.0
LIVE_BUOY = "41010"
TIDE_GAUGE = "8721604"  # Trident Pier, Port Canaveral: water level, wind and air pressure
GAUGE_WITHOUT_MET = "8735523"  # East Fowl River Bridge: water level only
DARK_CANDIDATES = ("42040", "41001", "42003", "42019", "42020", "42059")  # listed but dark as of 2026-10-31


class Report:
    def __init__(self) -> None:
        self.failures = 0
        self.outages = 0
        self._empty_body = False

    async def watch(self, response: httpx.Response) -> None:
        """Response hook: remember a body of zero bytes, the one empty answer that is an outage, not format drift."""
        await response.aread()
        if not response.content:
            self._empty_body = True

    def ok(self, label: str, detail: str) -> None:
        print(f"  ok    {label:<28} {detail}")

    def fail(self, label: str, detail: str) -> None:
        self.failures += 1
        print(f"  FAIL  {label:<28} {detail}")

    def down(self, label: str, detail: str) -> None:
        self.outages += 1
        print(f"  DOWN  {label:<28} {detail}")

    def check(self, passed: bool, label: str, detail: str) -> None:
        """Record one check. A failed check is DOWN when the feed sent zero bytes, FAIL otherwise: a non-empty answer
        that parses to nothing (a renamed column or key) is format drift."""
        empty, self._empty_body = self._empty_body, False
        if passed:
            self.ok(label, detail)
        elif empty:
            self.down(label, detail)
        else:
            self.fail(label, detail)

    async def fetch[T](self, label: str, call: Callable[[], Awaitable[T]]) -> T | None:
        """Wait a second, then make one request (NDBC asks for minimal retrievals). A FetchError is an outage: it is
        recorded and None comes back so the checks that do not depend on this feed still run."""
        self._empty_body = False
        await asyncio.sleep(PAUSE_SECONDS)
        try:
            return await call()
        except FetchError as exc:
            self.down(label, str(exc))
            return None


def describe(observation: Observation | None, now: datetime) -> str:
    if observation is None:
        return "no observations"
    age = format_age((now - observation.time).total_seconds())
    wind, pressure = observation.wind_speed_mps, observation.pressure_hpa
    return f"newest {observation.time:%Y-%m-%d %H:%MZ} ({age} old), wind {wind} m/s, pressure {pressure} hPa"


async def check_ndbc(ndbc: NdbcClient, report: Report) -> list[Station]:
    print("NDBC")
    now = datetime.now(UTC)
    stations: list[Station] = []
    live_ids: set[str] = set()

    response = await report.fetch("activestations.xml", ndbc.stations)
    if response is not None:
        catalog = response.value
        stations = list(catalog.items) if catalog else []
        reporting = sum(1 for s in stations if s.met)
        report.check(
            len(stations) > 500,
            "activestations.xml",
            f"{len(stations)} stations, {reporting} with met data, {catalog.skipped if catalog else '?'} skipped",
        )

    response = await report.fetch("latest_obs.txt", ndbc.latest_obs)
    if response is not None:
        latest = response.value
        rows = list(latest.items) if latest else []
        with_wind = sum(1 for r in rows if r.observation.wind_speed_mps is not None)
        with_pressure = sum(1 for r in rows if r.observation.pressure_hpa is not None)
        report.check(
            len(rows) > 300,
            "latest_obs.txt",
            f"{len(rows)} stations, {with_wind} with wind, "
            f"{with_pressure} with pressure, {latest.skipped if latest else '?'} skipped",
        )
        live_ids = {r.station_id for r in rows}

    response = await report.fetch(f"{LIVE_BUOY}_5day.txt", lambda: ndbc.series(LIVE_BUOY))
    series = response.value if response is not None else None
    if response is not None:
        report.check(
            bool(series and series.reporting),
            f"{LIVE_BUOY}_5day.txt",
            f"{len(series.observations) if series else 0} rows; " + describe(series.latest if series else None, now),
        )
    if series and series.reporting:
        extra_response = await report.fetch(f"{LIVE_BUOY}_5day.supl", lambda: ndbc.supplemental(LIVE_BUOY))
        extra = extra_response.value if extra_response is not None else None
        supl_rows = list(extra.items) if extra else []
        if extra_response is not None:
            report.check(bool(supl_rows), f"{LIVE_BUOY}_5day.supl", f"{len(supl_rows)} rows")
        waves_response = await report.fetch(f"{LIVE_BUOY}_5day.spec", lambda: ndbc.waves(LIVE_BUOY))
        if waves_response is not None:
            waves = waves_response.value
            report.check(
                bool(waves and waves.items), f"{LIVE_BUOY}_5day.spec", f"{len(waves.items) if waves else 0} rows"
            )
        trends = station_trends(series, supl_rows, now=now, window_hours=72)
        tendency = trends.pressure_tendency
        report.ok(
            "trends",
            f"3 h pressure change {tendency.delta_hpa:+.1f} hPa ({tendency.source})"
            if tendency
            else "3 h pressure change unavailable",
        )
        low, peak = trends.extremes.min_pressure_hpa, trends.extremes.peak_gust_mps
        report.ok("extremes (72 h)", f"lowest pressure {low} hPa, peak gust {peak} m/s, silent={trends.silent}")

    dark = [c for c in DARK_CANDIDATES if c not in live_ids]
    dark += [
        s.id
        for s in stations
        if s.type == "buoy" and s.owner == "NDBC" and s.met is False and s.id not in live_ids and s.id not in dark
    ]
    for candidate in dark[:3]:
        dark_response = await report.fetch(f"dark buoy {candidate}", partial(ndbc.series, candidate))
        result = dark_response.value if dark_response is not None else None
        if result is not None and not result.reporting:
            report.ok(f"dark buoy {candidate}", "not reporting (404 for its file)")
            break
    else:
        report.fail("dark buoy", "none of the usual dark buoys was missing its file; pick new ones in DARK_CANDIDATES")
    return stations


async def check_coops(coops: CoopsClient, report: Report, ndbc_stations: list[Station]) -> None:
    print("CO-OPS")
    now = datetime.now(UTC)
    gauges = await report.fetch("stations.json", coops.all_stations)
    if gauges is not None:
        both = sum(1 for g in gauges if {"water_level", "met"} <= g.products)
        report.check(len(gauges) > 250, "stations.json", f"{len(gauges)} stations, {both} with water level and met")

    levels = await report.fetch(f"water_level {TIDE_GAUGE}", lambda: coops.water_level(TIDE_GAUGE, date="recent"))
    if levels is not None:
        gaps = sum(1 for r in levels.items if r.level_ft is None)
        newest = levels.items[0] if levels.items else None
        report.check(
            bool(levels.items),
            f"water_level {TIDE_GAUGE}",
            f"{len(levels.items)} readings, {gaps} gaps"
            + (f", newest {newest.level_ft} ft at {newest.time:%H:%MZ}" if newest else ""),
        )
    tides = await report.fetch("predictions (hilo)", lambda: coops.predictions(TIDE_GAUGE, begin=now, hours=36))
    if tides is not None:
        nxt = ", ".join(f"{p.kind} {p.level_ft} ft {p.time:%a %H:%MZ}" for p in tides.items[:3])
        report.check(bool(tides.items), "predictions (hilo)", nxt or "none")
    wind = await report.fetch("wind", lambda: coops.wind(TIDE_GAUGE, hours=3))
    if wind is not None:
        top = wind.items[0] if wind.items else None
        report.check(
            top is not None,
            "wind",
            f"{len(wind.items)} readings" + (f", {top.speed_kt} kt {top.direction_text}" if top else ""),
        )
    pressure = await report.fetch("air_pressure", lambda: coops.air_pressure(TIDE_GAUGE, hours=3))
    if pressure is not None:
        top_p = pressure.items[0] if pressure.items else None
        report.check(
            top_p is not None,
            "air_pressure",
            f"{len(pressure.items)} readings" + (f", {top_p.pressure_mb} mb" if top_p else ""),
        )
    missing = await report.fetch(f"wind {GAUGE_WITHOUT_MET}", lambda: coops.wind(GAUGE_WITHOUT_MET, date="latest"))
    if missing is not None:
        report.check(
            not missing.items and bool(missing.message),
            f"wind {GAUGE_WITHOUT_MET}",
            f"no data, as expected: {missing.message}",
        )

    if ndbc_stations:
        sample = nearby_stations(
            (27.0, -79.0),
            [TrackFix(24, 31.0, -78.0), TrackFix(48, 35.0, -75.0), TrackFix(72, 40.0, -70.0)],
            [s for s in ndbc_stations if s.met],
        )
        names = ", ".join(n.station.id for n in sample[:5])
        report.check(
            bool(sample),
            "nearby (made-up storm)",
            f"{len(sample)} stations near 27N 79W heading north; nearest {names}",
        )


async def main() -> int:
    report = Report()
    started = datetime.now(UTC)
    async with new_client() as client:
        client.event_hooks["response"].append(report.watch)
        stations = await check_ndbc(NdbcClient(client), report)
        await check_coops(CoopsClient(client), report, stations)
    took = (datetime.now(UTC) - started) / timedelta(seconds=1)
    print(f"\n{'all feeds parsed' if not report.failures else str(report.failures) + ' problem(s)'} in {took:.0f} s")
    if report.outages:
        print(f"{report.outages} feed(s) down or empty")
    return 1 if report.failures else 2 if report.outages else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
