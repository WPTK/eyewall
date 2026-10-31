"""Shared helpers for the render tests: golden files and a hand-built storm that resembles Hurricane Erin (2025).

The storm is synthetic, a plausible snapshot for exercising the layers, not recorded data. The golden files are
UTF-8 text, compared line by line with trailing spaces ignored; set EYEWALL_UPDATE_GOLDEN=1 to rewrite them after an
intentional change to the drawing, then read the diff before committing.
"""

from __future__ import annotations

import os
from pathlib import Path

from eyewall.geo import bearing_deg, destination
from eyewall.mapdata.loader import load_layer
from eyewall.palette import WatchWarning
from eyewall.render.layers import (
    ForecastPoint,
    MapScene,
    StationMark,
    StormScene,
    TrackPoint,
    WarningSegment,
    WindRadii,
)
from eyewall.render.projection import LatLon

GOLDEN_DIR = Path(__file__).parent / "golden"


def assert_golden(name: str, text: str) -> None:
    """Compare text with tests/golden/<name>; with EYEWALL_UPDATE_GOLDEN=1, write it instead."""
    path = GOLDEN_DIR / name
    actual = "\n".join(line.rstrip() for line in text.splitlines()) + "\n"
    if os.environ.get("EYEWALL_UPDATE_GOLDEN") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(actual.encode("utf-8"))
        return
    assert path.exists(), f"missing golden file {path}; run with EYEWALL_UPDATE_GOLDEN=1 to create it"
    expected = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    assert actual == expected, f"{name} differs from its golden file; rerun with EYEWALL_UPDATE_GOLDEN=1 to review"


def coast_run(south: float, north: float, west: float, east: float) -> tuple[LatLon, ...]:
    """The longest unbroken run of coastline vertices inside a box, so a warning can sit exactly on the coast."""
    best: list[LatLon] = []
    run: list[LatLon] = []
    for path in load_layer("coast").paths:
        # Long coastlines are stored in pieces that share an end vertex, so a run carries on into the next piece.
        if not (run and path.points[0] == run[-1]):
            run = []
        for lat, lon in path.points:
            if south <= lat <= north and west <= lon <= east:
                if not run or run[-1] != (lat, lon):
                    run.append((lat, lon))
                if len(run) > len(best):
                    best = run[:]
            else:
                run = []
    return tuple(best)


# Cone radius in nautical miles at the initial position and at 12, 24, 36, 48, 72, 96 and 120 hours.
CONE_RADII_NM = (10.0, 26.0, 39.0, 53.0, 67.0, 94.0, 142.0, 196.0)


def cone_ring(points: list[LatLon], radii_nm: tuple[float, ...]) -> tuple[LatLon, ...]:
    """A cone outline: the track offset to both sides by the cone radius, closed with a half circle at each end."""
    headings = []
    for i in range(len(points)):
        a = points[max(i - 1, 0)]
        b = points[min(i + 1, len(points) - 1)]
        headings.append(bearing_deg(a, b))

    def rounded(p: LatLon) -> LatLon:
        return (round(p[0], 5), round(p[1], 5))

    left = [rounded(destination(p, h - 90.0, r)) for p, h, r in zip(points, headings, radii_nm, strict=True)]
    right = [rounded(destination(p, h + 90.0, r)) for p, h, r in zip(points, headings, radii_nm, strict=True)]
    end = [rounded(destination(points[-1], headings[-1] - 90.0 + 15.0 * k, radii_nm[-1])) for k in range(1, 12)]
    start = [rounded(destination(points[0], headings[0] + 90.0 + 15.0 * k, radii_nm[0])) for k in range(1, 12)]
    return tuple(left + end + right[::-1] + start)


def erin_like_scene() -> MapScene:
    """A major hurricane north of the Leeward Islands, forecast to curve past the Outer Banks, with buoys and gauges."""
    best = (
        TrackPoint(16.5, -30.5, 35),
        TrackPoint(17.2, -36.0, 45),
        TrackPoint(17.9, -41.5, 55),
        TrackPoint(18.6, -46.5, 70),
        TrackPoint(19.1, -51.5, 90),
        TrackPoint(19.7, -56.0, 120),
        TrackPoint(20.3, -60.0, 140),
        TrackPoint(21.3, -63.5, 125),
        TrackPoint(22.6, -66.5, 115),
        TrackPoint(23.6, -68.2, 105),
    )
    forecast = (
        ForecastPoint(25.8, -70.5, 100, "00Z Tue"),
        ForecastPoint(27.4, -71.4, 95, "12Z Tue"),
        ForecastPoint(29.1, -72.1, 90, "00Z Wed"),
        ForecastPoint(30.9, -72.6, 85, "12Z Wed"),
        ForecastPoint(34.7, -72.2, 80, "12Z Thu"),
        ForecastPoint(39.5, -68.0, 65, "12Z Fri"),
        ForecastPoint(44.0, -58.0, 55, "12Z Sat"),
    )
    center = best[-1]
    track = [(center.lat, center.lon), *((f.lat, f.lon) for f in forecast)]
    cone = cone_ring(track, CONE_RADII_NM)
    outer_banks = coast_run(34.7, 36.9, -76.9, -75.2)
    south_of_banks = coast_run(33.9, 34.7, -78.3, -76.4)
    chesapeake = coast_run(36.9, 37.3, -76.5, -75.5)
    storm = StormScene(
        name="ERIN",
        center=center,
        best_track=best,
        forecast=forecast,
        cone=(cone,),
        warnings=(
            WarningSegment(WatchWarning.TROPICAL_STORM_WATCH, south_of_banks),
            WarningSegment(WatchWarning.HURRICANE_WATCH, outer_banks),
            WarningSegment(WatchWarning.TROPICAL_STORM_WARNING, outer_banks[: len(outer_banks) // 2]),
        ),
        surge=(WarningSegment(WatchWarning.SURGE_WATCH, chesapeake or outer_banks[-3:]),),
        radii=(
            WindRadii(
                center.lat,
                center.lon,
                kt34=(240.0, 210.0, 150.0, 200.0),
                kt50=(120.0, 100.0, 70.0, 100.0),
                kt64=(70.0, 60.0, 40.0, 60.0),
            ),
        ),
    )
    return MapScene(
        storms=(storm,),
        buoys=(
            StationMark(27.5, -71.5, 42.0, label="41047"),
            StationMark(31.0, -69.6, 28.0, label="41048"),
            StationMark(28.9, -78.5, 12.0, label="41010"),
            StationMark(31.8, -75.2, 21.0, label="41002"),
            StationMark(35.0, -75.4, 15.0, label="41025"),
            StationMark(32.5, -79.1, None, stale=True, label="41004"),
        ),
        tide_gauges=(
            StationMark(36.18, -75.75, label="8651370"),
            StationMark(35.80, -75.55, label="8652587"),
            StationMark(34.72, -76.67, label="8656483"),
            StationMark(34.23, -77.95, label="8658120"),
        ),
    )
