"""Parser for CurrentStorms.json, the list of active storms.

The feed is loosely typed, and the 2019 reference document is wrong in several places. What is observed:

- `id` is lower case (`al052025`); key storms by it. `binNumber` (`AT1`..`CP5`) is reused within a season, and a
  storm that crosses 140 W keeps its `ep` id but moves to a `CP` bin.
- `intensity` (knots) and `pressure` (millibars) are strings. `latitude`/`longitude` are strings like `17.1N`; the
  `…Numeric` twins are numbers. `movementSpeed` is in miles per hour, unlike the advisory text.
- Every product and GIS object can be null, and `advNum` is a string such as `018a` for an intermediate advisory.
- `{"activeStorms": []}` is the quiet answer.

Entries without an `id`, and repeats of one already seen (the first wins), are skipped and counted.
A missing or extra field never fails the parse.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

from eyewall.geo import wrap_lon
from eyewall.models.storm import (
    Classification,
    CurrentStorms,
    GisRef,
    ProductRef,
    Storm,
    WindProbabilityGisRef,
)
from eyewall.providers.base import ParseError
from eyewall.providers.nhc.ids import parse_adv_num
from eyewall.providers.nhc.times import parse_iso

_COORD_TEXT = re.compile(r"^\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<hemisphere>[NSEW])\s*$", re.IGNORECASE)


def _number(value: Any) -> float | None:
    """A number from a JSON number or a numeric string; None for empty, dash or non-numeric text."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value) if isinstance(value, int | float) else float(str(value).strip())
    except (ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _int(value: Any) -> int | None:
    number = _number(value)
    return None if number is None else round(number)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coordinate(numeric: Any, text: Any) -> float | None:
    """The numeric twin when present, else the `17.1N` string. Southern and western values are negative."""
    value = _number(numeric)
    if value is not None:
        return value
    match = _COORD_TEXT.match(str(text or ""))
    if match is None:
        return None
    parsed = float(match["value"])
    return -parsed if match["hemisphere"].upper() in {"S", "W"} else parsed


def _product(obj: Any) -> ProductRef | None:
    if not isinstance(obj, dict):
        return None
    return ProductRef(
        adv_num=parse_adv_num(obj.get("advNum")),
        issued=parse_iso(obj.get("issuance")),
        updated=parse_iso(obj.get("fileUpdateTime")),
        url=_text(obj.get("url")),
    )


def _gis(obj: Any) -> GisRef | None:
    if not isinstance(obj, dict):
        return None
    return GisRef(
        adv_num=parse_adv_num(obj.get("advNum")),
        issued=parse_iso(obj.get("issuance")),
        updated=parse_iso(obj.get("fileUpdateTime")),
        zip_url=_text(obj.get("zipFile")),
        kmz_url=_text(obj.get("kmzFile")),
        kml_url=_text(obj.get("kmlFile") or obj.get("peakSurgeKMLFile")),
    )


def _wsp_gis(obj: Any) -> WindProbabilityGisRef | None:
    if not isinstance(obj, dict):
        return None
    return WindProbabilityGisRef(
        issued=parse_iso(obj.get("issuance")),
        updated=parse_iso(obj.get("fileUpdateTime")),
        zip_5km_url=_text(obj.get("zipFile5km")),
        zip_half_degree_url=_text(obj.get("zipFile0p5deg")),
        kmz_34kt_url=_text(obj.get("kmzFile34kt")),
        kmz_50kt_url=_text(obj.get("kmzFile50kt")),
        kmz_64kt_url=_text(obj.get("kmzFile64kt")),
    )


def _classification(value: Any) -> Classification:
    try:
        return Classification(str(value or "").strip().upper())
    except ValueError:
        return Classification.UNKNOWN


def _storm(entry: dict[str, Any]) -> Storm | None:
    storm_id = _text(entry.get("id"))
    if storm_id is None:
        return None
    lon = _coordinate(entry.get("longitudeNumeric"), entry.get("longitude"))
    return Storm(
        id=storm_id.lower(),
        bin_number=(_text(entry.get("binNumber")) or "").upper() or None,
        name=_text(entry.get("name")) or "",
        classification=_classification(entry.get("classification")),
        classification_text=_text(entry.get("classification")) or "",
        intensity_kt=_int(entry.get("intensity")),
        pressure_mb=_int(entry.get("pressure")),
        lat=_coordinate(entry.get("latitudeNumeric"), entry.get("latitude")),
        lon=wrap_lon(lon) if lon is not None else None,
        movement_dir_deg=_int(entry.get("movementDir")),
        movement_speed_mph=_number(entry.get("movementSpeed")),
        last_update=parse_iso(entry.get("lastUpdate")),
        public_advisory=_product(entry.get("publicAdvisory")),
        forecast_advisory=_product(entry.get("forecastAdvisory")),
        wind_speed_probabilities=_product(entry.get("windSpeedProbabilities")),
        forecast_discussion=_product(entry.get("forecastDiscussion")),
        forecast_graphics=_product(entry.get("forecastGraphics")),
        forecast_track=_gis(entry.get("forecastTrack")),
        track_cone=_gis(entry.get("trackCone")),
        initial_wind_extent=_gis(entry.get("initialWindExtent")),
        forecast_wind_radii=_gis(entry.get("forecastWindRadiiGIS")),
        wind_watches_warnings=_gis(entry.get("windWatchesWarnings")),
        best_track=_gis(entry.get("bestTrackGIS")),
        earliest_arrival_ts_winds=_gis(entry.get("earliestArrivalTimeTSWindsGIS")),
        most_likely_ts_winds=_gis(entry.get("mostLikelyTimeTSWindsGIS")),
        wind_speed_probabilities_gis=_wsp_gis(entry.get("windSpeedProbabilitiesGIS")),
        storm_surge_watch_warning=_gis(entry.get("stormSurgeWatchWarningGIS")),
        potential_storm_surge_flooding=_gis(entry.get("potentialStormSurgeFloodingGIS")),
        peak_surge=_gis(entry.get("peakSurgeKML")),
    )


def parse_current_storms(data: bytes | str) -> CurrentStorms:
    """Parse CurrentStorms.json. Raises ParseError when the payload is not a JSON object."""
    try:
        document = json.loads(data)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ParseError(f"CurrentStorms is not JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise ParseError("CurrentStorms is not a JSON object")
    entries = document.get("activeStorms")
    if not isinstance(entries, list):
        return CurrentStorms()
    storms: dict[str, Storm] = {}
    skipped = 0
    for entry in entries:
        storm = _storm(entry) if isinstance(entry, dict) else None
        if storm is None or storm.id in storms:  # no id, or an id already seen: the first entry wins
            skipped += 1
        else:
            storms[storm.id] = storm
    return CurrentStorms(tuple(storms.values()), skipped)
