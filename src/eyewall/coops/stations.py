"""The CO-OPS metadata API station lists.

`stations.json?type=waterlevels` lists the tide gauges (about 300) and `?type=met` the stations with wind and air
pressure (about 300). Each entry is large because it nests links to its sensors, datums and benchmarks, and none of that
is needed here. The longitude field is `lng`, not `lon`; coordinates arrive as numbers but are coerced from strings in
case that changes. Which listing a station came from becomes its `products`; merge the lists to learn both.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import replace
from typing import Any

from eyewall.models.obs import Parsed, TideStation

WATER_LEVEL = "water_level"
MET = "met"
LISTING_TYPES = {WATER_LEVEL: "waterlevels", MET: "met"}


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_tide_stations(text: str | bytes, product: str = WATER_LEVEL) -> Parsed[TideStation]:
    """Parse one station listing, tagging every station with the product that listing stands for.

    Entries with no id or position are skipped and counted. Anything that is not the expected JSON gives an empty
    result with a message instead of raising.
    """
    try:
        payload = json.loads(text)
    except ValueError:
        return Parsed(message="invalid station JSON")
    entries = payload.get("stations") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return Parsed(message="station JSON has no station list")
    stations: list[TideStation] = []
    skipped = 0
    for entry in entries:
        if not isinstance(entry, dict):
            skipped += 1
            continue
        station_id = str(entry.get("id") or "").strip()
        lat = _number(entry.get("lat"))
        lon = _number(entry["lng"] if "lng" in entry else entry.get("lon"))
        if not station_id or lat is None or lon is None:
            skipped += 1
            continue
        stations.append(
            TideStation(
                id=station_id,
                name=str(entry.get("name") or "").strip(),
                lat=lat,
                lon=lon,
                state=str(entry.get("state") or "").strip(),
                great_lakes=entry.get("greatlakes") is True,
                products=frozenset({product}),
            )
        )
    return Parsed(tuple(stations), skipped)


def merge_tide_stations(listings: Iterable[Parsed[TideStation]]) -> tuple[TideStation, ...]:
    """One station per id across several listings, with the products of every listing it appeared in."""
    merged: dict[str, TideStation] = {}
    for listing in listings:
        for station in listing.items:
            known = merged.get(station.id)
            if known is None:
                merged[station.id] = station
            else:
                merged[station.id] = replace(known, products=known.products | station.products)
    return tuple(merged.values())
