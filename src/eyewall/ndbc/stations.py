"""`activestations.xml`: the NDBC station catalog (about 1350 stations, 270 KB).

Only some of the stations measure weather, and the `met`, `currents`, `waterquality` and `dart` flags say which ones
reported that kind of data in the last 8 hours. A listed station may still be dark, so a catalog entry is never proof
that its data file exists. Ids are lower case for C-MAN stations in the XML and upper case in file names; they are
normalised to upper case once, here, and can be seven characters long. Some entries omit the flags entirely.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Mapping

from eyewall.models.obs import Parsed, Station
from eyewall.ndbc.table import normalize_station_id
from eyewall.textclean import printable

_DECLARATION = re.compile(r"^\s*<\?xml[^>]*\?>")
_DTD = re.compile(rb"<!(DOCTYPE|ENTITY)", re.IGNORECASE)


def _float(value: str | None) -> float | None:
    try:
        return None if value is None else float(value)
    except ValueError:
        return None


def _flag(attributes: Mapping[str, str], name: str) -> bool | None:
    value = attributes.get(name, "").strip().lower()
    if value == "y":
        return True
    if value == "n":
        return False
    return None


def parse_stations(data: str | bytes) -> Parsed[Station]:
    """Parse the catalog. Entries without an id or a position are skipped and counted; bad XML gives a message."""
    payload = _DECLARATION.sub("", data).encode() if isinstance(data, str) else data
    if _DTD.search(payload):  # the catalog never has a DTD; refusing one rules out entity-expansion tricks
        return Parsed(message="station XML has a DTD; refusing to parse it")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        return Parsed(message=f"invalid station XML: {exc}")
    stations: list[Station] = []
    skipped = 0
    for element in root.iter("station"):
        attributes = element.attrib
        station_id = normalize_station_id(attributes.get("id", ""))
        lat, lon = _float(attributes.get("lat")), _float(attributes.get("lon"))
        if not station_id or lat is None or lon is None:
            skipped += 1
            continue
        stations.append(
            Station(
                id=station_id,
                name=printable(attributes.get("name", "")).strip(),
                lat=lat,
                lon=lon,
                type=attributes.get("type", "").strip(),
                owner=attributes.get("owner", "").strip(),
                program=attributes.get("pgm", "").strip(),
                elevation_m=_float(attributes.get("elev")),
                met=_flag(attributes, "met"),
                currents=_flag(attributes, "currents"),
                water_quality=_flag(attributes, "waterquality"),
                dart=_flag(attributes, "dart"),
            )
        )
    return Parsed(tuple(stations), skipped)
