"""Build the vendored basemap in src/eyewall/mapdata/ from Natural Earth.

Downloads the 1:10 million GeoJSON files from the nvkelso mirror (pinned to one commit, checked against SHA-256), clips
them to the tropical-cyclone basins' bounding box plus a margin, simplifies with Douglas-Peucker and packs the result
as int32 ten-thousandths of a degree (about 11 m). The output is deterministic: the same inputs always give the same
bytes.

Two detail tiers come from the same 10 m sources. The full tier ("coast", "land", "lakes") is simplified to 0.002
degrees (about 220 m) and is what every zoomed-in view draws. The `_lo` tier is simplified to 0.03 degrees and exists
only so a whole-basin view, where one terminal dot spans about a degree, does not project a million vertices. Both keep
every island: simplification never reduces a ring below three points.

Long lines are cut into pieces of at most MAX_LINE_POINTS points, and filled land is cut along a 5 degree grid, so a
viewport only touches the pieces it can see. The cuts in land fill are invisible (neighbouring pieces meet exactly);
coastline pieces overlap by one vertex.

    python scripts/build_mapdata.py             # download if needed, write src/eyewall/mapdata/*.bin + ATTRIBUTION.md
    python scripts/build_mapdata.py --check     # rebuild in memory and fail if the committed files differ
    python scripts/build_mapdata.py --refresh   # download the sources again

Binary format, little-endian, read by eyewall.mapdata.loader:

    header  "EWMD"  u8 version (2)  u8 flags (bit 0: closed rings)  u16 reserved  u32 units per degree  u32 path count
    path    u8 kind  u32 point count  then point count * (i32 longitude, i32 latitude) in 1/units-per-degree degrees

Ring paths are closed implicitly: the first point is not repeated at the end.

places.bin holds the populated places that label the map (Natural Earth ne_10m_populated_places_simple, public domain),
inside the same boxes, with scalerank 8 or better, sorted by (scalerank, descending pop_max, name) so the most
important come first:

    header  "EWPL"  u8 version (1)  u8 reserved  u16 reserved  u32 units per degree  u32 place count
    place   i32 longitude  i32 latitude  u8 scalerank  u32 pop_max  u8 name length  name (UTF-8)
            u8 ASCII name length (0 when it equals the name)  ASCII name
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import struct
import sys
import urllib.request
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

Point = tuple[float, float]  # (longitude, latitude), the GeoJSON order
Box = tuple[float, float, float, float]  # west, south, east, north

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE = ROOT / "cache" / "naturalearth"
DEFAULT_OUT = ROOT / "src" / "eyewall" / "mapdata"

# The mirror is pinned to the commit behind tag v5.1.2 so a rebuild never silently picks up new data.
MIRROR_REF = "f1890d9f152c896d250a77557a5751a93d494776"
MIRROR_URL = f"https://raw.githubusercontent.com/nvkelso/natural-earth-vector/{MIRROR_REF}/geojson/"

SOURCE_SHA256 = {
    "ne_10m_coastline": "6f75ae0e0de157b14946e2255eb1f5486d9a13819032e26d4610852d296788f6",
    "ne_10m_minor_islands_coastline": "d51fadaffc954e9e85671b0a2ecaba78b883dda1714640a173c151932fd1f2fb",
    "ne_10m_land": "1ac90796408bc6ad6911d69448485d3c4dbf2190370080368a09976e1c9f7416",
    "ne_10m_lakes": "2d036f53dedec578001c5c30c2959ee7d4eebc1306900fa4367c49929ec8f2d9",
    "ne_10m_admin_0_boundary_lines_land": "74d9c16229c095fde65943a9919e337682f044bcebccb120764f38edf3b70f4a",
    "ne_10m_admin_1_states_provinces_lines": "1a1f30ccaaf4cc9c4bde34266f0b8cbb955d3a4cf254b756912255f2ec7c75b6",
    "ne_10m_populated_places_simple": "fd3fa867a320cbd5c5b6bb5bc550afeec2939fb2cef688e508007282a55ac42f",
}

PLACES_SOURCE = "ne_10m_populated_places_simple"
PLACES_MAX_RANK = 8  # scalerank 9 and 10 are villages the finest zoom does not label

# The basins run from about 100 E eastward across the Pacific to 10 W, 5 S to 60 N. The data reaches MARGIN degrees
# beyond that so the flat cut where the fill stops is outside any view a basin storm needs. The box wraps the
# antimeridian, so it is two boxes.
MARGIN = 5.0
SOUTH, NORTH = -5.0 - MARGIN, 60.0 + MARGIN
BOXES: tuple[Box, ...] = ((100.0 - MARGIN, SOUTH, 180.0, NORTH), (-180.0, SOUTH, -10.0 + MARGIN, NORTH))

TILE = 5.0  # degrees; filled rings larger than this are cut along a grid of this size
MAX_LINE_POINTS = 400  # longest stored polyline; longer ones are split, overlapping by one vertex
UNITS = 10_000  # stored units per degree

MAGIC = b"EWMD"
PLACES_MAGIC = b"EWPL"
PLACES_VERSION = 1
FORMAT_VERSION = 2
FLAG_RINGS = 1
KIND_COUNTRY, KIND_STATE = 0, 1


@dataclass(frozen=True)
class LayerSpec:
    stem: str  # output file name without the extension
    sources: tuple[tuple[str, int], ...]  # (Natural Earth file, path kind)
    rings: bool  # polygons (filled) rather than lines
    tolerance: float  # Douglas-Peucker tolerance in degrees
    what: str
    tile: bool = True  # cut filled rings along the grid; lakes stay whole because they are also outlined


FULL_TOLERANCE = 0.002  # about 220 m; linecast simplifies to about 1 km
LO_TOLERANCE = 0.03  # a third of a dot in a whole-basin view

_COAST = (("ne_10m_coastline", 0), ("ne_10m_minor_islands_coastline", 0))
_LAND = (("ne_10m_land", 0),)
_LAKES = (("ne_10m_lakes", 0),)

LAYERS = (
    LayerSpec("coast", _COAST, False, FULL_TOLERANCE, "10 m coastline with minor islands"),
    LayerSpec("land", _LAND, True, FULL_TOLERANCE, "10 m land polygons"),
    LayerSpec("lakes", _LAKES, True, FULL_TOLERANCE, "10 m lakes", tile=False),
    LayerSpec(
        "borders",
        (("ne_10m_admin_0_boundary_lines_land", KIND_COUNTRY), ("ne_10m_admin_1_states_provinces_lines", KIND_STATE)),
        False,
        0.003,
        "10 m country boundaries and state or province lines",
    ),
    LayerSpec("coast_lo", _COAST, False, LO_TOLERANCE, "coarse coastline for whole-basin views"),
    LayerSpec("land_lo", _LAND, True, LO_TOLERANCE, "coarse land polygons for whole-basin views"),
    LayerSpec("lakes_lo", _LAKES, True, LO_TOLERANCE, "coarse lakes for whole-basin views", tile=False),
)


# ---------------------------------------------------------------------------------------------------------- geometry


def _clip_segment(p: Point, q: Point, box: Box) -> tuple[Point, Point] | None:
    """Liang-Barsky clip of one segment to a box. Endpoints that are already inside are returned untouched."""
    west, south, east, north = box
    dx, dy = q[0] - p[0], q[1] - p[1]
    t0, t1 = 0.0, 1.0
    for pk, qk in ((-dx, p[0] - west), (dx, east - p[0]), (-dy, p[1] - south), (dy, north - p[1])):
        if pk == 0:
            if qk < 0:
                return None
            continue
        t = qk / pk
        if pk < 0:
            if t > t1:
                return None
            t0 = max(t0, t)
        else:
            if t < t0:
                return None
            t1 = min(t1, t)
    a = p if t0 == 0.0 else (p[0] + t0 * dx, p[1] + t0 * dy)
    b = q if t1 == 1.0 else (p[0] + t1 * dx, p[1] + t1 * dy)
    return a, b


def clip_polyline(points: Sequence[Point], box: Box) -> list[list[Point]]:
    """The parts of a polyline inside a box, as separate polylines."""
    pieces: list[list[Point]] = []
    current: list[Point] = []
    for p, q in itertools.pairwise(points):
        clipped = _clip_segment(p, q, box)
        if clipped is None or clipped[0] == clipped[1]:  # missed the box, or only touched it at a point
            if len(current) > 1:
                pieces.append(current)
            current = []
            continue
        a, b = clipped
        if current and current[-1] == a:
            current.append(b)
        else:
            if len(current) > 1:
                pieces.append(current)
            current = [a, b]
    if len(current) > 1:
        pieces.append(current)
    return pieces


def clip_ring(ring: Sequence[Point], box: Box) -> list[Point]:
    """Sutherland-Hodgman clip of a closed ring to a box. The result may be empty."""
    west, south, east, north = box
    edges = (
        (lambda p: p[0] >= west, lambda a, b: (west, a[1] + (b[1] - a[1]) * (west - a[0]) / (b[0] - a[0]))),
        (lambda p: p[0] <= east, lambda a, b: (east, a[1] + (b[1] - a[1]) * (east - a[0]) / (b[0] - a[0]))),
        (lambda p: p[1] >= south, lambda a, b: (a[0] + (b[0] - a[0]) * (south - a[1]) / (b[1] - a[1]), south)),
        (lambda p: p[1] <= north, lambda a, b: (a[0] + (b[0] - a[0]) * (north - a[1]) / (b[1] - a[1]), north)),
    )
    out = list(ring)
    for inside, cross in edges:
        points, out = out, []
        if not points:
            break
        previous = points[-1]
        for current in points:
            if inside(current):
                if not inside(previous):
                    out.append(cross(previous, current))
                out.append(current)
            elif inside(previous):
                out.append(cross(previous, current))
            previous = current
    return out


def _segment_distance_squared(p: Point, a: Point, b: Point) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2))
    cx, cy = a[0] + t * dx, a[1] + t * dy
    return (p[0] - cx) ** 2 + (p[1] - cy) ** 2


def simplify(points: Sequence[Point], tolerance: float) -> list[Point]:
    """Douglas-Peucker. Keeps both end points; iterative so long coastlines cannot overflow the stack."""
    n = len(points)
    if n <= 2:
        return list(points)
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    limit = tolerance * tolerance
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        worst, index = -1.0, i
        for k in range(i + 1, j):
            d = _segment_distance_squared(points[k], points[i], points[j])
            if d > worst:
                worst, index = d, k
        if worst > limit:
            keep[index] = True
            stack.append((i, index))
            stack.append((index, j))
    return [p for p, kept in zip(points, keep, strict=True) if kept]


def simplify_ring(ring: Sequence[Point], tolerance: float) -> list[Point]:
    """Douglas-Peucker for a closed ring, split at the vertex farthest from the first so the ring keeps its shape.
    A ring smaller than the tolerance comes back as a triangle. A ring with no area (all points collinear) comes back
    as a degenerate three-point path that fills nothing; rings of fewer than three points are dropped by the caller."""
    points = list(ring)
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()
    if len(points) <= 3:
        return points
    first = points[0]
    far = max(range(1, len(points)), key=lambda k: (points[k][0] - first[0]) ** 2 + (points[k][1] - first[1]) ** 2)
    one = simplify(points[: far + 1], tolerance)
    two = simplify([*points[far:], first], tolerance)
    result = one[:-1] + two[:-1]
    if len(result) < 3:  # an islet smaller than the tolerance stays, as a triangle, rather than vanishing
        third = max(points, key=lambda q: _segment_distance_squared(q, first, points[far]))
        result = [first, *sorted({points[far], third}, key=points.index)]
    return result


def quantize(points: Iterable[Point]) -> list[tuple[int, int]]:
    """Round to the stored unit (UNITS per degree) and drop consecutive duplicates."""
    out: list[tuple[int, int]] = []
    for lon, lat in points:
        q = (math.floor(lon * UNITS + 0.5), math.floor(lat * UNITS + 0.5))
        if not out or out[-1] != q:
            out.append(q)
    return out


def tile_ring(ring: list[Point], box: Box) -> list[list[Point]]:
    """Cut a ring along a TILE-degree grid by halving the box, so a viewport can skip the pieces it cannot see.
    Neighbouring pieces are clipped on the same line, so together they cover exactly what the ring covered."""
    xs, ys = [p[0] for p in ring], [p[1] for p in ring]
    west, south, east, north = box
    if max(xs) - min(xs) <= TILE and max(ys) - min(ys) <= TILE:
        return [ring]
    if east - west >= north - south:
        mid = west + math.ceil((east - west) / TILE / 2) * TILE
        if mid >= east:
            return [ring]
        halves = ((west, south, mid, north), (mid, south, east, north))
    else:
        mid = south + math.ceil((north - south) / TILE / 2) * TILE
        if mid >= north:
            return [ring]
        halves = ((west, south, east, mid), (west, mid, east, north))
    pieces: list[list[Point]] = []
    for half in halves:
        part = clip_ring(ring, half)
        if len(part) >= 3:
            pieces.extend(tile_ring(part, half))
    return pieces


def split_line(points: Sequence[tuple[int, int]]) -> list[Sequence[tuple[int, int]]]:
    """Pieces of at most MAX_LINE_POINTS points, each starting on the last point of the one before."""
    if len(points) <= MAX_LINE_POINTS:
        return [points]
    step = MAX_LINE_POINTS - 1
    return [points[i : i + MAX_LINE_POINTS] for i in range(0, len(points) - 1, step)]


# ------------------------------------------------------------------------------------------------------------- data


def _lines(geometry: dict) -> Iterator[list[Point]]:
    kind, coords = geometry["type"], geometry["coordinates"]
    if kind == "LineString":
        yield [(c[0], c[1]) for c in coords]
    elif kind == "MultiLineString":
        for line in coords:
            yield [(c[0], c[1]) for c in line]


def _rings(geometry: dict) -> Iterator[list[Point]]:
    kind, coords = geometry["type"], geometry["coordinates"]
    polygons = [coords] if kind == "Polygon" else coords if kind == "MultiPolygon" else []
    for polygon in polygons:
        for ring in polygon:
            yield [(c[0], c[1]) for c in ring]


def convert(
    geometries: Iterable[tuple[dict, int]], *, rings: bool, tolerance: float, tile: bool = True
) -> list[tuple[int, list[tuple[int, int]]]]:
    """Clip, simplify, cut and quantize GeoJSON geometries into (kind, points) paths."""
    paths: list[tuple[int, list[tuple[int, int]]]] = []
    for geometry, kind in geometries:
        if rings:
            for ring in _rings(geometry):
                for box in BOXES:
                    clipped = clip_ring(ring[:-1] if ring and ring[0] == ring[-1] else ring, box)
                    if len(clipped) < 3:
                        continue
                    simple = simplify_ring(clipped, tolerance)
                    for piece in tile_ring(simple, box) if tile and len(simple) > 3 else [simple]:
                        points = quantize(piece)
                        if len(points) > 1 and points[0] == points[-1]:
                            points.pop()
                        if len(points) >= 3:
                            paths.append((kind, points))
        else:
            for line in _lines(geometry):
                for box in BOXES:
                    for piece in clip_polyline(line, box):
                        if len(piece) > 3 and piece[0] == piece[-1]:  # an island's shoreline: keep it a closed loop
                            simple = [*simplify_ring(piece, tolerance), piece[0]]
                        else:
                            simple = simplify(piece, tolerance)
                        points = quantize(simple)
                        if len(points) >= 2:
                            paths.extend((kind, list(part)) for part in split_line(points))
    return paths


_HEADER = struct.Struct("<4sBBHII")
_PATH_HEADER = struct.Struct("<BI")


def pack(paths: Sequence[tuple[int, Sequence[tuple[int, int]]]], *, rings: bool) -> bytes:
    """The .bin encoding described in the module docstring."""
    out = bytearray(_HEADER.pack(MAGIC, FORMAT_VERSION, FLAG_RINGS if rings else 0, 0, UNITS, len(paths)))
    for kind, points in paths:
        out += _PATH_HEADER.pack(kind, len(points))
        out += struct.pack(f"<{2 * len(points)}i", *(v for point in points for v in point))
    return bytes(out)


def unpack(data: bytes) -> tuple[bool, list[tuple[int, list[tuple[int, int]]]]]:
    """Inverse of pack, for tests and for --check diagnostics."""
    magic, version, flags, _, units, count = _HEADER.unpack_from(data)
    if magic != MAGIC or version != FORMAT_VERSION or units != UNITS:
        raise ValueError("not an eyewall map data file")
    offset = _HEADER.size
    paths = []
    for _ in range(count):
        kind, n = _PATH_HEADER.unpack_from(data, offset)
        offset += _PATH_HEADER.size
        flat = struct.unpack_from(f"<{2 * n}i", data, offset)
        offset += 8 * n
        paths.append((kind, list(zip(flat[0::2], flat[1::2], strict=True))))
    return bool(flags & FLAG_RINGS), paths


_PLACES_HEADER = struct.Struct("<4sBBHII")
_PLACE_FIXED = struct.Struct("<iiBI")

Place = tuple[int, int, int, int, str, str]  # lon, lat (stored units), scalerank, pop_max, name, ASCII name


def places_from(collection: dict) -> list[Place]:
    """The places inside the map boxes with scalerank PLACES_MAX_RANK or better, most important first. Fields are read
    by name; a feature without a name, a position or a scalerank is skipped."""
    places: list[Place] = []
    for feature in collection["features"]:
        props = feature.get("properties") or {}
        name, rank = props.get("name"), props.get("scalerank")
        lon, lat = props.get("longitude"), props.get("latitude")
        if not name or rank is None or lon is None or lat is None or rank > PLACES_MAX_RANK:
            continue
        if not any(w <= lon <= e and s <= lat <= n for w, s, e, n in BOXES):
            continue
        ascii_name = props.get("nameascii") or name
        pop = int(props.get("pop_max") or 0)
        ((x, y),) = quantize([(lon, lat)])
        places.append((x, y, int(rank), pop, str(name), str(ascii_name)))
    places.sort(key=lambda p: (p[2], -p[3], p[4], p[0], p[1]))
    return places


def pack_places(places: Sequence[Place]) -> bytes:
    """The places.bin encoding described in the module docstring."""
    out = bytearray(_PLACES_HEADER.pack(PLACES_MAGIC, PLACES_VERSION, 0, 0, UNITS, len(places)))
    for x, y, rank, pop, name, ascii_name in places:
        raw = name.encode("utf-8")
        alt = b"" if ascii_name == name else ascii_name.encode("utf-8")
        if len(raw) > 255 or len(alt) > 255:
            raise ValueError(f"place name too long: {name!r}")
        out += _PLACE_FIXED.pack(x, y, rank, min(pop, 0xFFFFFFFF)) + bytes([len(raw)]) + raw + bytes([len(alt)]) + alt
    return bytes(out)


# ----------------------------------------------------------------------------------------------------------- driver


def _verify(path: Path, data: bytes, expected: str) -> None:
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected:
        raise SystemExit(f"{path} has SHA-256 {digest}, expected {expected}; delete it and run with --refresh")


def fetch(name: str, cache: Path, *, refresh: bool) -> bytes:
    """The bytes of one Natural Earth GeoJSON file, downloaded once into the cache and checked against its hash."""
    path = cache / f"{name}.geojson"
    if refresh or not path.exists():
        print(f"downloading {name}", file=sys.stderr)
        request = urllib.request.Request(MIRROR_URL + f"{name}.geojson", headers={"User-Agent": "eyewall-build"})
        with urllib.request.urlopen(request, timeout=120) as response:
            downloaded = response.read()
        _verify(path, downloaded, SOURCE_SHA256[name])
        cache.mkdir(parents=True, exist_ok=True)
        path.write_bytes(downloaded)
    data = path.read_bytes()
    _verify(path, data, SOURCE_SHA256[name])
    return data


def build(cache: Path, *, refresh: bool = False) -> dict[str, bytes]:
    """Every output file, by name."""
    outputs: dict[str, bytes] = {}
    for spec in LAYERS:
        geometries: list[tuple[dict, int]] = []
        for name, kind in spec.sources:
            collection = json.loads(fetch(name, cache, refresh=refresh))
            geometries.extend((feature["geometry"], kind) for feature in collection["features"] if feature["geometry"])
        outputs[f"{spec.stem}.bin"] = pack(
            convert(geometries, rings=spec.rings, tolerance=spec.tolerance, tile=spec.tile), rings=spec.rings
        )
    outputs["places.bin"] = pack_places(places_from(json.loads(fetch(PLACES_SOURCE, cache, refresh=refresh))))
    outputs["ATTRIBUTION.md"] = attribution(outputs).encode()
    return outputs


def attribution(outputs: dict[str, bytes]) -> str:
    rows = "\n".join(
        f"| `{spec.stem}.bin` | {spec.what} | `{', '.join(name for name, _ in spec.sources)}` "
        f"| {len(outputs[spec.stem + '.bin']):,} |"
        for spec in LAYERS
    )
    rows += (
        f"\n| `places.bin` | populated places for map labels (scalerank {PLACES_MAX_RANK} or better) "
        f"| `{PLACES_SOURCE}` | {len(outputs['places.bin']):,} |"
    )
    total = sum(len(data) for name, data in outputs.items() if name.endswith(".bin"))
    sources = "\n".join(f"- `{name}`: `{digest}`" for name, digest in SOURCE_SHA256.items())
    return f"""# Map data attribution

