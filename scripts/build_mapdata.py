"""Build the vendored basemap in src/eyewall/mapdata/ from Natural Earth.

Downloads the GeoJSON files from the nvkelso mirror (pinned to one commit, checked against SHA-256), clips them to the
tropical-cyclone basins' bounding box, simplifies with Douglas-Peucker and packs the result as int16 hundredths of a
degree. The output is deterministic: the same inputs always give the same bytes.

    python scripts/build_mapdata.py             # download if needed, write src/eyewall/mapdata/*.bin + ATTRIBUTION.md
    python scripts/build_mapdata.py --check     # rebuild in memory and fail if the committed files differ
    python scripts/build_mapdata.py --refresh   # download the sources again

Binary format, little-endian, read by eyewall.mapdata.loader:

    header  "EWMD"  u8 version (1)  u8 flags (bit 0: closed rings)  u16 reserved  u32 path count
    path    u8 kind  u16 point count  then point count * (i16 longitude, i16 latitude) in hundredths of a degree

Ring paths are closed implicitly: the first point is not repeated at the end.
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
    "ne_50m_coastline": "271f1c4c1908312bac6b29d158ea1356544beafc129f260005300913aa5ea283",
    "ne_50m_land": "e874b27a51d146452be360cafb3cc50c86001074a67d534113e6534682f9826b",
    "ne_50m_admin_0_boundary_lines_land": "2faac4f6b34386f3d21b6e018cf151f241f00e5c936d44dd17d7d9bfb147fa48",
    "ne_50m_admin_1_states_provinces_lines": "72cca93c850d412628a5da4bc5ebfe21ba4d376eb34611bde6b623ee73f0fdcf",
    "ne_110m_coastline": "851f581ff5ffb844deed8ae1a9ce22e3c4bb3d74fa342cadb5d8e39b41ae7c3c",
    "ne_110m_land": "9e0729ee253ca7d7a5c4ae9395fb1902264c5377c52e224d13dd85010e2835d9",
}

# About 100 E eastward across the Pacific to 10 W, 5 S to 60 N. The box wraps the antimeridian, so it is two boxes.
SOUTH, NORTH = -5.0, 60.0
BOXES: tuple[Box, ...] = ((100.0, SOUTH, 180.0, NORTH), (-180.0, SOUTH, -10.0, NORTH))

MAGIC = b"EWMD"
FORMAT_VERSION = 1
FLAG_RINGS = 1
KIND_COUNTRY, KIND_STATE = 0, 1


@dataclass(frozen=True)
class LayerSpec:
    stem: str  # output file name without the extension
    sources: tuple[tuple[str, int], ...]  # (Natural Earth file, path kind)
    rings: bool  # polygons (filled) rather than lines
    tolerance: float  # Douglas-Peucker tolerance in degrees
    what: str


LAYERS = (
    LayerSpec("coast50", (("ne_50m_coastline", 0),), False, 0.01, "50 m coastline"),
    LayerSpec("coast110", (("ne_110m_coastline", 0),), False, 0.05, "110 m coastline"),
    LayerSpec("land50", (("ne_50m_land", 0),), True, 0.01, "50 m land polygons"),
    LayerSpec("land110", (("ne_110m_land", 0),), True, 0.05, "110 m land polygons"),
    LayerSpec(
        "borders",
        (("ne_50m_admin_0_boundary_lines_land", KIND_COUNTRY), ("ne_50m_admin_1_states_provinces_lines", KIND_STATE)),
        False,
        0.02,
        "50 m country boundaries and state or province lines",
    ),
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
    """Douglas-Peucker for a closed ring, split at the vertex farthest from the first so the ring keeps its shape."""
    points = list(ring)
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()
    if len(points) <= 3:
        return points
    first = points[0]
    far = max(range(1, len(points)), key=lambda k: (points[k][0] - first[0]) ** 2 + (points[k][1] - first[1]) ** 2)
    one = simplify(points[: far + 1], tolerance)
    two = simplify([*points[far:], first], tolerance)
    return one[:-1] + two[:-1]


def quantize(points: Iterable[Point]) -> list[tuple[int, int]]:
    """Round to hundredths of a degree and drop consecutive duplicates."""
    out: list[tuple[int, int]] = []
    for lon, lat in points:
        q = (math.floor(lon * 100 + 0.5), math.floor(lat * 100 + 0.5))
        if not out or out[-1] != q:
            out.append(q)
    return out


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
    geometries: Iterable[tuple[dict, int]], *, rings: bool, tolerance: float
) -> list[tuple[int, list[tuple[int, int]]]]:
    """Clip, simplify and quantize GeoJSON geometries into (kind, points) paths."""
    paths: list[tuple[int, list[tuple[int, int]]]] = []
    for geometry, kind in geometries:
        if rings:
            for ring in _rings(geometry):
                for box in BOXES:
                    clipped = clip_ring(ring[:-1] if ring and ring[0] == ring[-1] else ring, box)
                    if len(clipped) < 3:
                        continue
                    points = quantize(simplify_ring(clipped, tolerance))
                    if len(points) > 1 and points[0] == points[-1]:
                        points.pop()
                    if len(points) >= 3:
                        paths.append((kind, points))
        else:
            for line in _lines(geometry):
                for box in BOXES:
                    for piece in clip_polyline(line, box):
                        points = quantize(simplify(piece, tolerance))
                        if len(points) >= 2:
                            paths.append((kind, points))
    return paths


def pack(paths: Sequence[tuple[int, Sequence[tuple[int, int]]]], *, rings: bool) -> bytes:
    """The .bin encoding described in the module docstring."""
    out = bytearray(struct.pack("<4sBBHI", MAGIC, FORMAT_VERSION, FLAG_RINGS if rings else 0, 0, len(paths)))
    for kind, points in paths:
        out += struct.pack("<BH", kind, len(points))
        out += struct.pack(f"<{2 * len(points)}h", *(v for point in points for v in point))
    return bytes(out)


def unpack(data: bytes) -> tuple[bool, list[tuple[int, list[tuple[int, int]]]]]:
    """Inverse of pack, for tests and for --check diagnostics."""
    magic, version, flags, _, count = struct.unpack_from("<4sBBHI", data)
    if magic != MAGIC or version != FORMAT_VERSION:
        raise ValueError("not an eyewall map data file")
    offset = struct.calcsize("<4sBBHI")
    paths = []
    for _ in range(count):
        kind, n = struct.unpack_from("<BH", data, offset)
        offset += 3
        flat = struct.unpack_from(f"<{2 * n}h", data, offset)
        offset += 4 * n
        paths.append((kind, list(zip(flat[0::2], flat[1::2], strict=True))))
    return bool(flags & FLAG_RINGS), paths


# ----------------------------------------------------------------------------------------------------------- driver


def fetch(name: str, cache: Path, *, refresh: bool) -> bytes:
    """The bytes of one Natural Earth GeoJSON file, downloaded once into the cache and checked against its hash."""
    path = cache / f"{name}.geojson"
    if refresh or not path.exists():
        print(f"downloading {name}", file=sys.stderr)
        request = urllib.request.Request(MIRROR_URL + f"{name}.geojson", headers={"User-Agent": "eyewall-build"})
        with urllib.request.urlopen(request, timeout=120) as response:
            data = response.read()
        cache.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if SOURCE_SHA256[name] and digest != SOURCE_SHA256[name]:
        raise SystemExit(
            f"{path} has SHA-256 {digest}, expected {SOURCE_SHA256[name]}; delete it and run with --refresh"
        )
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
            convert(geometries, rings=spec.rings, tolerance=spec.tolerance), rings=spec.rings
        )
    outputs["ATTRIBUTION.md"] = attribution(outputs).encode()
    return outputs


def attribution(outputs: dict[str, bytes]) -> str:
    rows = "\n".join(
        f"| `{spec.stem}.bin` | {spec.what} | `{', '.join(name for name, _ in spec.sources)}` "
        f"| {len(outputs[spec.stem + '.bin']):,} |"
        for spec in LAYERS
    )
    total = sum(len(data) for name, data in outputs.items() if name.endswith(".bin"))
    sources = "\n".join(f"- `{name}`: `{digest}`" for name, digest in SOURCE_SHA256.items())
    return f"""# Map data attribution

The `.bin` files in this directory are derived from [Natural Earth](https://www.naturalearthdata.com/) vector data,
which is in the public domain ("Made with Natural Earth. Free vector and raster map data @ naturalearthdata.com").
No permission or credit is required; it is given here anyway.

The data was read from the [nvkelso/natural-earth-vector](https://github.com/nvkelso/natural-earth-vector) mirror at
commit `{MIRROR_REF}` (tag v5.1.2), clipped to longitude 100 E eastward across the Pacific to 10 W and latitude 5 S to
60 N, simplified with Douglas-Peucker and stored as 16-bit integers in hundredths of a degree.

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
