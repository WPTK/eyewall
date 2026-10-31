"""What the buoy and tide screens say: table rows, the latest observation, the extremes and the chart series.

Pure functions of the store and a few settings, with no Textual in them, like `eyewall.ui.format`. Winds stay in the
unit NOAA reported and are converted here through a `units.Preset`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo

from rich.text import Text

from eyewall.clock import format_age, format_when, format_zulu
from eyewall.geo import compass_point
from eyewall.models.obs import Observation, Station, SupplementalReading, TideStation
from eyewall.palette import wind_band_color
from eyewall.render.chart import ChartSeries, Tick
from eyewall.state.nearby import Located, NearbyStation
from eyewall.state.store import Store
from eyewall.state.tides import is_silent as tide_is_silent
from eyewall.state.tides import latest_residual
from eyewall.state.tides import observation_age as tide_age
from eyewall.state.trends import Extremes, interval_extremes, is_silent, observation_age
from eyewall.ui.glyphs import UiGlyphs
from eyewall.ui.theme import DIM
from eyewall.units import MISSING, Preset, convert, format_value

NOT_REPORTING = "not reporting"
WAITING = "waiting"
FALL_WARN_HPA = -1.0  # a three hour fall of this much is flagged, and of FALL_RAPID_HPA in red
FALL_RAPID_HPA = -3.0
RESIDUAL_COLORS = ((4.0, "#ff4d4d"), (2.0, "#ffa63d"), (1.0, "#ffe94a"))  # feet, largest first
NEGATIVE_RESIDUAL = "#8fd3ff"
RANGES_H = (24, 48, 72)
PRESSURE_COLOR = "#4aa3ff"
WIND_COLOR = "#3ddc84"
GUST_COLOR = "#ffa63d"
WAVE_COLOR = "#8fd3ff"
NAME_WIDTH = 20

BUOY_COLUMNS = ("ID", "Name", "Dist", "Brg", "Wind", "Gust", "Pres", "dP 3h", "Wave", "WTMP", "Age", "Closest")
TIDE_COLUMNS = ("ID", "Name", "Dist", "Brg", "Observed", "Predicted", "Residual", "Wind", "Pres", "Age", "Closest")


@dataclass(frozen=True, slots=True)
class Entry[S: Located]:
    """A station with its relation to the storm; distance and bearing are None for a watchlist-only row."""

    station: S
    distance_nm: float | None = None
    bearing_deg: float | None = None
    closest_nm: float | None = None
    eta_hours: float = 0.0
    watchlisted: bool = False

    @property
    def id(self) -> str:
        return self.station.id


def from_nearby[S: Located](entries: Sequence[NearbyStation[S]]) -> list[Entry[S]]:
    return [
        Entry(e.station, e.distance_nm, e.bearing_deg, e.closest_approach_nm, e.eta_hours, e.watchlisted)
        for e in entries
    ]


def watchlist_buoys(store: Store) -> list[Entry[Station]]:
    """The watchlisted buoys in the config's order. An id the catalog does not list still gets a row (a typo, or a
    station that left the catalog), with no name or position."""
    out: list[Entry[Station]] = []
    for station_id in store.config.watchlist.ndbc:
        station = store.stations.get(station_id.upper()) or Station(station_id.upper(), "", 0.0, 0.0)
        out.append(Entry(station, watchlisted=True))
    return out


def watchlist_gauges(store: Store) -> list[Entry[TideStation]]:
    known = {g.id.upper(): g for g in store.tide_stations}
    out: list[Entry[TideStation]] = []
    for station_id in store.config.watchlist.coops:
        gauge = known.get(station_id.upper()) or TideStation(station_id.upper(), "", 0.0, 0.0)
        out.append(Entry(gauge, watchlisted=True))
    return out


# ------------------------------------------------------------------------------------------------------------ helpers


def newest_observation(store: Store, station_id: str) -> Observation | None:
    """The newest row for a buoy: the polled series, else its row in latest_obs.txt."""
    series = store.series.get(station_id.upper())
    if series is not None and series.latest is not None:
        return series.latest
    latest = store.latest.get(station_id.upper())
    return None if latest is None else latest.observation


def buoy_state(store: Store, station_id: str, now: datetime) -> str:
    """ "ok", "silent" (it stopped), "dark" (nothing to read) or "waiting" (not asked yet)."""
    key = station_id.upper()
    series = store.series.get(key)
    if series is not None:
        if not series.reporting:
            return "dark"
        return "silent" if is_silent(series, now) else "ok"
    latest = store.latest.get(key)
    if latest is not None:
        return "silent" if now - latest.observation.time > timedelta(hours=2) else "ok"
    station = store.stations.get(key)
    if station is not None and (station.met is False or store.latest):
        return "dark"  # latest_obs is read and does not list it: no report in the last hours
    return "waiting"


def wind_kt(obs: Observation | None) -> float | None:
    return None if obs is None or obs.wind_speed_mps is None else convert(obs.wind_speed_mps, "mps", "kt")


def gust_kt(obs: Observation | None) -> float | None:
    return None if obs is None or obs.gust_mps is None else convert(obs.gust_mps, "mps", "kt")


def banded(text: str, kt: float | None) -> Text:
    color = wind_band_color(kt)
    return Text(text, style=f"bold {color}" if color else "")


def delta_text(delta_hpa: float | None, preset: Preset, g: UiGlyphs) -> Text:
    """A three hour pressure change with its arrow, orange when falling by a hectopascal or more, red from three."""
    if delta_hpa is None:
        return Text(MISSING, style=DIM)
    arrow = g.falling if delta_hpa < -0.05 else g.rising if delta_hpa > 0.05 else g.steady
    value = convert(abs(delta_hpa), "hpa", preset.pressure)
    number = format_value(value, preset.pressure, decimals=2 if preset.pressure == "inhg" else 1, label=False)
    color = "bold #ff4d4d" if delta_hpa <= FALL_RAPID_HPA else "bold #ffa63d" if delta_hpa <= FALL_WARN_HPA else ""
    return Text(f"{arrow}{number}", style=color)


def closest_text(entry: Entry[Station] | Entry[TideStation], preset: Preset) -> str:
    if entry.closest_nm is None:
        return MISSING
    distance = preset.fmt_distance(entry.closest_nm)
    if entry.distance_nm is not None and entry.eta_hours < 0.5:
        return f"{distance} now"
    return f"{distance} {entry.eta_hours:.0f}h"


def _position(entry: Entry[Station] | Entry[TideStation], preset: Preset) -> tuple[str, str]:
    if entry.distance_nm is None or entry.bearing_deg is None:
        return MISSING, MISSING
    return preset.fmt_distance(entry.distance_nm), compass_point(entry.bearing_deg)


def short_name(name: str, width: int = NAME_WIDTH) -> str:
    name = " ".join(name.split())
    return name if len(name) <= width else name[: width - 1] + "…"


def _signed(value: float, unit: str, decimals: int) -> str:
    if round(value, decimals) == 0:
        value = 0.0  # a residual of -0.02 ft reads +0.0, never -0.0
    text = format_value(value, unit, decimals=decimals)
    return text if text.startswith("-") else f"+{text}"


# ------------------------------------------------------------------------------------------------------ buoy table


def buoy_row(store: Store, entry: Entry[Station], now: datetime, preset: Preset, g: UiGlyphs) -> tuple[Text, ...]:
    """One Buoys tab row. A station that is silent or dark is dimmed and says "not reporting" in the age column."""
    station = entry.station
    state = buoy_state(store, station.id, now)
    distance, bearing = _position(entry, preset)
    name = short_name(station.name) or MISSING
    pin = "*" if entry.watchlisted else " "
    ident = Text(f"{pin}{station.id}", style="bold")
    if state in ("silent", "dark"):
        dim = [name, distance, bearing, *[MISSING] * 6, NOT_REPORTING, closest_text(entry, preset)]
        return (Text(ident.plain, style=f"bold {DIM}"), *[Text(c, style=DIM) for c in dim])
    obs = newest_observation(store, station.id)
    if state == "waiting" or obs is None:
        cells = [ident, Text(name), Text(distance), Text(bearing)] + [Text(MISSING, style=DIM)] * 6
        return (*cells, Text(WAITING, style=DIM), Text(closest_text(entry, preset)))
    series = store.series.get(station.id.upper())
    if series is not None and series.latest is not None:
        age = observation_age(series, now) or timedelta(0)
    else:
        age = max(timedelta(0), now - obs.time)  # latest_obs only; a clock a little behind must not give a negative age
    tendency = store.tendency(station.id, now)
    wind, gust = wind_kt(obs), gust_kt(obs)
    return (
        ident,
        Text(name),
        Text(distance),
        Text(bearing),
        banded(preset.fmt_wind(wind), wind),
        banded(preset.fmt_wind(gust), gust),
        Text(preset.fmt_pressure(obs.pressure_hpa, "hpa")),
        delta_text(None if tendency is None else tendency.delta_hpa, preset, g),
        Text(preset.fmt_length(obs.wave_height_m, "m")),
        Text(preset.fmt_temperature(obs.water_temp_c, "c")),
        Text(format_age(age.total_seconds())),
        Text(closest_text(entry, preset)),
    )


def buoy_rows(
    store: Store, entries: Sequence[Entry[Station]], now: datetime, preset: Preset, g: UiGlyphs
) -> list[tuple[str, tuple[Text, ...]]]:
    return [(e.id, buoy_row(store, e, now, preset, g)) for e in entries]


# ------------------------------------------------------------------------------------------------------ tide table


def residual_color(residual_ft: float) -> str:
    for floor, color in RESIDUAL_COLORS:
        if residual_ft >= floor:
            return f"bold {color}"
    return NEGATIVE_RESIDUAL if residual_ft <= -1.0 else ""


def tide_row(store: Store, entry: Entry[TideStation], now: datetime, preset: Preset) -> tuple[Text, ...]:
    gauge = entry.station
    series = store.tide_series.get(gauge.id)
    distance, bearing = _position(entry, preset)
    ident = Text(f"{'*' if entry.watchlisted else ' '}{gauge.id}", style="bold")
    name = short_name(gauge.name) or MISSING
    if series is None or series.latest_level is None or tide_is_silent(series, now):
        failed = gauge.id in store.tide_errors or (series is not None and series.latest_level is None)
        note = NOT_REPORTING if failed or series is not None else WAITING
        dim = [name, distance, bearing, *[MISSING] * 5, note, closest_text(entry, preset)]
        return (Text(ident.plain, style=f"bold {DIM}"), *[Text(c, style=DIM) for c in dim])
    latest = series.latest_level
    assert latest is not None  # checked above
    residual = latest_residual(series)
    decimals = 1 if preset.length == "ft" else 2
    wind = next((w for w in series.wind.items if w.speed_kt is not None), None)
    pressure = next((p for p in series.pressure.items if p.pressure_mb is not None), None)
    wind_text = MISSING if wind is None else preset.fmt_wind(wind.speed_kt)
    if wind is not None and wind.direction_text:
        wind_text = f"{wind.direction_text} {wind_text}"
    gauge_age = tide_age(series, now)
    return (
        ident,
        Text(name),
        Text(distance),
        Text(bearing),
        Text(preset.fmt_length(latest.level_ft, "ft", decimals=decimals)),
        Text(MISSING if residual is None else preset.fmt_length(residual.predicted_ft, "ft", decimals=decimals)),
        Text(MISSING, style=DIM)
        if residual is None
        else Text(
            _signed(convert(residual.residual_ft, "ft", preset.length), preset.length, decimals),
            style=residual_color(residual.residual_ft),
        ),
        Text(wind_text, style=_wind_style(wind.speed_kt if wind else None)),
        Text(preset.fmt_pressure(None if pressure is None else pressure.pressure_mb, "mb")),
        Text(MISSING if gauge_age is None else format_age(gauge_age.total_seconds())),
        Text(closest_text(entry, preset)),
    )


def _wind_style(kt: float | None) -> str:
    color = wind_band_color(kt)
    return f"bold {color}" if color else ""


def tide_rows(
    store: Store, entries: Sequence[Entry[TideStation]], now: datetime, preset: Preset
) -> list[tuple[str, tuple[Text, ...]]]:
    return [(e.id, tide_row(store, e, now, preset)) for e in entries]


# ------------------------------------------------------------------------------------------------------ buoy detail


def hours_back(observations: Sequence[Observation], now: datetime, hours: float) -> list[Observation]:
    """The rows inside the last `hours`, oldest first."""
    since = now - timedelta(hours=hours)
    return sorted((o for o in observations if since <= o.time <= now), key=lambda o: o.time)


def _x(obs: Observation, now: datetime) -> float:
    return -(now - obs.time).total_seconds() / 3600.0


def chart_series(
    observations: Sequence[Observation], now: datetime, hours: float, preset: Preset
) -> dict[str, list[ChartSeries]]:
    """The three charts' lines, x in hours before now: pressure, wind with gust, and wave height, in display units."""
    rows = hours_back(observations, now, hours)

    def line(name: str, color: str, value: object) -> ChartSeries:
        return ChartSeries(name, tuple((_x(o, now), value(o)) for o in rows), color)  # type: ignore[operator]

    def pressure(o: Observation) -> float | None:
        return None if o.pressure_hpa is None else convert(o.pressure_hpa, "hpa", preset.pressure)

    def wind(o: Observation) -> float | None:
        return None if o.wind_speed_mps is None else convert(o.wind_speed_mps, "mps", preset.wind)

    def gust(o: Observation) -> float | None:
        return None if o.gust_mps is None else convert(o.gust_mps, "mps", preset.wind)

    def wave(o: Observation) -> float | None:
        return None if o.wave_height_m is None else convert(o.wave_height_m, "m", preset.length)

    return {
        "pressure": [line("pressure", PRESSURE_COLOR, pressure)],
        "wind": [line("wind", WIND_COLOR, wind), line("gust", GUST_COLOR, gust)],
        "wave": [line("wave", WAVE_COLOR, wave)],
    }


