"""Parsers for NHC GIS zips: forecast (cone, points, track, warnings), wind radii and best track.

Shapefiles are read with pyshp straight from the zip bytes, by layer name suffix and field name:

- forecast zip `al052025_5day_030.zip`: layers `*_5day_pts` (TAU, MAXWIND, GUST, MSLP, TCDVLP, DATELBL, VALIDTIME...),
  `*_5day_lin` (the track line), `*_5day_pgn` (the cone polygon) and `*_ww_wwlin` (coastal watch and warning lines,
  field TCWW). Intermediate advisories use an `A` suffix in the zip name and in ADVISNUM (`30A`).
- radii zip `al052025_fcst_030.zip`: `*_forecastradii` and `*_initialradii` polygons with RADII, TAU and the four radii.
- best track zip `al052025_best_track.zip`: `*_pts` and `*_lin`.

A layer that is missing, empty or unreadable comes back empty. NOAA fills unknown numbers with 9999. Longitudes are
wrapped to (-180, 180]: across the dateline the layers disagree (the track line continues to -182 while the cone
continues to 182), so every vertex is normalised on the way in.
"""

from __future__ import annotations

import io
import math
import re
import struct
import zipfile
import zlib
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import shapefile

from eyewall.geo import wrap_lon
from eyewall.models.forecast import ForecastGis, ForecastPoint
from eyewall.models.track import BestTrackGis, BestTrackPoint, BestTrackSegment
from eyewall.models.watches import WatchWarningSegment
from eyewall.models.wind import QuadrantRadii, RadiiPolygon, Ring, WindRadiiGis
from eyewall.palette import WatchWarning
from eyewall.providers.base import ParseError
from eyewall.providers.nhc.ids import parse_adv_num
from eyewall.providers.nhc.times import parse_header_time, resolve_day_time

_STORM_STEM = re.compile(r"(?P<id>(?:al|ep|cp)\d{6})", re.IGNORECASE)
_TCWW_KINDS: dict[str, WatchWarning] = {
    "TWA": WatchWarning.TROPICAL_STORM_WATCH,
    "TWR": WatchWarning.TROPICAL_STORM_WARNING,
    "HWA": WatchWarning.HURRICANE_WATCH,
    "HWR": WatchWarning.HURRICANE_WARNING,
}
# A damaged layer is dropped, not fatal: bad shapefile contents, or a zip member that cannot be inflated.
_READ_ERRORS = (
    shapefile.ShapefileException,
    struct.error,
    ValueError,
    KeyError,
    IndexError,
    OverflowError,
    zipfile.BadZipFile,
    zlib.error,
    EOFError,
    NotImplementedError,
    RuntimeError,
)


# The largest layer member read into memory. A real layer is well under 1 MB; the cap stops a zip bomb, and a layer
# over it is dropped like any other unreadable layer.
MAX_MEMBER_BYTES = 32 * 1024 * 1024


def _read_member(archive: zipfile.ZipFile, name: str) -> bytes:
    with archive.open(name) as handle:
        data = handle.read(MAX_MEMBER_BYTES + 1)
    if len(data) > MAX_MEMBER_BYTES:
        raise ValueError(f"zip member {name!r} is larger than {MAX_MEMBER_BYTES} bytes")
    return data


@dataclass(frozen=True, slots=True)
class Feature:
    """One shape with its attributes (keys upper-cased). `parts` are the rings or lines as (lat, lon) tuples."""

    attrs: Mapping[str, Any]
    parts: tuple[tuple[tuple[float, float], ...], ...]


def _open_zip(data: bytes) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ParseError(f"not a zip file: {exc}") from exc


def read_layer_names(data: bytes) -> tuple[str, ...]:
    """The shapefile layer stems in a zip, lower-cased."""
    with _open_zip(data) as archive:
        return tuple(sorted(_stems(archive)))


def _stems(archive: zipfile.ZipFile) -> dict[str, str]:
    """Layer stem (lower case, no directory) to the zip member prefix, for every .shp in the archive."""
    return {
        name.rsplit("/", 1)[-1][:-4].lower(): name[:-4] for name in archive.namelist() if name.lower().endswith(".shp")
    }


