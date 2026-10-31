"""Reads the vendored Natural Earth map data.

The files are written by scripts/build_mapdata.py, which also documents the format. Coordinates are int32 in units of
1/units-per-degree (ten-thousandths of a degree, about 11 m); this module returns them as (lat, lon) degrees, the
order the rest of eyewall uses.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from functools import cache
from importlib import resources

LatLon = tuple[float, float]

MAGIC = b"EWMD"
FORMAT_VERSION = 2
FLAG_RINGS = 1

KIND_COUNTRY = 0  # in the borders layer: a country boundary
KIND_STATE = 1  # in the borders layer: a state or province line

# The full tier is Natural Earth 1:10 million simplified to 0.002 degrees; the `_lo` tier is the same data simplified to
# 0.03 degrees, for whole-basin views.
LAYERS = ("coast", "land", "lakes", "borders", "coast_lo", "land_lo", "lakes_lo")

_HEADER = struct.Struct("<4sBBHII")
_PATH_HEADER = struct.Struct("<BI")


@dataclass(frozen=True)
class MapPath:
    """One polyline, or one ring when the layer holds polygons (the first point is not repeated at the end)."""

    kind: int
    points: tuple[LatLon, ...]
    south: float
    west: float
    north: float
    east: float  # a path never crosses the antimeridian, so west <= east


@dataclass(frozen=True)
class MapLayer:
    rings: bool
    paths: tuple[MapPath, ...]

    @property
    def vertex_count(self) -> int:
        return sum(len(path.points) for path in self.paths)


def parse(data: bytes) -> MapLayer:
    """Decode the bytes of one .bin file."""
    if len(data) < _HEADER.size:
        raise ValueError("map data file is truncated")
    magic, version, flags, _, units, count = _HEADER.unpack_from(data)
    if magic != MAGIC or version != FORMAT_VERSION:
        raise ValueError("not an eyewall map data file of a supported version")
    if units <= 0:
        raise ValueError("map data file has a non-positive unit scale")
    offset = _HEADER.size
    scale = float(units)
    paths: list[MapPath] = []
    for _ in range(count):
        if offset + _PATH_HEADER.size > len(data):
            raise ValueError("map data file is truncated")
        kind, n = _PATH_HEADER.unpack_from(data, offset)
        offset += _PATH_HEADER.size
        if n == 0 or offset + 8 * n > len(data):
            raise ValueError("map data file is truncated or has an empty path")
        flat = struct.unpack_from(f"<{2 * n}i", data, offset)
        offset += 8 * n
        lons, lats = flat[0::2], flat[1::2]
        paths.append(
            MapPath(
                kind,
                tuple((lat / scale, lon / scale) for lat, lon in zip(lats, lons, strict=True)),
                min(lats) / scale,
                min(lons) / scale,
                max(lats) / scale,
                max(lons) / scale,
            )
        )
    return MapLayer(bool(flags & FLAG_RINGS), tuple(paths))


@cache
def load_layer(name: str) -> MapLayer:
    """A layer by file stem: one of LAYERS. Read once, then kept."""
    if name not in LAYERS:
        raise ValueError(f"unknown map layer {name!r}; expected one of {', '.join(LAYERS)}")
    return parse(resources.files("eyewall.mapdata").joinpath(f"{name}.bin").read_bytes())
