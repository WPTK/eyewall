"""From the store to the renderer's inputs.

`eyewall.render` knows nothing about NHC models; this module turns a `StormState`, the outlook and the nearby stations
into the plain dataclasses `render.layers` draws. Nothing here touches Textual.
"""

from __future__ import annotations

from datetime import datetime

from eyewall.geo import LatLon
from eyewall.models.forecast import ForecastAdvisory
from eyewall.models.outlook import Outlook
from eyewall.models.wind import QuadrantRadii
from eyewall.render import layers as L
from eyewall.state.store import Store, StormState
from eyewall.state.trends import observation_age
from eyewall.units import convert

# Where each basin sits, as two opposite corners (lat, lon), for the view when no storm is selected.
BASIN_BOUNDS: dict[str, tuple[LatLon, LatLon]] = {
    "AL": ((5.0, -100.0), (48.0, -5.0)),
    "EP": ((4.0, -140.0), (32.0, -84.0)),
    "CP": ((4.0, -180.0), (30.0, -130.0)),
}
STATION_STALE_AFTER_H = 3.0
MAX_MAP_STATIONS = 12
_RISK_RANK = {"low": 1, "medium": 2, "high": 3}


def basin_points(basins: tuple[str, ...]) -> list[LatLon]:
    """Corner points of the enabled basins, to fit the view around."""
    points: list[LatLon] = []
    for code in basins or tuple(BASIN_BOUNDS):
        points.extend(BASIN_BOUNDS.get(code, ()))
    return points


def _quadrants(radii: QuadrantRadii | None) -> L.QuadrantRadii | None:
    if radii is None:
        return None
    return (float(radii.ne or 0), float(radii.se or 0), float(radii.sw or 0), float(radii.nw or 0))


def _forecast_label(valid: datetime | None) -> str | None:
    return None if valid is None else f"{valid:%H}Z {valid:%a}"


def _forecast_points(state: StormState) -> tuple[L.ForecastPoint, ...]:
    gis = state.forecast_gis
    if gis is not None and gis.points:
        return tuple(
            L.ForecastPoint(p.lat, p.lon, p.max_wind_kt, _forecast_label(p.valid)) for p in gis.points if p.tau > 0
        )
    tcm: ForecastAdvisory | None = state.advisories.forecast
    if tcm is None:
        return ()
    return tuple(
        L.ForecastPoint(f.lat, f.lon, f.max_wind_kt, _forecast_label(f.valid))
        for f in tcm.forecast_fixes
        if f.lat is not None and f.lon is not None
    )


def storm_scene(state: StormState) -> L.StormScene:
    """Everything the map draws for one storm: center, past track, forecast, cone, warnings and current wind radii."""
    storm = state.storm
    center = None
    if storm.lat is not None and storm.lon is not None:
        center = L.TrackPoint(storm.lat, storm.lon, storm.intensity_kt)
    best: tuple[L.TrackPoint, ...] = ()
    if state.track is not None:
        best = tuple(L.TrackPoint(f.lat, f.lon, f.vmax_kt) for f in state.track.fixes)
    gis = state.forecast_gis
    cone = tuple(gis.cone) if gis is not None else ()
    warnings: tuple[L.WarningSegment, ...] = ()
    if gis is not None:
        warnings = tuple(L.WarningSegment(s.kind, s.points) for s in gis.watch_warnings if s.kind is not None)
    radii: tuple[L.WindRadii, ...] = ()
    tcm = state.advisories.forecast
    if tcm is not None and not tcm.radii.empty:
        lat = tcm.lat if tcm.lat is not None else (center.lat if center else None)
        lon = tcm.lon if tcm.lon is not None else (center.lon if center else None)
        if lat is not None and lon is not None:
            radii = (
                L.WindRadii(
                    lat, lon, _quadrants(tcm.radii.kt34), _quadrants(tcm.radii.kt50), _quadrants(tcm.radii.kt64)
                ),
            )
    return L.StormScene(
        name=storm.name,
        center=center,
        best_track=best,
        forecast=_forecast_points(state),
        cone=cone,
        warnings=warnings,
        radii=radii,
    )


def outlook_areas(outlook: Outlook | None) -> tuple[L.OutlookArea, ...]:
    """The outlook shapes colored by the higher of the 2 day and 7 day risk, labelled with the 7 day chance."""
    if outlook is None:
        return ()
    areas: list[L.OutlookArea] = []
    for system in outlook.gis.systems:
        if not system.polygons:
            continue
        risks = [r for r in (system.risk_2day, system.risk_7day) if r]
        risk = max(risks, key=lambda r: _RISK_RANK.get(r.lower(), 0)) if risks else "low"
        chance = system.prob_7day if system.prob_7day is not None else system.prob_2day
        areas.append(L.OutlookArea(system.polygons, risk, None if chance is None else f"{chance}%"))
    return tuple(areas)


def _wind_kt_of(store: Store, station_id: str, now: datetime) -> tuple[float | None, bool]:
    """The newest wind at a station in knots, and whether the reading is too old to trust."""
    series = store.series.get(station_id.upper())
    if series is not None and series.latest is not None:
        obs = series.latest
        age = observation_age(series, now)
        stale = age is None or age.total_seconds() > STATION_STALE_AFTER_H * 3600
    else:
        latest = store.latest.get(station_id.upper())
        if latest is None:
            return None, True
        obs = latest.observation
        stale = False
    if obs.wind_speed_mps is None:
        return None, stale
    return convert(obs.wind_speed_mps, "mps", "kt"), stale


def station_marks(
    store: Store, storm_id: str, now: datetime
) -> tuple[tuple[L.StationMark, ...], tuple[L.StationMark, ...]]:
    """Buoy and tide gauge marks near a storm, nearest first. This is the hook M6 builds on."""
    buoys = []
    for entry in store.nearby_buoys(storm_id)[:MAX_MAP_STATIONS]:
        wind, stale = _wind_kt_of(store, entry.station.id, now)
        buoys.append(L.StationMark(entry.station.lat, entry.station.lon, wind, stale, entry.station.id))
    tides = [
        L.StationMark(entry.station.lat, entry.station.lon, None, False, entry.station.id)
        for entry in store.nearby_tides(storm_id)[:MAX_MAP_STATIONS]
    ]
    return tuple(buoys), tuple(tides)


def map_scene(store: Store, now: datetime, selected: str | None, *, cursor: LatLon | None = None) -> L.MapScene:
    """The dashboard map: every storm, the outlook areas, and the stations near the selected storm."""
    storms = tuple(storm_scene(state) for state in store.storms.values())
    buoys: tuple[L.StationMark, ...] = ()
    tides: tuple[L.StationMark, ...] = ()
    if selected in store.storms:
        buoys, tides = station_marks(store, selected, now)
    return L.MapScene(
        storms=storms,
        outlook=outlook_areas(store.outlook),
        buoys=buoys,
        tide_gauges=tides,
        cursor=cursor,
    )
