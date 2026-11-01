"""From the store to the renderer's inputs.

`eyewall.render` knows nothing about NHC models; this module turns a `StormState`, the outlook and the nearby stations
into the plain dataclasses `render.layers` draws. Nothing here touches Textual.
"""

from __future__ import annotations

from datetime import datetime

from eyewall.geo import LatLon
from eyewall.models.forecast import ForecastAdvisory
from eyewall.models.obs import Station, TideStation
from eyewall.models.outlook import Outlook
from eyewall.models.wind import QuadrantRadii
from eyewall.render import layers as L
from eyewall.state.store import Store, StormState
from eyewall.state.tides import SILENT_AFTER as TIDE_SILENT_AFTER
from eyewall.state.tides import observation_age as tide_age
from eyewall.state.trends import SILENT_AFTER
from eyewall.ui.stations import newest_observation, tide_wind
from eyewall.units import convert

# Where each basin sits, as two opposite corners (lat, lon), for the view when no storm is selected.
BASIN_BOUNDS: dict[str, tuple[LatLon, LatLon]] = {
    "AL": ((5.0, -100.0), (48.0, -5.0)),
    "EP": ((4.0, -140.0), (32.0, -84.0)),
    "CP": ((4.0, -180.0), (30.0, -130.0)),
}
MAX_MAP_STATIONS = 12
_RISK_RANK = {"low": 1, "medium": 2, "high": 3}


def basin_points(basins: tuple[str, ...]) -> list[LatLon]:
    """Corner points of the enabled basins, to fit the view around."""
    points: list[LatLon] = []
    for code in basins or tuple(BASIN_BOUNDS):
        points.extend(BASIN_BOUNDS.get(code, ()))
    return points


def quiet_points(areas: tuple[L.OutlookArea, ...], basins: tuple[str, ...]) -> list[LatLon]:
    """What the map fits when no storm is selected: the first enabled basin (the Atlantic unless the reader chose
    another or switched it off), widened to take in every outlook area, so a quiet day shows one basin and the
    places NHC is watching rather than the whole hemisphere."""
    points = list(BASIN_BOUNDS.get(basins[0] if basins else "AL", BASIN_BOUNDS["AL"]))
    for area in areas:
        points.extend(p for ring in area.rings for p in ring)
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
            L.ForecastPoint(p.lat, p.lon, p.max_wind_kt, _forecast_label(p.valid), p.tau)
            for p in gis.points
            if p.tau > 0
        )
    tcm: ForecastAdvisory | None = state.advisories.forecast
    if tcm is None:
        return ()
    return tuple(
        L.ForecastPoint(f.lat, f.lon, f.max_wind_kt, _forecast_label(f.valid), f.tau)
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
        id=storm.id,
        name=storm.name,
        center=center,
        best_track=best,
        forecast=_forecast_points(state),
        cone=cone,
        warnings=warnings,
        radii=radii,
    )


def outlook_areas(outlook: Outlook | None) -> tuple[L.OutlookArea, ...]:
    """The outlook shapes colored by the higher of the 2 day and 7 day risk, labelled with the 7 day chance and its
    span, so a number on the map is never bare."""
    if outlook is None:
        return ()
    areas: list[L.OutlookArea] = []
    for system in outlook.gis.systems:
        if not system.polygons:
            continue
        risks = [r for r in (system.risk_2day, system.risk_7day) if r]
        risk = max(risks, key=lambda r: _RISK_RANK.get(r.lower(), 0)) if risks else "low"
        days, chance = (7, system.prob_7day) if system.prob_7day is not None else (2, system.prob_2day)
        areas.append(L.OutlookArea(system.polygons, risk, None if chance is None else f"{chance}% in {days} days"))
    return tuple(areas)


def _wind_kt_of(store: Store, station_id: str, now: datetime) -> tuple[float | None, bool]:
    """The newest wind at a station in knots, and whether the reading is too old to trust."""
    obs = newest_observation(store, station_id)
    if obs is None:
        return None, True
    stale = now - obs.time > SILENT_AFTER
    if obs.wind_speed_mps is None:
        return None, stale
    return convert(obs.wind_speed_mps, "mps", "kt"), stale


def _tide_mark(store: Store, gauge: TideStation, now: datetime) -> L.StationMark:
    """A gauge colored by its own wind where it has an anemometer, dim when its newest water level is old."""
    series = store.tide_series.get(gauge.id)
    if series is None:
        return L.StationMark(gauge.lat, gauge.lon, None, False, gauge.id, gauge.name)
    age = tide_age(series, now)
    stale = age is None or age > TIDE_SILENT_AFTER
    wind = tide_wind(series, now)
    return L.StationMark(gauge.lat, gauge.lon, None if wind is None else wind.speed_kt, stale, gauge.id, gauge.name)


def _buoy_mark(store: Store, station: Station, now: datetime) -> L.StationMark:
    wind, stale = _wind_kt_of(store, station.id, now)
    return L.StationMark(station.lat, station.lon, wind, stale, station.id, station.name)


def station_marks(
    store: Store, storm_id: str, now: datetime
) -> tuple[tuple[L.StationMark, ...], tuple[L.StationMark, ...]]:
    """Buoy and tide gauge marks near a storm, nearest first, colored by reported wind and dim when stale."""
    buoys = tuple(_buoy_mark(store, e.station, now) for e in store.nearby_buoys(storm_id, now)[:MAX_MAP_STATIONS])
    tides = tuple(_tide_mark(store, e.station, now) for e in store.nearby_tides(storm_id, now)[:MAX_MAP_STATIONS])
    return buoys, tides


def watchlist_marks(store: Store, now: datetime) -> tuple[tuple[L.StationMark, ...], tuple[L.StationMark, ...]]:
    """The watchlisted stations the catalogs know, for the map when there is no storm to show stations around."""
    watched = {w.upper() for w in store.config.watchlist.ndbc}
    buoys = tuple(_buoy_mark(store, s, now) for s in store.stations.values() if s.id.upper() in watched)
    gauges = {w.upper() for w in store.config.watchlist.coops}
    tides = tuple(_tide_mark(store, g, now) for g in store.tide_stations if g.id.upper() in gauges)
    return buoys, tides


def map_scene(store: Store, now: datetime, selected: str | None, *, cursor: LatLon | None = None) -> L.MapScene:
    """The dashboard map: every storm, the outlook areas, and the stations near the selected storm."""
    storms = tuple(storm_scene(state) for state in store.storms.values())
    buoys: tuple[L.StationMark, ...] = ()
    tides: tuple[L.StationMark, ...] = ()
    if selected in store.storms:
        buoys, tides = station_marks(store, selected, now)
    elif not store.storms:
        buoys, tides = watchlist_marks(store, now)
    return L.MapScene(
        storms=storms,
        outlook=outlook_areas(store.outlook),
        buoys=buoys,
        tide_gauges=tides,
        cursor=cursor,
    )
