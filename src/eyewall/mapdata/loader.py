"""Reads the vendored Natural Earth map data.

The files are written by scripts/build_mapdata.py, which also documents the format. Coordinates are int16 hundredths of
a degree; this module returns them as (lat, lon) degrees, the order the rest of eyewall uses.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from functools import cache
from importlib import resources

LatLon = tuple[float, float]

MAGIC = b"EWMD"
FORMAT_VERSION = 1
FLAG_RINGS = 1

KIND_COUNTRY = 0  # in the borders layer: a country boundary
KIND_STATE = 1  # in the borders layer: a state or province line

LAYERS = ("coast50", "coast110", "land50", "land110", "borders")

_HEADER = struct.Struct("<4sBBHI")
_PATH_HEADER = struct.Struct("<BH")


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
    magic, version, flags, _, count = _HEADER.unpack_from(data)
    if magic != MAGIC or version != FORMAT_VERSION:
        raise ValueError("not an eyewall map data file of a supported version")
    offset = _HEADER.size
    paths: list[MapPath] = []
    for _ in range(count):
        kind, n = _PATH_HEADER.unpack_from(data, offset)
        offset += _PATH_HEADER.size
        flat = struct.unpack_from(f"<{2 * n}h", data, offset)
        offset += 4 * n
        lons, lats = flat[0::2], flat[1::2]
        paths.append(
            MapPath(
                kind,
                tuple((lat / 100.0, lon / 100.0) for lat, lon in zip(lats, lons, strict=True)),
                min(lats) / 100.0,
                min(lons) / 100.0,
                max(lats) / 100.0,
                max(lons) / 100.0,
            )
        )
    return MapLayer(bool(flags & FLAG_RINGS), tuple(paths))


@cache
def load_layer(name: str) -> MapLayer:
    """A layer by file stem: coast50, coast110, land50, land110 or borders. Read once, then kept."""
    if name not in LAYERS:
        raise ValueError(f"unknown map layer {name!r}; expected one of {', '.join(LAYERS)}")
    return parse(resources.files("eyewall.mapdata").joinpath(f"{name}.bin").read_bytes())
