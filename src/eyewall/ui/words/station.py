"""Sentences about buoys and tide gauges: what a buoy reads, which way it is trending, and when it fell silent."""

from __future__ import annotations

from datetime import datetime, timedelta, tzinfo

from eyewall.clock import format_age
from eyewall.geo import compass_point
from eyewall.models.obs import Observation, Station, TideSeries, TideStation
from eyewall.state.nearby import NearbyStation
from eyewall.state.tides import is_silent, latest_residual, observation_age
from eyewall.state.trends import Extremes, PressureTendency, Trend
from eyewall.ui.products import fmt_local
from eyewall.ui.stations import FALL_RAPID_HPA, FALL_WARN_HPA
from eyewall.ui.words import Words, distance_text, round5
from eyewall.units import Preset

_CLOSE_NM = 5  # nearer than this to the storm centre reads as "at"
_STEADY_PRESSURE_HPA = 0.5
_STEADY_WIND_MPS = 1.0
_AT_PREDICTED_FT = 0.1


def _hours(hours: float) -> str:
    count = max(1, round(hours))
    return f"{count} hour" if count == 1 else f"{count} hours"


# ------------------------------------------------------------------------------------------------------------ a buoy


def _reading_parts(obs: Observation, waves: Observation | None, preset: Preset, sources: list[str]) -> list[str]:
    """`wind 28 mph from the NE`, `gusting 35 mph`, `waves 12 ft`: what the buoy reads, in that order."""
    parts: list[str] = []
    if obs.wind_speed_mps is None:
        parts.append("wind not reported")
    else:
        wind = f"wind {preset.fmt_wind(obs.wind_speed_mps, 'mps')}"
        sources.append("obs.wind_speed_mps")
        if obs.wind_dir_deg is not None:
            wind += f" from the {compass_point(obs.wind_dir_deg)}"
            sources.append("obs.wind_dir_deg")
        parts.append(wind)
    if obs.gust_mps is not None:
        parts.append(f"gusting {preset.fmt_wind(obs.gust_mps, 'mps')}")
        sources.append("obs.gust_mps")
    if waves is not None and waves.wave_height_m is not None:
        parts.append(f"waves {preset.fmt_length(waves.wave_height_m, 'm')}")
        sources.append("waves.wave_height_m")
    return parts


def buoy_lead(
    entry: NearbyStation[Station], storm_name: str, obs: Observation, waves: Observation | None, preset: Preset
) -> Words:
    """`Buoy 41047 (Bahamas), 120 mi NE of Erin: wind 28 mph from the NE, gusting 35 mph, waves 12 ft.`

    `waves` is the row to read the wave height from (the newest row can lack it; see `ui.stations.last_reading`).
    """
    sources = ["entry.station.id", "entry.station.name", "entry.distance_nm", "entry.bearing_deg"]
    name = f" ({entry.station.name})" if entry.station.name else ""
    if round5(entry.distance_nm) < _CLOSE_NM:
        where = f"at {storm_name}"
    else:
        where = f"{distance_text(preset, nm=entry.distance_nm)} {compass_point(entry.bearing_deg)} of {storm_name}"
    parts = _reading_parts(obs, waves, preset, sources)
    return Words(f"Buoy {entry.station.id}{name}, {where}: {', '.join(parts)}.", tuple(sources))


def buoy_summary(station: Station, obs: Observation, waves: Observation | None, preset: Preset) -> Words:
    """`Buoy 41047 (Bahamas): wind 28 mph from the NE, gusting 35 mph, waves 12 ft.`, for a buoy with no storm."""
    sources = ["station.id", "station.name"]
    name = f" ({station.name})" if station.name else ""
    parts = _reading_parts(obs, waves, preset, sources)
    return Words(f"Buoy {station.id}{name}: {', '.join(parts)}.", tuple(sources))


def buoy_brief(
    obs: Observation,
    waves: Observation | None,
    tendency: PressureTendency | None,
    preset: Preset,
    arrows: tuple[str, str, str],
) -> Words:
    """The second line of a list row: `wind 28 mph NE, gust 35 mph · 1004 mb falling v · waves 12 ft`.

    `arrows` are the rising, falling and steady glyphs; a word always goes with the arrow."""
    rising, falling, steady = arrows
    sources = ["obs.wind_speed_mps"]
    parts: list[str] = []
    if obs.wind_speed_mps is None:
        parts.append("wind not reported")
    else:
        wind = f"wind {preset.fmt_wind(obs.wind_speed_mps, 'mps')}"
        if obs.wind_dir_deg is not None:
            wind += f" {compass_point(obs.wind_dir_deg)}"
            sources.append("obs.wind_dir_deg")
        if obs.gust_mps is not None:
            wind += f", gust {preset.fmt_wind(obs.gust_mps, 'mps')}"
            sources.append("obs.gust_mps")
        parts.append(wind)
    if obs.pressure_hpa is not None:
        pressure = preset.fmt_pressure(obs.pressure_hpa, "hpa")
        sources.append("obs.pressure_hpa")
        if tendency is not None:
            sources.append("tendency.delta_hpa")
            if tendency.delta_hpa <= FALL_RAPID_HPA:
                pressure += f" falling fast {falling}"
            elif tendency.delta_hpa <= FALL_WARN_HPA:
                pressure += f" falling {falling}"
            elif tendency.delta_hpa >= -FALL_WARN_HPA:
                pressure += f" rising {rising}"
            else:
                pressure += f" steady {steady}"
        parts.append(pressure)
    if waves is not None and waves.wave_height_m is not None:
        parts.append(f"waves {preset.fmt_length(waves.wave_height_m, 'm')}")
        sources.append("waves.wave_height_m")
    return Words(" · ".join(parts), tuple(sources))