def read_features(archive: zipfile.ZipFile, prefix: str) -> list[Feature]:
    """Read one layer. Returns an empty list when the layer is unreadable."""
    members = {name.lower(): name for name in archive.namelist()}

    def member(extension: str) -> str | None:
        return members.get(f"{prefix}.{extension}".lower())

    shp, dbf, shx = member("shp"), member("dbf"), member("shx")
    if shp is None:
        return []
    features: list[Feature] = []
    try:
        reader = shapefile.Reader(
            shp=io.BytesIO(_read_member(archive, shp)),
            dbf=io.BytesIO(_read_member(archive, dbf)) if dbf else None,
            shx=io.BytesIO(_read_member(archive, shx)) if shx else None,
        )
        fields = [field[0].upper() for field in reader.fields[1:]] if dbf else []
        for shape_record in _iter_shape_records(reader, bool(dbf)):
            shape, record = shape_record
            attrs = dict(zip(fields, record, strict=False)) if record is not None else {}
            features.append(Feature(attrs, _parts(shape)))
    except _READ_ERRORS:
        return features
    return features


def _iter_shape_records(reader: Any, has_records: bool) -> Iterator[tuple[Any, list[Any] | None]]:
    if has_records:
        for item in reader.iterShapeRecords():
            yield item.shape, list(item.record)
    else:
        for shape in reader.iterShapes():
            yield shape, None


def _parts(shape: Any) -> tuple[tuple[tuple[float, float], ...], ...]:
    points = getattr(shape, "points", None) or []
    if not points:
        return ()
    starts = list(getattr(shape, "parts", None) or [0])
    ends = [*starts[1:], len(points)]
    return tuple(
        tuple((float(y), wrap_lon(float(x))) for x, y in points[start:end])
        for start, end in zip(starts, ends, strict=True)
        if end > start
    )


def read_layer_group(data: bytes, wanted: Mapping[str, str]) -> dict[str, list[Feature]]:
    """Read the layers whose stem matches a pattern.

    `wanted` maps a result key to a regular expression searched in the lower-case layer stem, for example
    `{"points": r"_5day_pts$"}`. A key whose layer is absent comes back as an empty list.
    """
    with _open_zip(data) as archive:
        stems = _stems(archive)
        result: dict[str, list[Feature]] = {}
        for key, pattern in wanted.items():
            stem = next((s for s in sorted(stems) if re.search(pattern, s)), None)
            result[key] = read_features(archive, stems[stem]) if stem else []
        return result


def _number(value: Any, *, fill: float = 9999) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if not math.isfinite(number) or number >= fill else number


def _int(value: Any, *, fill: float = 9999) -> int | None:
    number = _number(value, fill=fill)
    return None if number is None else round(number)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _ymdh(value: Any) -> datetime | None:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    digits = str(int(value)) if isinstance(value, float | int) else str(value or "").strip()
    if len(digits) < 10 or not digits[:10].isdigit():
        return None
    try:
        return datetime(int(digits[:4]), int(digits[4:6]), int(digits[6:8]), int(digits[8:10]), tzinfo=UTC)
    except ValueError:
        return None


def _storm_id(zip_stems: tuple[str, ...]) -> str | None:
    for stem in zip_stems:
        match = _STORM_STEM.search(stem)
        if match:
            return match["id"].lower()
    return None


# ---- forecast zip -------------------------------------------------------------------------------------------------


def parse_forecast_zip(data: bytes) -> ForecastGis:
    """Parse a `_5day` zip into forecast points, the track line, the cone and the watch and warning lines."""
    layers = read_layer_group(
        data, {"pts": r"_5day_pts$", "lin": r"_5day_lin$", "pgn": r"_5day_pgn$", "ww": r"_ww_wwlin$"}
    )
    meta: Mapping[str, Any] = next((f.attrs for key in ("pgn", "lin", "ww", "pts") for f in layers[key][:1]), {})
    adv_date = _text(meta.get("ADVDATE"))
    issued = parse_header_time(adv_date) if adv_date else None
    points: list[ForecastPoint] = []
    for feature in layers["pts"]:
        if not feature.parts and not feature.attrs:
            continue
        lat, lon = _point(feature)
        if lat is None or lon is None:
            continue
        valid_text = _text(feature.attrs.get("VALIDTIME"))
        valid = None
        if valid_text and issued is not None and "/" in valid_text:
            day, _, hhmm = valid_text.partition("/")
            if day.isdigit() and len(hhmm) >= 4 and hhmm[:4].isdigit():
                valid = resolve_day_time(int(day), int(hhmm[:2]), int(hhmm[2:4]), issued)
        tau = _int(feature.attrs.get("TAU"))
        points.append(
            ForecastPoint(
                tau=tau if tau is not None else 0,
                lat=lat,
                lon=lon,
                max_wind_kt=_int(feature.attrs.get("MAXWIND")),
                gust_kt=_int(feature.attrs.get("GUST")),
                mslp_mb=_int(feature.attrs.get("MSLP")),
                storm_type=_text(feature.attrs.get("STORMTYPE")),
                development=_text(feature.attrs.get("TCDVLP")),
                saffir_simpson=_int(feature.attrs.get("SSNUM")),
                date_label=_text(feature.attrs.get("DATELBL")),
                local_label=_text(feature.attrs.get("FLDATELBL")),
                timezone=_text(feature.attrs.get("TIMEZONE")),
                valid=valid,
                direction_deg=_int(feature.attrs.get("TCDIR"), fill=999),
                speed_kt=_int(feature.attrs.get("TCSPD"), fill=999),
            )
        )
    points.sort(key=lambda p: p.tau)
    segments = tuple(
        WatchWarningSegment(code, _TCWW_KINDS.get(code), part)
        for feature in layers["ww"]
        for part in feature.parts
        if (code := (_text(feature.attrs.get("TCWW")) or "").upper())
    )
    return ForecastGis(
        storm_name=_text(meta.get("STORMNAME")),
        storm_type=_text(meta.get("STORMTYPE")),
        adv_num=parse_adv_num(meta.get("ADVISNUM")),
        adv_date_text=adv_date,
        issued=issued,
        points=tuple(points),
        track=tuple(part for feature in layers["lin"] for part in feature.parts),
        cone=tuple(ring for feature in layers["pgn"] for ring in feature.parts),
        watch_warnings=segments,
    )