def has_points(series: Sequence[ChartSeries]) -> bool:
    return any(y is not None for s in series for _, y in s.points)


def time_ticks(hours: float) -> list[Tick]:
    """-24h ... now, four intervals across the range."""
    step = hours / 4
    ticks = [Tick(-step * k, f"-{step * k:g}h") for k in range(4, 0, -1)]
    return [*ticks, Tick(0.0, "now")]


def extremes_for(
    observations: Sequence[Observation], supplemental: Sequence[SupplementalReading], now: datetime, hours: float
) -> Extremes:
    return interval_extremes(observations, supplemental, since=now - timedelta(hours=hours), until=now)


def _kv(out: Text, label: str, value: str, *, style: str = "") -> None:
    out.append(f"{label:<14}", style=DIM)
    out.append(value + "\n", style=style)


def latest_observation_text(
    obs: Observation | None, store: Store, station_id: str, now: datetime, preset: Preset, g: UiGlyphs
) -> Text:
    out = Text()
    if obs is None:
        out.append(f"{NOT_REPORTING.capitalize()}: NDBC has no recent observation for this station.\n", style=DIM)
        return out
    age = max(timedelta(0), now - obs.time)
    _kv(out, "Observed", f"{format_zulu(obs.time)}  ({format_age(age.total_seconds())} ago)")
    wind, gust = wind_kt(obs), gust_kt(obs)
    direction = "" if obs.wind_dir_deg is None else f"{compass_point(obs.wind_dir_deg)} "
    _kv(out, "Wind", direction + preset.fmt_wind(wind), style=_wind_style(wind))
    _kv(out, "Gust", preset.fmt_wind(gust), style=_wind_style(gust))
    _kv(out, "Pressure", preset.fmt_pressure(obs.pressure_hpa, "hpa"))
    tendency = store.tendency(station_id, now)
    change = delta_text(None if tendency is None else tendency.delta_hpa, preset, g)
    out.append(f"{'Change 3h':<12}", style=DIM)
    out.append_text(change)
    out.append("\n")
    _kv(out, "Wave height", preset.fmt_length(obs.wave_height_m, "m"))
    if obs.wave_height_m is not None or obs.dominant_period_s is not None:
        period = MISSING if obs.dominant_period_s is None else f"{obs.dominant_period_s:.0f} s"
        _kv(out, "Wave period", period)
    _kv(out, "Water temp", preset.fmt_temperature(obs.water_temp_c, "c"))
    _kv(out, "Air temp", preset.fmt_temperature(obs.air_temp_c, "c"))
    _kv(out, "Dew point", preset.fmt_temperature(obs.dewpoint_c, "c"))
    visibility = MISSING if obs.visibility_nmi is None else preset.fmt_distance(obs.visibility_nmi)
    _kv(out, "Visibility", visibility)
    return out