def pressure_trend(tendency: PressureTendency | None, preset: Preset) -> Words | None:
    """`Pressure is falling fast: down 3.2 mb in the last 3 hours.` (steady, falling, rising or falling fast)"""
    if tendency is None:
        return None
    delta = tendency.delta_hpa
    span = _hours(tendency.hours)
    sources = ("tendency.delta_hpa", "tendency.hours")
    if delta <= FALL_RAPID_HPA:
        word = "falling fast"
    elif delta <= FALL_WARN_HPA:
        word = "falling"
    elif delta >= -FALL_WARN_HPA:
        word = "rising"
    else:
        return Words(f"Pressure is steady over the last {span}.", sources)
    size = preset.fmt_pressure(abs(delta), "hpa", decimals=2 if preset.pressure == "inhg" else 1)
    return Words(f"Pressure is {word}: {'down' if delta < 0 else 'up'} {size} in the last {span}.", sources)


def _trend_sentence(subject: str, trend: Trend | None, size: str, sources: tuple[str, ...]) -> Words | None:
    """`subject` is `Wind` or `Waves`: `Wind has picked up by ...`, `Waves have eased by ...`, `Wind is steady ...`."""
    if trend is None:
        return None
    span = _hours(trend.hours)
    plural = subject == "Waves"
    if trend.direction == "steady":
        return Words(f"{subject} {'are' if plural else 'is'} steady over the last {span}.", sources)
    word = "picked up" if trend.direction == "rising" else "eased"
    return Words(f"{subject} {'have' if plural else 'has'} {word} by {size} in the last {span}.", sources)


_TREND_SOURCES = ("trend.delta", "trend.direction", "trend.hours")


def wind_trend_sentence(trend: Trend | None, preset: Preset) -> Words | None:
    """`Wind has picked up by 8 kt in the last 3 hours.` / `eased by` / `steady`"""
    size = "" if trend is None else preset.fmt_wind(abs(trend.delta), "mps")
    return _trend_sentence("Wind", trend, size, _TREND_SOURCES)


def wave_trend_sentence(trend: Trend | None, preset: Preset) -> Words | None:
    """`Waves have picked up by 3 ft in the last 3 hours.` / `eased by` / `steady`"""
    size = "" if trend is None else preset.fmt_length(abs(trend.delta), "m", decimals=1)
    return _trend_sentence("Waves", trend, size, _TREND_SOURCES)


def approach_sentence(entry: NearbyStation[Station] | NearbyStation[TideStation], preset: Preset) -> Words:
    """`The forecast track passes about 40 mi from here in about 18 hours.`"""
    closest = distance_text(preset, nm=entry.closest_approach_nm)
    sources = ("entry.closest_approach_nm", "entry.eta_hours")
    if entry.eta_hours < 1:
        return Words(f"The forecast track is closest to here now, about {closest} away.", sources)
    return Words(f"The forecast track passes about {closest} from here in about {_hours(entry.eta_hours)}.", sources)


def state_sentence(state: str, obs: Observation | None, now: datetime, tz: tzinfo | None) -> Words | None:
    """What to say about a buoy that is not simply reporting (`ui.stations.buoy_state`); None for `ok`."""
    if state == "silent" and obs is not None:
        age = format_age(max(timedelta(0), now - obs.time).total_seconds())
        return Words(f"No report for {age}. Last heard {fmt_local(obs.time, tz)}.", ("obs.time",))
    if state == "dark":
        return Words("Not reporting (NOAA lists it as dark).")
    if state == "waiting":
        return Words("Waiting for the first report.")
    return None


ABOUT_BUOY_WINDS = (
    "A buoy measures wind a few meters (10 to 15 feet) above the sea, as an average over about 8 minutes, and the "
    "gust is the strongest 5 to 8 seconds. NHC's storm winds are a 1 minute average at 10 meters (33 feet), so a "
    "buoy usually reads lower than the storm's stated wind even when it sits in it."
)


def about_buoy_winds() -> Words:
    return Words(ABOUT_BUOY_WINDS)


