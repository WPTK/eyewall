"""Parser for ATCF best track files (b-decks) and the `btk` directory listing.

A b-deck has no header row, so the columns are read by their documented ATCF positions, from the left: basin, cyclone
number, date-time group (YYYYMMDDHH), technique number, technique (BEST), forecast hour, latitude and longitude in
tenths of a degree with a hemisphere letter, then max wind, pressure, level (DB, LO, TD, TS, HU...), the wind radius
threshold with its quadrant code and four radii, pressure and radius of the outer closed isobar, radius of max wind,
gusts, eye diameter, subregion, max seas, forecaster initials, direction, speed and storm name. Later columns hold
free-form genesis notes and are ignored. A line with fewer columns than it needs is skipped and counted.

Observed behaviours the code handles:

- Up to three lines carry one time, one per radii threshold (34, 50, 64 kt); they merge into one fix.
- Early rows are `DB`/`LO` with name `INVEST` or `GENESISnnn`, and the storm keeps its number when it is named.
- Invests are numbers 90 to 99; 80 to 89 are training systems.
- Longitudes can be east (`1771E`), near the dateline.
- Zero is the file's way of saying unknown for wind, pressure, radii of max wind, gusts and eye size.
"""

from __future__ import annotations

import re
import zlib
from datetime import UTC, datetime

from eyewall.models.track import BDeckFile, BestTrack, BestTrackFix
from eyewall.models.wind import QuadrantRadii, WindRadii
from eyewall.providers.base import ParseError

_GZIP_MAGIC = b"\x1f\x8b"
MAX_BDECK_BYTES = 32 * 1024 * 1024  # a long storm's b-deck is about 1 MB; this stops a decompression bomb
_COORD = re.compile(r"^(?P<value>\d+(?:\.\d+)?)(?P<hemisphere>[NSEW])$")
_LISTING = re.compile(
    r'<a href="(?P<name>b(?P<basin>al|ep|cp)(?P<number>\d{2})(?P<year>\d{4})\.dat)">[^<]*</a>\s*'
    r"(?:(?P<date>\d{4}-\d{2}-\d{2} \d{2}:\d{2})\s+)?(?P<size>[\d.]+[KMG]?|-)?",
    re.IGNORECASE,
)


def _coordinate(text: str) -> float | None:
    """`165N` is 16.5; `231W` is -23.1; `1771E` is 177.1. Values with a decimal point are taken as degrees."""
    match = _COORD.match(text.strip().upper())
    if match is None:
        return None
    raw = match["value"]
    value = float(raw) if "." in raw else int(raw) / 10.0
    return value if match["hemisphere"] in {"N", "E"} else -value


def _int(fields: list[str], index: int, *, zero_is_missing: bool = False) -> int | None:
    if index >= len(fields):
        return None
    try:
        value = int(float(fields[index]))
    except ValueError:
        return None
    if value < 0 or (zero_is_missing and value == 0):
        return None
    return value


def _time(text: str) -> datetime | None:
    digits = text.strip()
    if len(digits) < 10 or not digits[:10].isdigit():
        return None
    try:
        return datetime(int(digits[0:4]), int(digits[4:6]), int(digits[6:8]), int(digits[8:10]), tzinfo=UTC)
    except ValueError:
        return None


def _quadrants(fields: list[str]) -> QuadrantRadii | None:
    code = fields[12].upper() if len(fields) > 12 else ""
    values = [_int(fields, index) for index in (13, 14, 15, 16)]
    if code == "AAA":  # a full circle: only the first radius is filled in
        return QuadrantRadii(values[0], values[0], values[0], values[0])
    if code == "NEQ":
        return QuadrantRadii(values[0], values[1], values[2], values[3])
    return None


def _gunzip(data: bytes) -> bytes:
    """Decompress a gzipped b-deck, never producing more than `MAX_BDECK_BYTES`. A cut-off, corrupt or oversized body is
    a ParseError, like any other body that cannot be read."""
    inflater = zlib.decompressobj(wbits=31)
    try:
        raw = inflater.decompress(data, MAX_BDECK_BYTES + 1)
        if len(raw) > MAX_BDECK_BYTES or inflater.unconsumed_tail:
            raise ParseError(f"b-deck larger than {MAX_BDECK_BYTES // (1024 * 1024)} MB once decompressed")
        if not inflater.eof:
            raise ParseError("b-deck gzip data is cut off")
    except zlib.error as exc:
        raise ParseError(f"b-deck is not valid gzip data: {exc}") from exc
    return raw


