"""Record a past storm from NOAA's archives into a replay bundle (see `eyewall.sources.bundle` for the layout).

    python scripts/record_storm.py AL052025 --from 2025-08-18T09:00 --to 2025-08-21T03:00 --out DIR --stations auto

Sources: the NHC archive pages (fstadv, public, discus, wndprb) and GIS archive zips for each advisory in the window,
the ATCF archive b-deck, the NDBC yearly historical files, and CO-OPS date ranges. `--stations auto` picks the
buoys within 300 nm of the best track that have data in the window (nearest first); `--tide-gauges auto` does the same
for CO-OPS water level gauges within 250 nm. Times are UTC. The script waits `--delay` seconds between requests.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import html
import json
import re
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from eyewall.coops.client import STATIONS_URL as COOPS_STATIONS_URL
from eyewall.coops.data import DATAGETTER_URL, datagetter_params
from eyewall.coops.stations import LISTING_TYPES, parse_tide_stations
from eyewall.geo import haversine_nm
from eyewall.models.storm import AdvNum
from eyewall.ndbc.client import STATIONS_URL as NDBC_STATIONS_URL
from eyewall.ndbc.client import yearly_url
from eyewall.ndbc.historical import decompress
from eyewall.ndbc.stations import parse_stations
from eyewall.net import FetchError, fetch_bytes, new_client
from eyewall.providers.base import ParseError
from eyewall.providers.nhc import ids
from eyewall.providers.nhc.atcf import parse_bdeck
from eyewall.providers.nhc.tcm import parse_tcm
from eyewall.providers.nhc.text import parse_tcp
from eyewall.sources import bundle

NOW_RADIUS_NM = 300.0
TIDE_RADIUS_NM = 250.0
_PRE = re.compile(r"<pre>(.*?)</pre>", re.DOTALL | re.IGNORECASE)
_SUFFIXES = ("A", "B", "C")
_ARCHIVE_KINDS = {"fstadv": "tcm", "public": "tcp", "discus": "tcd", "wndprb": "pws"}


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def parse_moment(text: str) -> datetime:
    moment = datetime.fromisoformat(text)
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


class Recorder:
    def __init__(self, http: httpx.AsyncClient, out: Path, delay: float) -> None:
        self.http = http
        self.out = out
        self.delay = delay

    async def get(self, url: str, *, params: dict[str, str] | None = None) -> bytes | None:
        """The body, or None for a 404. Other failures propagate."""
        await asyncio.sleep(self.delay)
        fetched = await fetch_bytes(self.http, url, params=params, allow_404=True)
        return None if fetched.missing else fetched.body

    def write(self, relative: str, data: bytes | str) -> None:
        path = self.out / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, str):
            path.write_text(data, encoding="utf-8", newline="\n")
        else:
            path.write_bytes(data)

    async def archive_text(self, kind: str, storm_id: str, adv: AdvNum) -> str | None:
        body = await self.get(ids.archive_product_url(kind, storm_id, adv))
        if body is None:
            return None
        match = _PRE.search(body.decode("utf-8", errors="replace"))
        if match is None:
            return None
        text = html.unescape(match.group(1)).replace("\r\n", "\n").strip("\n")
        return text + "\n"

    # ---- advisories -------------------------------------------------------------------------------------------

    async def advisories(self, storm_id: str, start: datetime, end: datetime) -> list[AdvNum]:
        """Record every advisory issued in the window plus the one in effect at its start. Returns their numbers."""
        found: list[tuple[AdvNum, datetime]] = []
        number = 1
        misses = 0
        while misses < 3:
            adv = AdvNum(number)
            text = await self.archive_text("fstadv", storm_id, adv)
            number += 1
            if text is None:
                misses += 1
                continue
            misses = 0
            try:
                issued = parse_tcm(text).issued
            except ParseError:
                log(f"advisory {adv}: the archive page is not a forecast/advisory; skipped")
                continue
            found.append((adv, issued))
            if issued > end:
                break
        before = [f for f in found if f[1] <= start]
        keep = [f for f in found if start < f[1] <= end]
        if before:
            keep.insert(0, before[-1])
        recorded: list[AdvNum] = []
        for adv, _issued in keep:
            log(f"advisory {adv}")
            label = ids.format_adv_num(adv)
            for kind, ext in _ARCHIVE_KINDS.items():
                text = await self.archive_text(kind, storm_id, adv)
                if text is not None:
                    self.write(bundle.text_path(storm_id, label, ext), text)
            recorded.append(adv)
            for suffix in _SUFFIXES:
                inter = AdvNum(adv.number, suffix)
                text = await self.archive_text(f"public_{suffix.lower()}", storm_id, adv)
                if text is None:
                    break
                issued = parse_tcp(text).issued
                if issued is not None and not (start < issued <= end):
                    break
                log(f"advisory {inter}")
                self.write(bundle.text_path(storm_id, ids.format_adv_num(inter), "tcp"), text)
                recorded.append(inter)
        return recorded

    async def gis(self, storm_id: str, advisories: Sequence[AdvNum]) -> None:
        for adv in advisories:
            label = ids.format_adv_num(adv)
            for layer in bundle.GIS_LAYERS:
                body = await self.get(ids.forecast_zip_url(storm_id, adv, layer))
                if body is not None:
                    self.write(bundle.gis_path(storm_id, label, layer), body)

    async def graphics(self, storm_id: str, advisories: Sequence[AdvNum], count: int) -> list[bundle.GraphicEntry]:
        """The cone with wind field for `count` advisories spread over the window."""
        mains = [a for a in advisories if not a.intermediate]
        if not mains or count <= 0:
            return []
        parsed = ids.parse_storm_id(storm_id)
        spread = {mains[min(len(mains) - 1, i * len(mains) // count + len(mains) // (2 * count))] for i in range(count)}
        entries: list[bundle.GraphicEntry] = []
        for adv in sorted(spread):
            url = (
                f"{ids.NHC_BASE}/archive/{parsed.year}/graphics/{parsed.upper}/"
                f"{parsed.upper}_5day_cone_with_line_and_wind_{adv}.png"
            )
            body = await self.get(url)
            if body is None:
                continue
            name = f"cone_{ids.format_adv_num(adv)}.png"
            self.write(f"graphics/{name}", body)
            entries.append(bundle.GraphicEntry(name, "cone", "5day_cone_with_line_and_wind", ids.format_adv_num(adv)))
        return entries

    # ---- best track -------------------------------------------------------------------------------------------

    async def best_track(
        self, storm_id: str, start: datetime, end: datetime, before: timedelta
    ) -> list[tuple[float, float]]:
        """Write the b-deck rows from `before` ahead of the window to its end; return the window's positions."""
        body = await self.get(ids.bdeck_archive_url(storm_id))
        if body is None:
            raise SystemExit(f"no archived b-deck for {storm_id}")
        text = gzip.decompress(body).decode("utf-8", errors="replace")
        kept: list[str] = []
        for line in text.splitlines():
            fields = line.split(",")
            if len(fields) < 3:
                continue
            try:
                when = datetime.strptime(fields[2].strip(), "%Y%m%d%H").replace(tzinfo=UTC)
            except ValueError:
                continue
            if start <= when <= end:
                kept.append(line)
        trimmed = "\n".join(kept) + "\n"
        self.write(bundle.bdeck_path(storm_id), trimmed)
        return [(f.lat, f.lon) for f in parse_bdeck(trimmed.encode()).fixes]

    # ---- NDBC -------------------------------------------------------------------------------------------------

    async def buoys(
        self,
        track: Sequence[tuple[float, float]],
        wanted: str,
        start: datetime,
        end: datetime,
        history: timedelta,
        limit: int,
    ) -> None:
        body = await self.get(NDBC_STATIONS_URL)
        if body is None:
            raise SystemExit("NDBC station catalog not found")
        catalog_text = body.decode("utf-8", errors="replace")
        stations = {s.id: s for s in parse_stations(catalog_text).items}
        if wanted == "auto":
            ranked = sorted(
                (min(haversine_nm((s.lat, s.lon), p) for p in track), s.id)
                for s in stations.values()
                if s.type in {"buoy", "fixed"}
            )
            candidates = [sid for distance, sid in ranked if distance <= NOW_RADIUS_NM][: limit * 3]
        else:
            candidates = [s.strip().upper() for s in wanted.split(",") if s.strip()]
        chosen: list[str] = []
        for station_id in candidates:
            if len(chosen) >= limit:
                break
            if station_id not in stations:
                log(f"buoy {station_id}: not in the catalog")
                continue
            data = await self.get(yearly_url(station_id, start.year))
            if data is None:
                log(f"buoy {station_id}: no {start.year} file")
                continue
            kept = self._rows(decompress(data).splitlines(), start - history, end)
            rows = len(kept) - 2
            if rows < 24:
                log(f"buoy {station_id}: nothing in the window")
                continue
            log(f"buoy {station_id}: {rows} rows")
            self.write(bundle.ndbc_path(station_id), "\n".join(kept) + "\n")
            chosen.append(station_id)
        self.write(bundle.STATIONS_XML, self._catalog_xml(catalog_text, set(chosen)))

    @staticmethod
    def _rows(lines: Sequence[str], start: datetime, end: datetime) -> list[str]:
        kept = [line for line in lines if line.startswith("#")][:2]
        for line in lines:
            tokens = line.split()
            if line.startswith("#") or len(tokens) < 5:
                continue
            try:
                year = int(tokens[0])
                year += 2000 if year < 100 else 0
                when = datetime(year, int(tokens[1]), int(tokens[2]), int(tokens[3]), int(tokens[4]), tzinfo=UTC)
            except ValueError:
                continue
            if start <= when <= end:
                kept.append(line)
        return kept

    @staticmethod
    def _catalog_xml(text: str, chosen: set[str]) -> str:
        """The recorded stations as a catalog, minus the "reported in the last 8 hours" flags (they describe today)."""
        elements = []
        for match in re.finditer(r"<station\b[^>]*?/>|<station\b[^>]*?>.*?</station>", text, re.DOTALL):
            element = match.group(0)
            id_match = re.search(r'\bid="([^"]*)"', element)
            if id_match is None or id_match.group(1).upper() not in chosen:
                continue
            element = re.sub(r'\s(?:met|currents|waterquality|dart)="[^"]*"', "", element)
            elements.append("  " + element)
        return '<?xml version="1.0" encoding="UTF-8"?>\n<stations>\n' + "\n".join(elements) + "\n</stations>\n"

    # ---- CO-OPS -----------------------------------------------------------------------------------------------

    async def gauges(
        self, track: Sequence[tuple[float, float]], wanted: str, start: datetime, end: datetime, limit: int
    ) -> None:
        if wanted == "none":
            return
        payloads: dict[str, dict[str, Any]] = {}
        located: dict[str, dict[str, tuple[float, float, bool]]] = {}
        for listing, kind in LISTING_TYPES.items():
            body = await self.get(COOPS_STATIONS_URL, params={"type": kind})
            if body is None:
                raise SystemExit(f"CO-OPS {kind} listing not found")
            payloads[listing] = json.loads(body)
            located[listing] = {s.id: (s.lat, s.lon, s.great_lakes) for s in parse_tide_stations(body, listing).items}
        water = located["water_level"]
        if wanted == "auto":
            ranked = sorted(
                (min(haversine_nm((lat, lon), p) for p in track), sid)
                for sid, (lat, lon, lakes) in water.items()
                if not lakes
            )
            candidates = [sid for distance, sid in ranked if distance <= TIDE_RADIUS_NM][: limit * 3]
        else:
            candidates = [s.strip() for s in wanted.split(",") if s.strip()]
        chosen: list[str] = []
        for station_id in candidates:
            if len(chosen) >= limit:
                break
            got = False
            for product in bundle.TIDE_PRODUCTS:
                if product not in ("water_level", "predictions") and station_id not in located["met"]:
                    continue
                params = datagetter_params(product, station_id, begin=start, end=end)  # type: ignore[arg-type]
                body = await self.get(DATAGETTER_URL, params=params)
                payload = json.loads(body) if body else {}
                rows_key = "predictions" if product == "predictions" else "data"
                if not isinstance(payload, dict) or "error" in payload or not payload.get(rows_key):
                    log(f"gauge {station_id} {product}: no data")
                    continue
                log(f"gauge {station_id} {product}: {len(payload[rows_key])} rows")
                self.write(bundle.coops_path(station_id, product), json.dumps(payload, separators=(",", ":")))
                got = got or product == "water_level"
            if got:
                chosen.append(station_id)
        for listing, payload in payloads.items():
            slim = [
                {key: entry.get(key) for key in ("id", "name", "lat", "lng", "state", "greatlakes")}
                for entry in payload.get("stations", [])
                if str(entry.get("id")) in chosen
            ]
            self.write(
                bundle.coops_listing_path(listing),
                json.dumps({"count": len(slim), "stations": slim}, separators=(",", ":")),
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("storm_id", help="for example AL052025")
    parser.add_argument("--from", dest="start", required=True, type=parse_moment, help="first moment, UTC")
    parser.add_argument("--to", dest="end", required=True, type=parse_moment, help="last moment, UTC")
    parser.add_argument("--stations", default="auto", help='"auto" or a comma separated list of NDBC ids')
    parser.add_argument("--max-stations", type=int, default=8)
    parser.add_argument("--tide-gauges", default="auto", help='"auto", "none" or a comma separated list of CO-OPS ids')
    parser.add_argument("--max-gauges", type=int, default=3)
    parser.add_argument("--graphics", type=int, default=2, help="how many cone graphics to keep")
    parser.add_argument("--history-hours", type=float, default=24.0, help="buoy rows kept before --from")
    parser.add_argument("--track-hours", type=float, default=72.0, help="best track rows kept before --from")
    parser.add_argument("--name", help="bundle name (default: the storm name and year)")
    parser.add_argument("--out", type=Path, required=True, help="the bundle directory to write")
    parser.add_argument("--delay", type=float, default=0.25, help="seconds between requests")
    return parser


async def record(args: argparse.Namespace) -> None:
    storm_id = ids.normalize_storm_id(args.storm_id)
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    async with new_client() as http:
        recorder = Recorder(http, out, args.delay)
        advisories = await recorder.advisories(storm_id, args.start, args.end)
        if not advisories:
            raise SystemExit("no advisories in the window")
        await recorder.gis(storm_id, advisories)
        graphics = await recorder.graphics(storm_id, advisories, args.graphics)
        track = await recorder.best_track(storm_id, args.start, args.end, timedelta(hours=args.track_hours))
        await recorder.buoys(
            track, args.stations, args.start, args.end, timedelta(hours=args.history_hours), args.max_stations
        )
        await recorder.gauges(track, args.tide_gauges, args.start, args.end, args.max_gauges)
    first = (out / bundle.text_path(storm_id, ids.format_adv_num(advisories[0]), "tcm")).read_text(encoding="utf-8")
    name_match = re.search(r"(?:HURRICANE|STORM|DEPRESSION|CYCLONE)\s+([A-Z]+)\s+FORECAST/ADVISORY", first)
    storm_name = name_match.group(1).title() if name_match else storm_id
    bin_match = re.search(r"TCM(AT|EP|CP)(\d)", first)
    bin_name = f"{bin_match.group(1)}{bin_match.group(2)}" if bin_match else "AT1"
    parsed = ids.parse_storm_id(storm_id)
    bundle.write_manifest(
        out,
        bundle.Manifest(
            name=args.name or f"{storm_name.lower()}{parsed.year}",
            title=f"{storm_name} ({parsed.year})",
            storm_id=storm_id,
            storm_name=storm_name,
            bin=bin_name,
            start=args.start,
            end=args.end,
            graphics=tuple(graphics),
        ),
    )
    log(f"wrote {out}")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        asyncio.run(record(args))
    except FetchError as exc:
        print(f"record_storm: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
