"""Spherical geometry on a mean-radius Earth. Positions are (lat, lon) in degrees; distances are nautical miles.

Accurate to a fraction of a percent, which is far inside the uncertainty of any forecast track.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from itertools import pairwise

LatLon = tuple[float, float]
Vector = tuple[float, float, float]

EARTH_RADIUS_KM = 6371.0088
KM_PER_NM = 1.852
EARTH_RADIUS_NM = EARTH_RADIUS_KM / KM_PER_NM

_COMPASS = (
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
)  # fmt: skip


def normalize_lon(lon: float) -> float:
    """Wrap a longitude into [-180, 180)."""
    return (lon + 180.0) % 360.0 - 180.0


def wrap_lon(lon: float) -> float:
    """Wrap a longitude into (-180, 180], so the dateline itself is 180 and not -180. In-range values pass unchanged."""
    if -180.0 < lon <= 180.0:
        return lon
    wrapped = normalize_lon(lon)
    return 180.0 if wrapped == -180.0 else wrapped


def _to_vector(point: LatLon) -> Vector:
    lat, lon = math.radians(point[0]), math.radians(point[1])
    return (math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat))


def _from_vector(v: Vector) -> LatLon:
    return (math.degrees(math.atan2(v[2], math.hypot(v[0], v[1]))), math.degrees(math.atan2(v[1], v[0])))


def _dot(a: Vector, b: Vector) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vector, b: Vector) -> Vector:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(a: Vector) -> float:
    return math.sqrt(_dot(a, a))


def _scale(a: Vector, k: float) -> Vector:
    return (a[0] * k, a[1] * k, a[2] * k)


def _angle(a: Vector, b: Vector) -> float:
    """Angle between two vectors in radians, stable for tiny and near-180 degree angles."""
    return math.atan2(_norm(_cross(a, b)), _dot(a, b))


def haversine_nm(a: LatLon, b: LatLon) -> float:
    """Great-circle distance in nautical miles."""
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlat = lat2 - lat1
    dlon = math.radians(b[1] - a[1])
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_NM * math.asin(min(1.0, math.sqrt(h)))


def bearing_deg(a: LatLon, b: LatLon) -> float:
    """Initial bearing from a to b in degrees clockwise from north, in [0, 360)."""
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlon = math.radians(b[1] - a[1])
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def destination(start: LatLon, bearing: float, distance_nm: float) -> LatLon:
    """The point reached by travelling distance_nm from start on an initial bearing."""
    lat1, lon1 = math.radians(start[0]), math.radians(start[1])
    theta = math.radians(bearing)
    delta = distance_nm / EARTH_RADIUS_NM
    sin_lat2 = math.sin(lat1) * math.cos(delta) + math.cos(lat1) * math.sin(delta) * math.cos(theta)
    lat2 = math.asin(max(-1.0, min(1.0, sin_lat2)))
    lon2 = lon1 + math.atan2(
        math.sin(theta) * math.sin(delta) * math.cos(lat1), math.cos(delta) - math.sin(lat1) * math.sin(lat2)
    )
    return (math.degrees(lat2), normalize_lon(math.degrees(lon2)))


def interpolate(a: LatLon, b: LatLon, fraction: float) -> LatLon:
    """The point a given fraction of the way from a to b along the great circle (0 is a, 1 is b)."""
    va, vb = _to_vector(a), _to_vector(b)
    omega = _angle(va, vb)
    if omega < 1e-12 or abs(omega - math.pi) < 1e-9:
        return a
    k1 = math.sin((1 - fraction) * omega) / math.sin(omega)
    k2 = math.sin(fraction * omega) / math.sin(omega)
    return _from_vector((k1 * va[0] + k2 * vb[0], k1 * va[1] + k2 * vb[1], k1 * va[2] + k2 * vb[2]))


def distance_to_segment_nm(point: LatLon, a: LatLon, b: LatLon) -> float:
    """Shortest distance from a point to the great-circle segment a-b."""
    p, va, vb = _to_vector(point), _to_vector(a), _to_vector(b)
    normal = _cross(va, vb)
    length = _norm(normal)
    if length < 1e-12:  # a and b coincide or are exactly opposite: treat them as two points
        return min(haversine_nm(point, a), haversine_nm(point, b))
    normal = _scale(normal, 1.0 / length)
    along = _dot(p, normal)
    foot = (p[0] - along * normal[0], p[1] - along * normal[1], p[2] - along * normal[2])
    foot_length = _norm(foot)
    if foot_length > 1e-12:
        foot = _scale(foot, 1.0 / foot_length)
        if _dot(_cross(va, foot), normal) >= 0 and _dot(_cross(foot, vb), normal) >= 0:
            return _angle(p, foot) * EARTH_RADIUS_NM
    return min(haversine_nm(point, a), haversine_nm(point, b))


def distance_to_polyline_nm(point: LatLon, polyline: Sequence[LatLon]) -> float:
    """Shortest distance from a point to a track made of great-circle legs. Infinity for an empty track."""
    if not polyline:
        return math.inf
    if len(polyline) == 1:
        return haversine_nm(point, polyline[0])
    return min(distance_to_segment_nm(point, a, b) for a, b in pairwise(polyline))


def compass_point(bearing: float) -> str:
    """The 16-point compass name for a bearing, such as NNE or SW."""
    return _COMPASS[int((bearing % 360.0 + 11.25) // 22.5) % 16]