def extremes_text(ext: Extremes, hours: float, preset: Preset, tz: tzinfo | None, *, supl_note: str | None) -> Text:
    out = Text()
    out.append(f"Last {hours:g} hours\n", style="bold #8fd3ff")

    def when(moment: datetime | None) -> str:
        if moment is None:
            return ""
        return f"  {format_when(moment, tz)}"

    _kv(out, "Min pressure", preset.fmt_pressure(ext.min_pressure_hpa, "hpa") + when(ext.min_pressure_time))
    gust = None if ext.peak_gust_mps is None else convert(ext.peak_gust_mps, "mps", "kt")
    _kv(out, "Peak gust", preset.fmt_wind(gust) + when(ext.peak_gust_time), style=_wind_style(gust))
    peak = None if ext.peak_wind_mps is None else convert(ext.peak_wind_mps, "mps", "kt")
    _kv(out, "Peak wind", preset.fmt_wind(peak) + when(ext.peak_wind_time), style=_wind_style(peak))
    if supl_note:
        out.append(supl_note + "\n", style=DIM)
    return out


# ----------------------------------------------------------------------------------------------------------- search


@dataclass(frozen=True, slots=True)
class Hit:
    """A station found by the search: kind is "ndbc" (buoy and C-MAN) or "coops" (tide gauge)."""

    kind: str
    id: str
    name: str
    detail: str


