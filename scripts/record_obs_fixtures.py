"""Record the NDBC and CO-OPS payloads the observation tests parse.

Fetches each feed once from the live services (a second apart, with the eyewall User-Agent), trims the big ones to the
rows the tests need without changing a byte of what is kept, and writes them under tests/fixtures/ndbc and
tests/fixtures/coops together with a manifest of where and when each came from. Run it again when a feed changes shape,
then fix whatever the tests say.

    python scripts/record_obs_fixtures.py            # everything, about 17 requests
    python scripts/record_obs_fixtures.py --only ndbc
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import io
import json
import re
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from eyewall.coops.data import DATAGETTER_URL, datagetter_params
from eyewall.coops.stations import LISTING_TYPES
from eyewall.ndbc.client import LATEST_OBS_URL, STATIONS_URL, five_day_url, yearly_url
from eyewall.net import fetch_bytes, new_client

ROOT = Path(__file__).resolve().parent.parent
PAUSE_SECONDS = 1.0
COOPS_STATIONS_URL = "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json"

# latest_obs rows always kept when present: replay buoys, C-MAN stations, Hawaii (no pressure) and odd rows.
LATEST_KEEP = ("41010", "41025", "41047", "41048", "42001", "TRDF1", "SSBN7", "22101", "51WH0", "AAMC1", "44137")
# activestations.xml entries always kept: working buoys, dark ones (met="n"), C-MAN and partner stations.
CATALOG_KEEP = (
    "41010", "41001", "41002", "41025", "41047", "41048", "42001", "42003", "42019", "42040", "fwyf1", "trdf1", "ssbn7",
)  # fmt: skip
STATION = "41010"
DARK_STATION = "42040"
HISTORICAL_STATION, HISTORICAL_YEAR = "41025", 2025
HISTORICAL_WINDOW = (datetime(2025, 8, 17, tzinfo=UTC), datetime(2025, 8, 25, tzinfo=UTC))  # Hurricane Erin passes
TIDE_STATION = "8721604"  # Trident Pier, Port Canaveral: water level, wind and pressure
NO_MET_STATION = "8735523"  # East Fowl River Bridge: water level only
GAP_CANDIDATES = ("8721604", "8720218", "8723214", "8724580", "8726520", "8729840", "8735180", "8761724", "8518750")
TIDE_KEEP = ("8721604", "8720218", "8723214", "8724580", "8735523", "8518750", "8761724", "8729840", "8726520")


class Recorder:
    """Writes payloads into one fixture folder and remembers where each came from."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.entries: list[dict[str, Any]] = []
        folder.mkdir(parents=True, exist_ok=True)

    def save(
        self, name: str | None, data: bytes, *, url: str, status: int, note: str, params: dict[str, str] | None = None
    ) -> None:
        if name and data:
            (self.folder / name).write_bytes(data)
        self.entries.append(
            {
                "file": name if data else None,
                "url": url,
                "params": params,
                "status": status,
                "bytes": len(data),
                "fetched": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"),
                "note": note,
            }
        )
        print(f"  {status} {len(data):>8} bytes  {name if data else '(no body)'}  {note}")

    def finish(self) -> None:
        manifest = {"recorded_by": "scripts/record_obs_fixtures.py", "payloads": self.entries}
        text = json.dumps(manifest, indent=2) + "\n"
        (self.folder / "manifest.json").write_bytes(text.encode("utf-8"))  # bytes: fixtures must stay LF on Windows


# --- trimming ---------------------------------------------------------------------------------------------------


def first_n(rows: list[str], n: int, wanted: Callable[[str], bool]) -> list[str]:
    return [r for r in rows if wanted(r)][:n]


def trim_latest(text: str) -> str:
    """Header, the named stations, and the first few rows with missing wind, missing pressure, a PTDY or a wave."""
    lines = text.splitlines(keepends=True)
    header = next(line for line in lines if line.startswith("#STN")).lstrip("#").split()
    rows = [line for line in lines if not line.startswith("#")]

    def column(row: str, name: str) -> str:
        return row.split()[header.index(name)]

    chosen = {r for r in rows if r.split()[0] in LATEST_KEEP}
    chosen.update(first_n(rows, 3, lambda r: column(r, "WSPD") == "MM"))
    chosen.update(first_n(rows, 3, lambda r: column(r, "PRES") == "MM"))
    chosen.update(first_n(rows, 3, lambda r: column(r, "PTDY") != "MM"))
    chosen.update(first_n(rows, 3, lambda r: column(r, "WVHT") != "MM"))
    return "".join(line for line in lines if line.startswith("#") or line in chosen)