def _point(feature: Feature) -> tuple[float | None, float | None]:
    if feature.parts and feature.parts[0]:
        lat, lon = feature.parts[0][0]
        return lat, lon
    lat_attr, lon_attr = _number(feature.attrs.get("LAT")), _number(feature.attrs.get("LON"))
    return lat_attr, (wrap_lon(lon_attr) if lon_attr is not None else None)


# ---- wind radii zip -----------------------------------------------------------------------------------------------


def _radii_polygons(features: list[Feature]) -> tuple[RadiiPolygon, ...]:
    polygons: list[RadiiPolygon] = []
    for feature in features:
        kt = _int(feature.attrs.get("RADII"))
        if kt is None or not feature.parts:
            continue
        rings: tuple[Ring, ...] = feature.parts
        polygons.append(
            RadiiPolygon(
                kt=kt,
                tau=_int(feature.attrs.get("TAU")),
                valid=_ymdh(feature.attrs.get("VALIDTIME")),
                synoptic=_ymdh(feature.attrs.get("SYNOPTIME")),
                radii=QuadrantRadii(
                    _int(feature.attrs.get("NE")),
                    _int(feature.attrs.get("SE")),
                    _int(feature.attrs.get("SW")),
                    _int(feature.attrs.get("NW")),
                ),
                rings=rings,
            )
        )
    return tuple(polygons)


def parse_radii_zip(data: bytes) -> WindRadiiGis:
    """Parse a `_fcst` zip: the initial and forecast 34, 50 and 64 kt wind radii polygons."""
    layers = read_layer_group(data, {"initial": r"initialradii$", "forecast": r"forecastradii$"})
    first = next((f for key in ("initial", "forecast") for f in layers[key][:1]), None)
    attrs: Mapping[str, Any] = first.attrs if first else {}
    storm_id = _text(attrs.get("STORMID"))
    return WindRadiiGis(
        storm_id=storm_id.lower() if storm_id else None,
        adv_num=parse_adv_num(attrs.get("ADVNUM")),
        initial=_radii_polygons(layers["initial"]),
        forecast=_radii_polygons(layers["forecast"]),
    )


# ---- best track zip -----------------------------------------------------------------------------------------------


def parse_best_track_zip(data: bytes) -> BestTrackGis:
    """Parse a best track zip: the `_pts` fixes and the `_lin` segments colored by storm type."""
    with _open_zip(data) as archive:
        stems = tuple(sorted(_stems(archive)))
    layers = read_layer_group(data, {"pts": r"(?<!_5day)_pts$", "lin": r"(?<!_5day)_lin$"})
    points: list[BestTrackPoint] = []
    for feature in layers["pts"]:
        lat, lon = _point(feature)
        if lat is None or lon is None:
            continue
        points.append(
            BestTrackPoint(
                time=_ymdh(feature.attrs.get("DTG")),
                lat=lat,
                lon=lon,
                storm_name=_text(feature.attrs.get("STORMNAME")),
                storm_type=_text(feature.attrs.get("STORMTYPE")),
                intensity_kt=_int(feature.attrs.get("INTENSITY")),
                mslp_mb=_int(feature.attrs.get("MSLP")),
                saffir_simpson=_int(feature.attrs.get("SS")),
            )
        )
    segments = tuple(
        BestTrackSegment(_text(feature.attrs.get("STORMTYPE")), _int(feature.attrs.get("SS")), part)
        for feature in layers["lin"]
        for part in feature.parts
    )
    return BestTrackGis(_storm_id(stems), tuple(points), segments)
