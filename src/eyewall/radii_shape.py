"""The shape of a storm's 34, 50 or 64 knot wind radii: one geodesic polygon from four quadrant radii.

Each quadrant is an arc of constant geodesic distance (WGS84, not a sphere) from the storm, and neighbouring quadrants
join along the radial line between them, as NHC draws them. A quadrant of 0 or None (post-tropical systems often have
no value) pulls the outline to the center, so the shape is a wedge. The result is a shapely geometry with every
longitude in [-180, 180]: a shape that crosses the antimeridian comes back as one part per side of it.

Radii are capped so the shape stays a simple polygon: at most MAX_RADIUS_NM, and short of the nearest pole. Real wind
radii are under 700 nm and storms are not drawn at the poles, so the caps never bite in practice.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Sequence

import shapely
from pyproj import Geod
from shapely import affinity
from shapely.geometry import MultiPolygon, Polygon, box

from eyewall.geo import LatLon, normalize_lon

MAX_RADIUS_NM = 1500.0
_MIN_RADIUS_NM = 0.01  # about 18 m: anything smaller is no radius, and would only make a degenerate sliver
_NM_PER_DEGREE_OF_LATITUDE = 59.0  # a little under the true 59.55 to 60.15, so the pole cap errs short
_POLE_MARGIN_DEG = 0.1
_ARC_STEPS = 12  # points per quadrant arc, one every 7.5 degrees of bearing
_RADIAL_STEPS = 4  # points added along the radial line where neighbouring quadrants differ
_METERS_PER_NM = 1852.0
_GEOD = Geod(ellps="WGS84")

QuadrantRadiiNm = Sequence[float | None]  # NE, SE, SW, NW


def _clean(radii: QuadrantRadiiNm, lat: float) -> list[float]:
    """Radii in meters: missing, negative or non-finite becomes 0, and the caps are applied."""
    cap = min(MAX_RADIUS_NM, max(0.0, 90.0 - abs(lat) - _POLE_MARGIN_DEG) * _NM_PER_DEGREE_OF_LATITUDE)
    values = [r if r is not None and math.isfinite(r) and r >= _MIN_RADIUS_NM else 0.0 for r in radii]
    return [min(r, cap) * _METERS_PER_NM for r in values]


def _ring(lat: float, lon: float, radii_m: list[float]) -> list[tuple[float, float]]:
    """Closed ring of (lon, lat) with longitudes continuous around the center (they may pass 180)."""
    bearings: list[float] = []
    distances: list[float] = []
    for q, radius in enumerate(radii_m):
        for step in range(_ARC_STEPS + 1):
            bearings.append(q * 90.0 + step * 90.0 / _ARC_STEPS)
            distances.append(radius)
        next_radius = radii_m[(q + 1) % 4]
        for step in range(1, _RADIAL_STEPS + 1):
            bearings.append((q + 1) * 90.0)
            distances.append(radius + (next_radius - radius) * step / (_RADIAL_STEPS + 1))
    lons, lats, _ = _GEOD.fwd([lon] * len(bearings), [lat] * len(bearings), bearings, distances)
    return [(lon + normalize_lon(x - lon), y) for x, y in zip(lons, lats, strict=True)]


def _wrapped_parts(polygon: Polygon, lon: float) -> list[Polygon]:
    """Split a polygon whose longitudes run around `lon` at the antimeridian, each part moved into [-180, 180]."""
    parts: list[Polygon] = []
    for k in (-1, 0, 1):
        piece = polygon.intersection(box(360.0 * k - 180.0, -90.0, 360.0 * k + 180.0, 90.0))
        if k:
            piece = affinity.translate(piece, xoff=-360.0 * k)
        parts.extend(g for g in _polygons(piece) if g.area > 0)
    return parts


def _polygons(geometry: shapely.Geometry) -> Iterator[Polygon]:
    if isinstance(geometry, Polygon):
        yield geometry
    elif hasattr(geometry, "geoms"):
        for part in geometry.geoms:
            yield from _polygons(part)


def radii_shape(center: LatLon, radii_nm: QuadrantRadiiNm) -> Polygon | MultiPolygon | None:
    """The wind radii polygon around center (lat, lon) for radii in nautical miles in the NE, SE, SW and NW quadrants.
    None when no quadrant has a radius. Coordinates are (lon, lat) as shapely wants them."""
    lat = max(-90.0, min(90.0, center[0]))
    lon = normalize_lon(center[1])
    radii_m = _clean(radii_nm, lat)
    if not any(radii_m):
        return None
    polygon = Polygon(_ring(lat, lon, radii_m))
    if not polygon.is_valid:
        polygon = shapely.make_valid(polygon)
    parts = _wrapped_parts(polygon, lon)
    if not parts:
        return None
    return parts[0] if len(parts) == 1 else MultiPolygon(parts)


def radii_rings(center: LatLon, radii_nm: QuadrantRadiiNm) -> list[list[LatLon]]:
    """The outlines of radii_shape as (lat, lon) rings, one per part, each closed. Empty when there is no shape.
    Rounded to about a meter so the drawing does not depend on the platform's floating point (geod and GEOS output)."""
    shape = radii_shape(center, radii_nm)
    if shape is None:
        return []
    return [[(round(y, 5), round(x, 5)) for x, y in part.exterior.coords] for part in _polygons(shape)]
