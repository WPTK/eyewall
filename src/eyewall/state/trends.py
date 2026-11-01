"""What a station's readings are doing: pressure tendency, wind trend, age, silence and interval extremes.

Pure functions over `eyewall.models.obs` records and an explicit `now`, so tests and replay control time. Winds stay in
metres per second and pressure in hectopascals, as NDBC reports them; the UI converts. Observation lists may be in any
order: the functions find the newest reading themselves.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from eyewall.models.obs import Observation, ObservationSeries, SupplementalReading

TENDENCY_HOURS = 3.0
STEADY_BAND_MPS = 1.0
STEADY_BAND_WAVE_M = 0.3
SILENT_AFTER = timedelta(hours=2)
_PAIR_TOLERANCE_MIN = 20.0

Direction = Literal["rising", "falling", "steady"]


@dataclass(frozen=True, slots=True)
class PressureTendency:
    """The change in pressure over about three hours, in hPa. source says where the number came from.

    "ptdy" is NDBC's own PTDY column, which only exists on the hour and always spans exactly three hours; "series" was
    computed from the observations, with `hours` the real gap between the two readings it compared.
    """

    delta_hpa: float
    source: Literal["ptdy", "series"]
    hours: float


@dataclass(frozen=True, slots=True)
class Trend:
    """How a reading changed between an earlier observation and the newest one, in the reading's own unit."""

    delta: float
    direction: Direction
    hours: float


@dataclass(frozen=True, slots=True)
class Extremes:
    """The lowest pressure and the strongest winds over a period, each with when it happened.

    Pressure comes from the regular rows and, when given, the supplemental file, whose lowest-pressure value inside each
    interval is the true extreme the smoothed regular row hides. peak_gust is the largest GST of the regular rows and
    peak_wind the highest wind of the supplemental rows; peak_wind stays None when no supplemental data was given.
    """

    min_pressure_hpa: float | None = None
    min_pressure_time: datetime | None = None
    peak_gust_mps: float | None = None
    peak_gust_time: datetime | None = None
    peak_wind_mps: float | None = None
    peak_wind_time: datetime | None = None


@dataclass(frozen=True, slots=True)
class StationTrends:
    """Everything the UI shows about one station's behaviour, computed together."""

    station_id: str
    latest: Observation | None
    age: timedelta | None
    silent: bool
    pressure_tendency: PressureTendency | None
    wind: Trend | None
    gust: Trend | None
    extremes: Extremes


def _newest_with(
    observations: Iterable[Observation], value: Callable[[Observation], float | None]
) -> Observation | None:
    candidates = [o for o in observations if value(o) is not None]
    return max(candidates, key=lambda o: o.time, default=None)


def _reference(
    observations: Sequence[Observation],
    newest: Observation,
    value: Callable[[Observation], float | None],
    hours: float,
    tolerance: timedelta,
) -> Observation | None:
    """The observation with a value closest to `hours` before the newest one, within the tolerance."""
    target = newest.time - timedelta(hours=hours)
    candidates = [o for o in observations if value(o) is not None and abs(o.time - target) <= tolerance]
    return min(candidates, key=lambda o: abs(o.time - target), default=None)


def _pressure(observation: Observation) -> float | None:
    return observation.pressure_hpa


def pressure_tendency(observations: Iterable[Observation], *, hours: float = TENDENCY_HOURS) -> PressureTendency | None:
    """The pressure change over the last three hours, or None when it cannot be known.

    Uses PTDY when the newest observation that has a pressure also carries it; otherwise compares that pressure with the
    reading closest to `hours` earlier, accepting a gap of up to 20 minutes either way.
    """
    rows = list(observations)
    newest = _newest_with(rows, _pressure)
    if newest is None or newest.pressure_hpa is None:
        return None
    if newest.pressure_tendency_hpa is not None:
        return PressureTendency(newest.pressure_tendency_hpa, "ptdy", TENDENCY_HOURS)
    earlier = _reference(rows, newest, _pressure, hours, timedelta(minutes=_PAIR_TOLERANCE_MIN))
    if earlier is None or earlier.pressure_hpa is None:
        return None
    return PressureTendency(
        newest.pressure_hpa - earlier.pressure_hpa, "series", (newest.time - earlier.time).total_seconds() / 3600
    )


def _trend(
    observations: Iterable[Observation],
    value: Callable[[Observation], float | None],
    hours: float,
    steady_band: float,
) -> Trend | None:
    rows = list(observations)
    newest = _newest_with(rows, value)
    if newest is None:
        return None
    tolerance = timedelta(minutes=max(_PAIR_TOLERANCE_MIN, hours * 6))
    earlier = _reference(rows, newest, value, hours, tolerance)
    now_value, then_value = value(newest), value(earlier) if earlier else None
    if earlier is None or now_value is None or then_value is None:
        return None
    delta = now_value - then_value
    direction: Direction = "rising" if delta > steady_band else "falling" if delta < -steady_band else "steady"
    return Trend(delta, direction, (newest.time - earlier.time).total_seconds() / 3600)