def parse_bdeck(data: bytes | str) -> BestTrack:
    """Parse a b-deck (plain or gzipped). Raises ParseError when no line holds a usable fix."""
    if isinstance(data, bytes):
        raw = _gunzip(data) if data[:2] == _GZIP_MAGIC else data
        text = raw.decode("utf-8", errors="replace")
    else:
        text = data
    basin_code = ""
    number = 0
    skipped = 0
    order: list[datetime] = []
    firsts: dict[datetime, tuple[list[str], float, float]] = {}
    radii: dict[datetime, dict[int, QuadrantRadii]] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        fields = [part.strip() for part in line.split(",")]
        when = _time(fields[2]) if len(fields) > 2 else None
        lat = _coordinate(fields[6]) if len(fields) > 7 else None
        lon = _coordinate(fields[7]) if len(fields) > 7 else None
        if len(fields) < 11 or when is None or lat is None or lon is None or not fields[1].isdigit():
            skipped += 1
            continue
        if fields[4].upper() != "BEST":
            skipped += 1
            continue
        if not basin_code:
            basin_code, number = fields[0].upper(), int(fields[1])
        if when not in firsts:
            firsts[when] = (fields, lat, lon)
            radii[when] = {}
            order.append(when)
        threshold = _int(fields, 11)
        if threshold in {34, 50, 64}:
            quadrants = _quadrants(fields)
            if quadrants is not None:
                radii[when].setdefault(threshold, quadrants)
    if not order:
        raise ParseError("no usable best track rows")

    fixes: list[BestTrackFix] = []
    for when in order:
        fields, lat, lon = firsts[when]
        found = radii[when]
        fixes.append(
            BestTrackFix(
                time=when,
                lat=lat,
                lon=lon,
                vmax_kt=_int(fields, 8, zero_is_missing=True),
                mslp_mb=_int(fields, 9, zero_is_missing=True),
                type=fields[10] or None,
                radii=WindRadii(found.get(34), found.get(50), found.get(64)),
                rmw_nm=_int(fields, 19, zero_is_missing=True),
                gusts_kt=_int(fields, 20, zero_is_missing=True),
                eye_nm=_int(fields, 21, zero_is_missing=True),
                pouter_mb=_int(fields, 17, zero_is_missing=True),
                router_nm=_int(fields, 18, zero_is_missing=True),
                direction_deg=_int(fields, 25),
                speed_kt=_int(fields, 26),
                name=(fields[27] or None) if len(fields) > 27 else None,
                depth=(fields[28] or None) if len(fields) > 28 else None,
            )
        )
    return BestTrack(basin_code, number, tuple(fixes), skipped)


def _size(text: str | None) -> int | None:
    if not text or text == "-":
        return None
    scale = {"K": 1024, "M": 1024**2, "G": 1024**3}.get(text[-1].upper(), 1)
    try:
        return int(float(text.rstrip("KMGkmg")) * scale)
    except ValueError:
        return None


def parse_btk_index(data: bytes | str) -> tuple[BDeckFile, ...]:
    """The b-decks listed in the `atcf/btk/` directory page, newest storm numbers last. Other links are ignored.

    Invests are listed here and not in CurrentStorms.json, so this listing is how active invests are found; a file
    stays for a while after a system dies, so the caller should look at `modified`.
    """
    text = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data
    found: list[BDeckFile] = []
    for match in _LISTING.finditer(text):
        modified: datetime | None = None
        if match["date"]:
            modified = datetime.strptime(match["date"], "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
        found.append(
            BDeckFile(
                name=match["name"],
                basin_code=match["basin"].upper(),
                number=int(match["number"]),
                year=int(match["year"]),
                modified=modified,
                size_bytes=_size(match["size"]),
            )
        )
    return tuple(found)