KIND_LABELS = {"ndbc": "buoy", "coops": "tide"}
MAX_HITS = 40


def search_stations(store: Store, query: str, limit: int = MAX_HITS) -> list[Hit]:
    """Stations whose id or name contains every word of the query, best match first.

    Ranking: an exact id, then ids that start with the query, then ids that contain it, then name matches, each in
    catalog order within its rank (buoys before gauges at the same rank). An empty query matches nothing.
    """
    words = query.lower().split()
    if not words:
        return []
    ranked: list[tuple[int, int, Hit]] = []
    pool: list[tuple[str, str, str, str]] = [
        ("ndbc", s.id, s.name, f"{s.type}{' ' + s.owner if s.owner else ''}".strip()) for s in store.stations.values()
    ]
    pool += [("coops", g.id, g.name, g.state) for g in store.tide_stations]
    for order, (kind, station_id, name, detail) in enumerate(pool):
        ident, text = station_id.lower(), f"{station_id} {name}".lower()
        if not all(word in text for word in words):
            continue
        whole = " ".join(words)
        rank = 0 if ident == whole else 1 if ident.startswith(whole) else 2 if whole in ident else 3
        ranked.append((rank, order, Hit(kind, station_id, name, detail)))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return [hit for _, _, hit in ranked[:limit]]
