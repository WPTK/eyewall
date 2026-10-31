"""Map viewport: conversion between (lat, lon) and canvas dot coordinates.

The projection is equirectangular, with longitude scaled by the cosine of the center latitude so a degree of longitude
covers the same number of dots as the matching distance of latitude at the center of the view. One value, degrees per
dot, sets the zoom for both axes because a braille dot is close to square in a terminal cell.

Dot coordinates are continuous: dot (i, j) covers [i, i+1) by [j, j+1), x grows to the east and y grows to the south,
and the top-left corner of the grid is (0, 0). Longitudes wrap, so a viewport centered on the antimeridian shows
Central Pacific storms whole: every longitude is measured as the signed offset from the viewport center.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import cached_property

from eyewall.geo import normalize_lon

LatLon = tuple[float, float]
Dot = tuple[float, float]

MIN_DEG_PER_DOT = 0.002
MAX_DEG_PER_DOT = 4.0
MAX_CENTER_LAT = 85.0


def _wrap(delta: float) -> float:
    """A longitude difference wrapped into [-180, 180)."""
    return (delta + 180.0) % 360.0 - 180.0


@dataclass(frozen=True)
class Bounds:
    """A latitude band and a longitude arc running east from west for lon_span degrees (at most 360)."""

    south: float
    west: float
    north: float
    lon_span: float

    @property
    def east(self) -> float:
        return normalize_lon(self.west + min(self.lon_span, 360.0))

    @property
    def center(self) -> LatLon:
        return ((self.south + self.north) / 2.0, normalize_lon(self.west + self.lon_span / 2.0))

    @classmethod
    def of(cls, south: float, west: float, north: float, east: float) -> Bounds:
        """Bounds from corner coordinates. A west that lies east of east means the box crosses the antimeridian."""
        span = 0.0 if east == west else (east - west) % 360.0
        return cls(min(south, north), normalize_lon(west), max(south, north), span)

    def contains(self, lat: float, lon: float) -> bool:
        return self.south <= lat <= self.north and (lon - self.west) % 360.0 <= self.lon_span

    def intersects(self, other: Bounds) -> bool:
        if other.south > self.north or other.north < self.south:
            return False
        if self.lon_span >= 360.0 or other.lon_span >= 360.0:
            return True
        return (other.west - self.west) % 360.0 <= self.lon_span or (self.west - other.west) % 360.0 <= other.lon_span


def bounds_of(points: Iterable[LatLon]) -> Bounds:
    """The smallest bounds holding every point. The longitude arc is the shortest one, so it may cross +-180."""
    pts = list(points)
    if not pts:
        raise ValueError("no points")
    south = min(p[0] for p in pts)
    north = max(p[0] for p in pts)
    lons = sorted({normalize_lon(p[1]) for p in pts})
    if len(lons) == 1:
        return Bounds(south, lons[0], north, 0.0)
    gaps = [(lons[(i + 1) % len(lons)] - lons[i]) % 360.0 for i in range(len(lons))]
    widest = max(range(len(gaps)), key=gaps.__getitem__)
    return Bounds(south, lons[(widest + 1) % len(lons)], north, 360.0 - gaps[widest])


@dataclass(frozen=True)
class Viewport:
    """What part of the world a canvas shows.

    cols and rows are terminal cells; dots_x and dots_y are the dots in one cell (2 and 4 for braille, 1 and 2 for the
    half-block and ASCII modes). The center is normalized and the zoom clamped on construction.
    """

    center_lat: float
    center_lon: float
    deg_per_dot: float
    cols: int
    rows: int
    dots_x: int = 2
    dots_y: int = 4

    def __post_init__(self) -> None:
        if self.cols < 1 or self.rows < 1 or self.dots_x < 1 or self.dots_y < 1:
            raise ValueError("a viewport needs at least one cell with at least one dot")
        object.__setattr__(self, "center_lat", max(-MAX_CENTER_LAT, min(MAX_CENTER_LAT, self.center_lat)))
        object.__setattr__(self, "center_lon", normalize_lon(self.center_lon))
        object.__setattr__(self, "deg_per_dot", max(MIN_DEG_PER_DOT, min(MAX_DEG_PER_DOT, self.deg_per_dot)))

    @property
    def width(self) -> int:
        """Width in dots."""
        return self.cols * self.dots_x

    @property
    def height(self) -> int:
        """Height in dots."""
        return self.rows * self.dots_y

    @cached_property
    def lon_scale(self) -> float:
        """cos(center latitude), rounded so the dots a coordinate lands on never depend on the platform's libm."""
        return round(math.cos(math.radians(self.center_lat)), 9)

    @cached_property
    def _kx(self) -> float:
        return self.lon_scale / self.deg_per_dot

    def to_dot(self, lat: float, lon: float) -> Dot:
        """Continuous dot coordinates of a position."""
        return (
            self.width / 2.0 + _wrap(lon - self.center_lon) * self._kx,
            self.height / 2.0 - (lat - self.center_lat) / self.deg_per_dot,
        )

    def dot_at(self, lat: float, lon: float) -> tuple[int, int]:
        """The integer dot a position falls in."""
        x, y = self.to_dot(lat, lon)
        return math.floor(x), math.floor(y)

    def to_geo(self, x: float, y: float) -> LatLon:
        """The position at continuous dot coordinates. The inverse of to_dot."""
        lat = self.center_lat - (y - self.height / 2.0) * self.deg_per_dot
        lon = normalize_lon(self.center_lon + (x - self.width / 2.0) / self._kx)
        return (lat, lon)

    def project_path(self, points: Iterable[LatLon]) -> list[Dot]:
        """Dot coordinates for a line or ring. Each step takes the short way round, so a path that crosses
        the antimeridian stays in one piece instead of jumping across the map."""
        out: list[Dot] = []
        half_w, half_h = self.width / 2.0, self.height / 2.0
        kx, dpd, clat, clon = self._kx, self.deg_per_dot, self.center_lat, self.center_lon
        dlon = 0.0
        previous: float | None = None
        for lat, lon in points:
            dlon = _wrap(lon - clon) if previous is None else dlon + _wrap(lon - previous)
            previous = lon
            out.append((half_w + dlon * kx, half_h - (lat - clat) / dpd))
        return out

    def bounds(self) -> Bounds:
        """The part of the world in view."""
        half_lat = self.height / 2.0 * self.deg_per_dot
        half_lon = min(180.0, self.width / 2.0 / self._kx)
        return Bounds(
            max(-90.0, self.center_lat - half_lat),
            normalize_lon(self.center_lon - half_lon),
            min(90.0, self.center_lat + half_lat),
            2.0 * half_lon,
        )

    def _moved(self, lat: float, lon: float, deg_per_dot: float | None = None) -> Viewport:
        zoom = self.deg_per_dot if deg_per_dot is None else deg_per_dot
        return Viewport(lat, lon, zoom, self.cols, self.rows, self.dots_x, self.dots_y)

    def pan_dots(self, dx: float, dy: float) -> Viewport:
        """Move the view by a number of dots; positive dx goes east, positive dy goes south."""
        lat, lon = self.to_geo(self.width / 2.0 + dx, self.height / 2.0 + dy)
        return self._moved(lat, lon)

    def pan_cells(self, dcols: float, drows: float) -> Viewport:
        """Move the view by a number of terminal cells."""
        return self.pan_dots(dcols * self.dots_x, drows * self.dots_y)

    def pan_degrees(self, dlat: float, dlon: float) -> Viewport:
        """Move the center by degrees; positive dlat goes north, positive dlon goes east."""
        return self._moved(self.center_lat + dlat, self.center_lon + dlon)

    def centered_on(self, lat: float, lon: float) -> Viewport:
        return self._moved(lat, lon)

    def zoom(self, factor: float, anchor: Dot | None = None) -> Viewport:
        """Zoom in by factor (above 1 zooms in, below 1 zooms out). The dot at anchor, the center by default, keeps its
        position on the map."""
        if factor <= 0:
            raise ValueError("zoom factor must be positive")
        deg_per_dot = max(MIN_DEG_PER_DOT, min(MAX_DEG_PER_DOT, self.deg_per_dot / factor))
        if anchor is None:
            return self._moved(self.center_lat, self.center_lon, deg_per_dot)
        lat, lon = self.to_geo(*anchor)
        view = self._moved(self.center_lat, self.center_lon, deg_per_dot)
        for _ in range(3):  # the longitude scale depends on the center latitude, so settle it by iteration
            x, y = view.to_dot(lat, lon)
            view = view.pan_dots(x - anchor[0], y - anchor[1])
        return view

    def resized(self, cols: int, rows: int) -> Viewport:
        """The same center and zoom on a canvas of another size."""
        return Viewport(self.center_lat, self.center_lon, self.deg_per_dot, cols, rows, self.dots_x, self.dots_y)

    @classmethod
    def fit(
        cls, bounds: Bounds, cols: int, rows: int, *, dots_x: int = 2, dots_y: int = 4, margin: float = 0.05
    ) -> Viewport:
        """The view that shows bounds entirely, centered, with a margin (a fraction of each side) all round."""
        lat, lon = bounds.center
        scale = round(math.cos(math.radians(max(-MAX_CENTER_LAT, min(MAX_CENTER_LAT, lat)))), 9)
        usable = 1.0 - 2.0 * max(0.0, min(0.45, margin))
        by_lat = (bounds.north - bounds.south) / (rows * dots_y * usable)
        by_lon = bounds.lon_span * scale / (cols * dots_x * usable)
        return cls(lat, lon, max(by_lat, by_lon, MIN_DEG_PER_DOT), cols, rows, dots_x, dots_y)

    @classmethod
    def fit_points(
        cls, points: Sequence[LatLon], cols: int, rows: int, *, dots_x: int = 2, dots_y: int = 4, margin: float = 0.05
    ) -> Viewport:
        """fit() around a set of positions."""
        return cls.fit(bounds_of(points), cols, rows, dots_x=dots_x, dots_y=dots_y, margin=margin)