def extremes_sentence(extremes: Extremes, preset: Preset, tz: tzinfo | None) -> Words | None:
    """`Highest gust 63 kt at Mon 05:00 PM EDT; lowest pressure 988 mb at Mon 07:00 PM EDT.`"""
    parts: list[str] = []
    sources: list[str] = []
    if extremes.peak_gust_mps is not None and extremes.peak_gust_time is not None:
        gust = preset.fmt_wind(extremes.peak_gust_mps, "mps")
        parts.append(f"Highest gust {gust} at {fmt_local(extremes.peak_gust_time, tz)}")
        sources += ["extremes.peak_gust_mps", "extremes.peak_gust_time"]
    if extremes.min_pressure_hpa is not None and extremes.min_pressure_time is not None:
        size = preset.fmt_pressure(extremes.min_pressure_hpa, "hpa", decimals=2 if preset.pressure == "inhg" else None)
        parts.append(
            f"{'lowest' if parts else 'Lowest'} pressure {size} at {fmt_local(extremes.min_pressure_time, tz)}"
        )
        sources += ["extremes.min_pressure_hpa", "extremes.min_pressure_time"]
    return Words("; ".join(parts) + ".", tuple(sources)) if parts else None


def readings_summary(
    observations: list[Observation], since: datetime, preset: Preset, tz: tzinfo | None
) -> Words | None:
    """`Since Mon 05:00 PM EDT, wind has picked up from 20 kt to 35 kt and pressure has fallen 4.1 mb.`"""
    rows = sorted((o for o in observations if o.time >= since), key=lambda o: o.time)
    parts: list[str] = []
    sources: list[str] = []
    winds = [o.wind_speed_mps for o in rows if o.wind_speed_mps is not None]
    if len(winds) >= 2:
        first, last = winds[0], winds[-1]
        a, b = preset.fmt_wind(first, "mps"), preset.fmt_wind(last, "mps")
        if last - first > _STEADY_WIND_MPS:
            parts.append(f"wind has picked up from {a} to {b}")
        elif first - last > _STEADY_WIND_MPS:
            parts.append(f"wind has eased from {a} to {b}")
        else:
            parts.append(f"wind has held near {b}")
        sources.append("observations[].wind_speed_mps")
    pressures = [o.pressure_hpa for o in rows if o.pressure_hpa is not None]
    if len(pressures) >= 2:
        change = pressures[-1] - pressures[0]
        size = preset.fmt_pressure(abs(change), "hpa", decimals=2 if preset.pressure == "inhg" else 1)
        if change <= -_STEADY_PRESSURE_HPA:
            parts.append(f"pressure has fallen {size}")
        elif change >= _STEADY_PRESSURE_HPA:
            parts.append(f"pressure has risen {size}")
        else:
            parts.append("pressure has held steady")
        sources.append("observations[].pressure_hpa")
    if not parts:
        return None
    return Words(f"Since {fmt_local(since, tz)}, {' and '.join(parts)}.", ("since", *sources))


# ----------------------------------------------------------------------------------------------------------- a gauge


def gauge_brief(station: TideStation, series: TideSeries | None, now: datetime, preset: Preset) -> Words:
    """The second line of a gauge row: `water 1.8 ft above the predicted tide`, or why there is nothing to say."""
    if series is None or series.latest_level is None:
        return Words("waiting for the first water level")
    residual = latest_residual(series)
    if residual is None:
        return Words("no tide prediction to compare with", ("series.predictions",))
    sources = ("residual.observed_ft", "residual.predicted_ft")
    if abs(residual.residual_ft) < _AT_PREDICTED_FT:
        return Words("water at the predicted tide", sources)
    size = preset.fmt_length(abs(residual.residual_ft), "ft", decimals=1)
    return Words(f"water {size} {'above' if residual.residual_ft > 0 else 'below'} the predicted tide", sources)


def gauge_sentence(station: TideStation, series: TideSeries | None, now: datetime, preset: Preset) -> Words:
    """`Water at Duck is 1.8 ft above the predicted tide.` or why there is nothing to say."""
    if series is None or series.latest_level is None:
        return Words("Waiting for the first water level.")
    age = observation_age(series, now)
    if is_silent(series, now) and age is not None:
        place = station.name or station.id
        return Words(f"No report from {place} for {format_age(age.total_seconds())}.", ("series.latest_level.time",))
    residual = latest_residual(series)
    if residual is None:
        return Words(f"No tide prediction to compare with at {station.name or station.id}.", ("series.predictions",))
    sources = ("residual.observed_ft", "residual.predicted_ft", "station.name")
    place = station.name or station.id
    if abs(residual.residual_ft) < _AT_PREDICTED_FT:
        return Words(f"Water at {place} is at the predicted tide.", sources)
    size = preset.fmt_length(abs(residual.residual_ft), "ft", decimals=1)
    side = "above" if residual.residual_ft > 0 else "below"
    return Words(f"Water at {place} is {size} {side} the predicted tide.", sources)