def trim_catalog(text: str) -> str:
    """The XML wrapper plus the named stations, one of each type, one with no flags and one with a long id."""
    lines = text.splitlines(keepends=True)
    stations = [line for line in lines if line.lstrip().startswith("<station ")]

    def attr(line: str, name: str) -> str | None:
        found = re.search(rf' {name}="([^"]*)"', line)
        return found.group(1) if found else None

    chosen = {line for line in stations if attr(line, "id") in CATALOG_KEEP}
    for kind in sorted({attr(line, "type") or "" for line in stations}):
        chosen.update(first_n(stations, 1, lambda s, kind=kind: attr(s, "type") == kind))
    chosen.update(first_n(stations, 1, lambda s: attr(s, "met") is None))
    chosen.update(first_n(stations, 1, lambda s: len(attr(s, "id") or "") >= 7))
    return "".join(line for line in lines if line in chosen or not line.lstrip().startswith("<station "))


def trim_historical(data: bytes) -> bytes:
    """Gunzip a yearly file, keep its header and the rows inside the window, and gzip it again reproducibly."""
    start, end = HISTORICAL_WINDOW
    kept = []
    for line in gzip.decompress(data).decode("utf-8").splitlines(keepends=True):
        if line.startswith("#"):
            kept.append(line)
            continue
        y, mo, d, h, mi = (int(t) for t in line.split()[:5])
        if start <= datetime(y, mo, d, h, mi, tzinfo=UTC) <= end:
            kept.append(line)
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", compresslevel=9, mtime=0) as handle:
        handle.write("".join(kept).encode("utf-8"))
    return buffer.getvalue()


def trim_tide_stations(data: bytes, extra_first: int = 0) -> bytes:
    """Keep the listed gauges, the first Great Lakes gauge and `extra_first` more; the count field stays as recorded."""
    payload = json.loads(data)
    stations = payload["stations"]
    kept = [s for s in stations if s.get("id") in TIDE_KEEP]
    kept += [s for s in stations if s.get("greatlakes") and s not in kept][:1]
    kept += [s for s in stations if s not in kept][:extra_first]
    payload["stations"] = kept
    return (json.dumps(payload, indent=2) + "\n").encode("utf-8")


# --- recording --------------------------------------------------------------------------------------------------


async def pause() -> None:
    await asyncio.sleep(PAUSE_SECONDS)


async def record_ndbc(client: httpx.AsyncClient, rec: Recorder) -> None:
    print("NDBC")
    got = await fetch_bytes(client, LATEST_OBS_URL)
    trimmed = trim_latest(got.text())
    rec.save("latest_obs.txt", trimmed.encode(), url=LATEST_OBS_URL, status=got.status, note="trimmed to chosen rows")
    await pause()
    got = await fetch_bytes(client, STATIONS_URL)
    rec.save(
        "activestations.xml",
        trim_catalog(got.text()).encode(),
        url=STATIONS_URL,
        status=got.status,
        note="trimmed to chosen stations; the count attribute is the full catalog's",
    )
    await pause()
    for suffix in ("txt", "supl", "spec"):
        url = five_day_url(STATION, suffix)
        got = await fetch_bytes(client, url)
        rec.save(f"{STATION}_5day.{suffix}", got.body, url=url, status=got.status, note="whole file")
        await pause()
    url = five_day_url(DARK_STATION)
    got = await fetch_bytes(client, url, allow_404=True)
    rec.save(None, got.body, url=url, status=got.status, note="a listed buoy that is dark: 404 means not reporting")
    await pause()
    url = yearly_url(HISTORICAL_STATION, HISTORICAL_YEAR)
    got = await fetch_bytes(client, url)
    start, end = (moment.strftime("%Y-%m-%d") for moment in HISTORICAL_WINDOW)
    rec.save(
        f"{HISTORICAL_STATION}h{HISTORICAL_YEAR}_erin_week.txt.gz",
        trim_historical(got.body),
        url=url,
        status=got.status,
        note=f"rows from {start} to {end} only, regzipped; historical fills (99.0, 999, 9999.0)",
    )


