"""Which stations matter for a storm: close to it now, or close to where it is forecast to go.

Pure functions over plain numbers, with no dependence on the NHC models: the caller turns a forecast into a handful of
`TrackFix` points. Works for anything with an id and a position, so NDBC stations and CO-OPS gauges share it.

A station is included when any of these holds:

- its distance to the storm's current center is within `radius_now_nm`;
- its distance to the forecast track is within `radius_track_nm`, where the track is the great-circle path through the
  center and every fix, sampled hourly out to `track_hours`;
- it is on the watchlist (always, whatever its distance, and never dropped by the cap).

Stations are ranked by current distance and capped at `max_stations`; the cap only trims non-watchlist stations.
"""

from __future__ import annotations

import math
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Protocol

from eyewall.config import NearbyConfig
from eyewall.geo import LatLon, bearing_deg, distance_to_segment_nm, haversine_nm, interpolate

_REFINE_STEPS = 40


@dataclass(frozen=True, slots=True)
class TrackFix:
    """A forecast position `hours` after the moment of the storm's current center. lon is east-positive degrees."""

    hours: float
    lat: float
    lon: float


class Located(Protocol):
    """Anything with an id and a position, such as an NDBC Station or a CO-OPS TideStation."""

    @property
    def id(self) -> str: ...

    @property
    def lat(self) -> float: ...

    @property
    def lon(self) -> float: ...


@dataclass(frozen=True, slots=True)
class NearbyStation[S: Located]:
    """A station and how it relates to the storm.

    bearing_deg is the direction from the storm's current center to the station (0 north, clockwise). The closest
    approach is the least distance between the station and the storm's path from now on, and eta_hours is when the storm
    gets there: 0 when it is closest right now (already moving away) or when there is no forecast track.
    """

    station: S
    distance_nm: float
    bearing_deg: float
    closest_approach_nm: float
    eta_hours: float
    near_now: bool
    near_track: bool
    watchlisted: bool


def hourly_track(center: LatLon, fixes: Iterable[TrackFix], track_hours: int) -> list[LatLon]:
    """The path as positions one hour apart: index 0 is the center, index h is h hours later.

    Fixes at or before hour 0 are ignored (the center is hour 0) and a repeated hour keeps its last fix. The path ends
    at `track_hours` or at the last fix, whichever comes first, and positions between fixes lie on the great circle.
    """
    by_hour: dict[float, TrackFix] = {}
    for fix in sorted(fixes, key=lambda f: f.hours):
        if fix.hours > 0:
            by_hour[fix.hours] = fix
    anchors: list[tuple[float, LatLon]] = [(0.0, center)]
    anchors.extend((hours, (fix.lat, fix.lon)) for hours, fix in by_hour.items())
    last = min(track_hours, math.floor(anchors[-1][0]))
    points = [center]
    for hour in range(1, last + 1):
        for (h0, p0), (h1, p1) in pairwise(anchors):
            if h0 <= hour <= h1:
                points.append(interpolate(p0, p1, (hour - h0) / (h1 - h0)))
                break
    return points


def _closest_time(station: LatLon, a: LatLon, b: LatLon) -> float:
    """The fraction of the way from a to b at which the path is nearest the station (ternary search)."""
    low, high = 0.0, 1.0
    for _ in range(_REFINE_STEPS):
        m1, m2 = low + (high - low) / 3, high - (high - low) / 3
        if haversine_nm(station, interpolate(a, b, m1)) <= haversine_nm(station, interpolate(a, b, m2)):
            high = m2
        else:
            low = m1
    return (low + high) / 2


def _closest_approach(station: LatLon, points: Sequence[LatLon], now_nm: float) -> tuple[float, float]:
    """(least distance to the path in nautical miles, hours until the path gets there)."""
    best, best_index = now_nm, -1
    for index, (a, b) in enumerate(pairwise(points)):
        distance = distance_to_segment_nm(station, a, b)
        if distance < best:
            best, best_index = distance, index
    if best_index < 0:
        return now_nm, 0.0
    fraction = _closest_time(station, points[best_index], points[best_index + 1])
    return best, best_index + fraction


def nearby_stations[S: Located](
    center: LatLon,
    track: Iterable[TrackFix],
    stations: Iterable[S],
    *,
    config: NearbyConfig | None = None,
    watchlist: Collection[str] = (),
) -> list[NearbyStation[S]]:
    """The stations that matter for one storm, nearest to its current center first.

    center is the storm's current (lat, lon) and track its forecast fixes, with hours counted from the center's own
    time. The radii, track length and cap come from `config` (the defaults of `eyewall.config.NearbyConfig` when
    omitted). Watchlist ids match case-insensitively. When the watchlist alone is longer than the cap, all of it stays
    and no other station does.
    """
    cfg = config or NearbyConfig()
    points = hourly_track(center, track, cfg.track_hours)
    step = max((haversine_nm(a, b) for a, b in pairwise(points)), default=0.0)
    wanted = {w.strip().upper() for w in watchlist}
    watched: list[NearbyStation[S]] = []
    others: list[NearbyStation[S]] = []
    for station in stations:
        here: LatLon = (station.lat, station.lon)
        distance = haversine_nm(center, here)
        listed = station.id.upper() in wanted
        near_now = distance <= cfg.radius_now_nm
        # Cheap rejection: the path is never nearer than its nearest hourly sample minus half a step.
        sample = min((haversine_nm(here, p) for p in points), default=distance)
        if not (near_now or listed or sample - step / 2 <= cfg.radius_track_nm):
            continue
        approach, eta = _closest_approach(here, points, distance)
        near_track = approach <= cfg.radius_track_nm
        if not (near_now or near_track or listed):
            continue
        entry = NearbyStation(station, distance, bearing_deg(center, here), approach, eta, near_now, near_track, listed)
        (watched if listed else others).append(entry)
    watched.sort(key=lambda n: (n.distance_nm, n.station.id))
    others.sort(key=lambda n: (n.distance_nm, n.station.id))
    room = max(0, cfg.max_stations - len(watched))
    chosen = watched + others[:room]
    chosen.sort(key=lambda n: (n.distance_nm, n.station.id))
    return chosen