def wind_trend(
    observations: Iterable[Observation], *, hours: float = TENDENCY_HOURS, steady_band: float = STEADY_BAND_MPS
) -> Trend | None:
    """The change in wind speed (m/s) between the newest reading and one about `hours` earlier."""
    return _trend(observations, lambda o: o.wind_speed_mps, hours, steady_band)


def gust_trend(
    observations: Iterable[Observation], *, hours: float = TENDENCY_HOURS, steady_band: float = STEADY_BAND_MPS
) -> Trend | None:
    """The change in gust speed (m/s) between the newest reading and one about `hours` earlier."""
    return _trend(observations, lambda o: o.gust_mps, hours, steady_band)


def wave_trend(
    observations: Iterable[Observation], *, hours: float = TENDENCY_HOURS, steady_band: float = STEADY_BAND_WAVE_M
) -> Trend | None:
    """The change in wave height (m) between the newest reading that has one and one about `hours` earlier."""
    return _trend(observations, lambda o: o.wave_height_m, hours, steady_band)


def observation_age(series: ObservationSeries, now: datetime) -> timedelta | None:
    """How old the newest observation is, never negative. None when the station has no observations."""
    latest = series.latest
    return None if latest is None else max(timedelta(0), now - latest.time)


def is_silent(series: ObservationSeries, now: datetime, *, silent_after: timedelta = SILENT_AFTER) -> bool:
    """True for a station that was reporting and stopped: it has observations but the newest is older than the limit.

    A station with no observations at all is "not reporting", which is a different state (a 404, or a dark buoy).
    The default of two hours is the age latest_obs.txt itself cuts off at.
    """
    age = observation_age(series, now)
    return age is not None and age > silent_after


def interval_extremes(
    observations: Iterable[Observation],
    supplemental: Iterable[SupplementalReading] = (),
    *,
    since: datetime | None = None,
    until: datetime | None = None,
) -> Extremes:
    """The lowest pressure and highest gust and wind from `since` to `until` (open ended when omitted)."""

    def inside(moment: datetime) -> bool:
        return (since is None or moment >= since) and (until is None or moment <= until)

    pressures: list[tuple[float, datetime]] = []
    gusts: list[tuple[float, datetime]] = []
    winds: list[tuple[float, datetime]] = []
    for obs in observations:
        if not inside(obs.time):
            continue
        if obs.pressure_hpa is not None:
            pressures.append((obs.pressure_hpa, obs.time))
        if obs.gust_mps is not None:
            gusts.append((obs.gust_mps, obs.time))
    for row in supplemental:
        if not inside(row.time):
            continue
        if row.min_pressure_hpa is not None:
            pressures.append((row.min_pressure_hpa, row.min_pressure_time or row.time))
        if row.peak_wind_mps is not None:
            winds.append((row.peak_wind_mps, row.peak_wind_time or row.time))
    low = min(pressures, key=lambda pair: (pair[0], pair[1]), default=None)
    gust = max(gusts, key=lambda pair: (pair[0], -pair[1].timestamp()), default=None)
    wind = max(winds, key=lambda pair: (pair[0], -pair[1].timestamp()), default=None)
    return Extremes(
        min_pressure_hpa=low[0] if low else None,
        min_pressure_time=low[1] if low else None,
        peak_gust_mps=gust[0] if gust else None,
        peak_gust_time=gust[1] if gust else None,
        peak_wind_mps=wind[0] if wind else None,
        peak_wind_time=wind[1] if wind else None,
    )


def station_trends(
    series: ObservationSeries,
    supplemental: Iterable[SupplementalReading] = (),
    *,
    now: datetime,
    window_hours: float | None = None,
    silent_after: timedelta = SILENT_AFTER,
) -> StationTrends:
    """All the trend numbers for one station. window_hours limits the extremes to that long before `now`."""
    since = None if window_hours is None else now - timedelta(hours=window_hours)
    return StationTrends(
        station_id=series.station_id,
        latest=series.latest,
        age=observation_age(series, now),
        silent=is_silent(series, now, silent_after=silent_after),
        pressure_tendency=pressure_tendency(series.observations),
        wind=wind_trend(series.observations),
        gust=gust_trend(series.observations),
        extremes=interval_extremes(series.observations, supplemental, since=since, until=now),
    )