async def get_json(client: httpx.AsyncClient, params: dict[str, str]) -> tuple[int, bytes]:
    """A datagetter response whatever its status: CO-OPS puts its error explanations in 400 bodies."""
    response = await client.get(DATAGETTER_URL, params=params)
    return response.status_code, response.content


def has_gaps(data: bytes) -> bool:
    rows = json.loads(data).get("data", [])
    return any(row.get("v") == "" for row in rows)


async def record_coops(client: httpx.AsyncClient, rec: Recorder) -> None:
    print("CO-OPS")
    for product, name in (("water_level", "stations_waterlevels.json"), ("met", "stations_met.json")):
        params = {"type": LISTING_TYPES[product]}
        got = await fetch_bytes(client, COOPS_STATIONS_URL, params=params)
        rec.save(
            name,
            trim_tide_stations(got.body, extra_first=0 if product == "water_level" else 2),
            url=COOPS_STATIONS_URL,
            params=params,
            status=got.status,
            note="trimmed to chosen stations; the count field is the full listing's",
        )
        await pause()

    def save_data(name: str, params: dict[str, str], status: int, body: bytes, note: str) -> None:
        rec.save(name, body, url=DATAGETTER_URL, params=params, status=status, note=note)

    midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    plain = (
        ("water_level_latest.json", datagetter_params("water_level", TIDE_STATION, date="latest"), "latest reading"),
        ("wind_recent.json", datagetter_params("wind", TIDE_STATION, hours=3), "last 3 hours"),
        ("air_pressure_recent.json", datagetter_params("air_pressure", TIDE_STATION, hours=3), "last 3 hours"),
        (
            "predictions_hilo.json",
            datagetter_params("predictions", TIDE_STATION, interval="hilo", begin=midnight, hours=48),
            "high and low tides, 48 hours from UTC midnight",
        ),
        (
            "predictions_interval.json",
            datagetter_params("predictions", TIDE_STATION, begin=midnight, hours=6),
            "6-minute predictions, 6 hours from UTC midnight",
        ),
        (
            "wind_no_data.json",
            datagetter_params("wind", NO_MET_STATION, date="latest"),
            "a gauge without an anemometer: HTTP 200 with an error object",
        ),
    )
    for name, params, note in plain:
        status, body = await get_json(client, params)
        save_data(name, params, status, body, note)
        await pause()

    params = datagetter_params("water_level", TIDE_STATION, date="latest")
    params.pop("datum")
    status, body = await get_json(client, params)
    save_data("error_no_datum.json", params, status, body, "water level without a datum: HTTP 400 with an error object")
    await pause()

    fallback: tuple[str, dict[str, str], bytes] | None = None
    for station in GAP_CANDIDATES:
        params = datagetter_params("water_level", station, date="recent")
        status, body = await get_json(client, params)
        await pause()
        if status == 200 and has_gaps(body):
            save_data(
                "water_level_recent.json", params, status, body, f"last 3 days at {station}, with empty-string gaps"
            )
            return
        if fallback is None and status == 200:
            fallback = (station, params, body)
    if fallback is not None:
        station, params, body = fallback
        save_data("water_level_recent.json", params, 200, body, f"last 3 days at {station}; no gaps in this window")
        print("  NOTE: no live window had empty-string gaps; the tests blank some values themselves")


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", choices=("ndbc", "coops"), help="record just one service")
    parser.add_argument("--out", type=Path, default=ROOT / "tests" / "fixtures", help="fixtures root")
    args = parser.parse_args(argv)
    async with new_client() as client:
        if args.only in (None, "ndbc"):
            rec = Recorder(args.out / "ndbc")
            await record_ndbc(client, rec)
            rec.finish()
        if args.only in (None, "coops"):
            rec = Recorder(args.out / "coops")
            await record_coops(client, rec)
            rec.finish()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