The `.bin` files in this directory are derived from [Natural Earth](https://www.naturalearthdata.com/) vector data,
which is in the public domain ("Made with Natural Earth. Free vector and raster map data @ naturalearthdata.com").
No permission or credit is required; it is given here anyway.

The data was read from the [nvkelso/natural-earth-vector](https://github.com/nvkelso/natural-earth-vector) mirror at
commit `{MIRROR_REF}` (tag v5.1.2), at the 1:10 million scale. They are clipped to longitude 95 E eastward across the
Pacific to 5 W and latitude 10 S to 65 N, simplified with Douglas-Peucker (0.002 degrees for the full tier, 0.03 for
the `_lo` tier used by whole-basin views) and stored as 32-bit integers in ten-thousandths of a degree.

`places.bin` holds point features from the same mirror and commit (`ne_10m_populated_places_simple`), kept inside the
same area and ordered by scalerank then population.

| File | Content | Natural Earth source | Bytes |
|---|---|---|---|
{rows}

Total: {total:,} bytes. The format is described at the top of `scripts/build_mapdata.py`.

## Rebuilding

`python scripts/build_mapdata.py` downloads the sources into `cache/naturalearth/` and rewrites these files and this
page; `--check` rebuilds in memory and fails if the committed files differ. The sources are verified against these
SHA-256 digests:

{sources}
"""


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the vendored basemap data.")
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE, help="where the Natural Earth downloads are kept")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="the eyewall.mapdata directory")
    parser.add_argument("--refresh", action="store_true", help="download the sources again")
    parser.add_argument("--check", action="store_true", help="compare a fresh build with the files in --out")
    args = parser.parse_args(argv)
    outputs = build(args.cache, refresh=args.refresh)
    if args.check:
        stale = [
            name
            for name, data in outputs.items()
            if not (args.out / name).exists() or (args.out / name).read_bytes() != data
        ]
        if stale:
            print("out of date: " + ", ".join(stale), file=sys.stderr)
            return 1
        print("map data is up to date")
        return 0
    args.out.mkdir(parents=True, exist_ok=True)
    for name, data in outputs.items():
        (args.out / name).write_bytes(data)
        print(f"{name}: {len(data):,} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
