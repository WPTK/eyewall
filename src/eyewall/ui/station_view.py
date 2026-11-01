"""The rows of the Buoys and gauges list and the pages of the Station screen, as plain data and Rich text.

Pure functions of the store and a few settings, with no Textual in them. A row is two lines: who the station is and
where it is from the storm, then what it reads and how old that is. A station that has gone quiet says so in words
with a mark, never by colour alone; one that is dark or still waiting is dimmed and never blank.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo

from rich.text import Text

from eyewall.clock import format_age
from eyewall.geo import compass_point
from eyewall.models.obs import Observation, Station, TideSeries, TideStation
from eyewall.palette import DIM, FRESHNESS_CUES, HEADING, category_color, storm_force
from eyewall.state.store import Store
from eyewall.state.tides import is_silent, latest_residual, observation_age, predicted_at
from eyewall.ui import stations as st
from eyewall.ui.glyphs import UiGlyphs
from eyewall.ui.words import station as words
from eyewall.units import MISSING, Preset, convert

SORTS = ("nearest", "strongest wind", "name")
BUOY, GAUGE = "ndbc", "coops"
KIND_WORD = {BUOY: "Buoy", GAUGE: "Gauge"}


@dataclass(frozen=True, slots=True)
class Row:
    """One station in the list. `state` is `ok`, `stale` (silent), `dark` or `waiting`."""

    kind: str
    id: str
    name: str
    distance_nm: float | None
    bearing_deg: float | None
    wind_kt: float | None
    followed: bool
    state: str
    detail: str
    age: str

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.id}"


def stale_text(g: UiGlyphs, ascii_: bool, sentence: str) -> str:
    cue = FRESHNESS_CUES["stale"]
    return f"{cue.ascii_glyph if ascii_ else cue.glyph} {cue.word.capitalize()}: {sentence}"


def _row(
    kind: str,
    entry: st.Entry[Station] | st.Entry[TideStation],
    state: str,
    detail: str,
    *,
    wind_kt: float | None = None,
    age: str = "",
) -> Row:
    return Row(
        kind=kind,
        id=entry.station.id,
        name=st.clean_name(entry.station.name),
        distance_nm=entry.distance_nm,
        bearing_deg=entry.bearing_deg,
        wind_kt=wind_kt,
        followed=entry.watchlisted,
        state=state,
        detail=detail,
        age=age,
    )


def buoy_row(
    store: Store, entry: st.Entry[Station], now: datetime, preset: Preset, g: UiGlyphs, tz: tzinfo | None, ascii_: bool
) -> Row:
    station = entry.station
    state = st.buoy_state(store, station.id, now)
    obs = st.newest_observation(store, station.id)
    if state == "ok" and obs is not None:
        age = max(timedelta(0), now - obs.time)
        detail = words.buoy_brief(
            obs,
            st.last_reading(store, station.id, obs, now, "wave_height_m"),
            store.tendency(station.id, now),
            preset,
            (g.rising, g.falling, g.steady),
        ).text
        return _row(BUOY, entry, "ok", detail, wind_kt=st.wind_kt(obs), age=f"{format_age(age.total_seconds())} ago")
    gap = words.state_sentence(state, obs, now, tz)
    sentence = gap.text if gap is not None else "No report."
    if state == "silent" and obs is not None:
        return _row(BUOY, entry, "stale", stale_text(g, ascii_, sentence))
    return _row(BUOY, entry, state, sentence)


def gauge_row(
    store: Store, entry: st.Entry[TideStation], now: datetime, preset: Preset, g: UiGlyphs, ascii_: bool
) -> Row:
    gauge = entry.station
    series = store.tide_series.get(gauge.id)
    if series is None or series.latest_level is None:
        if gauge.id in store.tide_errors:
            return _row(GAUGE, entry, "dark", "Not reporting. Could not fetch the water level for this gauge.")
        if series is not None:
            return _row(GAUGE, entry, "dark", "Not reporting. NOAA has no recent water level for this gauge.")
        return _row(GAUGE, entry, "waiting", "Waiting for the first water level.")
    age = observation_age(series, now)
    if age is not None and is_silent(series, now):
        return _row(GAUGE, entry, "stale", stale_text(g, ascii_, f"No report for {format_age(age.total_seconds())}."))
    wind = st.tide_wind(series, now)
    return _row(
        GAUGE,
        entry,
        "ok",
        words.gauge_brief(gauge, series, now, preset).text,
        wind_kt=None if wind is None else wind.speed_kt,
        age="" if age is None else f"{format_age(age.total_seconds())} ago",
    )


def near_rows(
    store: Store, storm_id: str, now: datetime, preset: Preset, g: UiGlyphs, tz: tzinfo | None, ascii_: bool
) -> list[Row]:
    """The buoys and gauges near a storm, as the store ranks them."""
    out = [buoy_row(store, e, now, preset, g, tz, ascii_) for e in st.from_nearby(store.nearby_buoys(storm_id, now))]
    out += [gauge_row(store, e, now, preset, g, ascii_) for e in st.from_nearby(store.nearby_tides(storm_id, now))]
    return out


def followed_rows(
    store: Store, now: datetime, preset: Preset, g: UiGlyphs, tz: tzinfo | None, ascii_: bool
) -> list[Row]:
    """The stations you follow, in the order you followed them (buoys, then gauges)."""
    out = [buoy_row(store, e, now, preset, g, tz, ascii_) for e in st.watchlist_buoys(store)]
    out += [gauge_row(store, e, now, preset, g, ascii_) for e in st.watchlist_gauges(store)]
    return out


def sort_rows(rows: Sequence[Row], mode: str) -> list[Row]:
    if mode == "strongest wind":
        return sorted(rows, key=lambda r: (r.wind_kt is None, -(r.wind_kt or 0.0), r.name.lower()))
    if mode == "name":
        return sorted(rows, key=lambda r: (r.name or r.id).lower())
    return sorted(rows, key=lambda r: (r.distance_nm is None, r.distance_nm or 0.0))


def where_text(row: Row, preset: Preset) -> str:
    if row.distance_nm is None or row.bearing_deg is None:
        return ""
    return f"{preset.fmt_distance(row.distance_nm)} {compass_point(row.bearing_deg)}"


def row_text(row: Row, width: int, preset: Preset) -> Text:
    """Two lines at this width: the name and where it is, then the reading and its age. Nothing wraps; a cell that does
    not fit is cut at its end with an ellipsis, the reading before the age."""
    mark = "*" if row.followed else " "
    head = Text(no_wrap=True, overflow="ellipsis")
    head.append(f"{mark} ")
    head.append(f"{KIND_WORD[row.kind]} {row.id}", style="bold")
    if row.name:
        head.append(f"  {row.name}")
    where = where_text(row, preset)
    if where:
        head.truncate(max(width - len(where) - 1, 1), overflow="ellipsis", pad=True)
        head.append(" ")
        head.append(where, style=DIM)
    body = Text(no_wrap=True, overflow="ellipsis")
    body.append("    ")
    style = DIM if row.state in ("dark", "waiting") else FRESHNESS_CUES["stale"].style() if row.state == "stale" else ""
    if row.age:
        body.append(row.age, style=DIM)
        body.append(" · ", style=DIM)
    if row.state == "ok" and row.wind_kt is not None and storm_force(row.wind_kt):
        body.append(row.detail, style=f"bold {category_color(row.wind_kt)}")
    else:
        body.append(row.detail, style=style)
    return Text("\n").join([head, body])


# ---- the station screen -------------------------------------------------------------------------------------------


def station_name(store: Store, kind: str, station_id: str) -> str:
    if kind == BUOY:
        station = store.stations.get(station_id.upper())
        return st.clean_name(station.name) if station else ""
    gauge = next((g for g in store.tide_stations if g.id.upper() == station_id.upper()), None)
    return st.clean_name(gauge.name) if gauge else ""


def readings_table(rows: Sequence[Observation], now: datetime, hours: float, preset: Preset, tz: tzinfo | None) -> Text:
    """The buoy's readings in the last `hours`, newest first, as aligned columns."""
    shown = list(reversed(st.hours_back(rows, now, hours)))
    out = Text()
    if not shown:
        out.append("No readings in this range.", style=DIM)
        return out
    columns = ("Time", "Wind", "Gust", "Pressure", "Waves", "Water")
    cells: list[tuple[str, ...]] = []
    for o in shown:
        local = o.time.astimezone(tz)
        direction = "" if o.wind_dir_deg is None else f"{compass_point(o.wind_dir_deg)} "
        wind = None if o.wind_speed_mps is None else convert(o.wind_speed_mps, "mps", "kt")
        gust = None if o.gust_mps is None else convert(o.gust_mps, "mps", "kt")
        cells.append(
            (
                f"{local:%a %I:%M %p}".replace(" 0", " ", 1),
                direction + preset.fmt_wind(wind),
                preset.fmt_wind(gust),
                preset.fmt_pressure(o.pressure_hpa, "hpa"),
                preset.fmt_length(o.wave_height_m, "m"),
                preset.fmt_temperature(o.water_temp_c, "c"),
            )
        )
    _grid(out, columns, cells)
    return out


def tide_readings_table(series: TideSeries, now: datetime, hours: float, preset: Preset, tz: tzinfo | None) -> Text:
    """The gauge's water levels in the last `hours`, newest first: observed, predicted and the difference."""
    out = Text()
    since = now - timedelta(hours=hours)
    predictions = tuple(sorted(series.predictions.items, key=lambda p: p.time))
    cells: list[tuple[str, ...]] = []
    for r in series.water_level.items:
        if r.level_ft is None or r.time < since or r.time > now:
            continue
        predicted = predicted_at(predictions, r.time)
        diff = MISSING if predicted is None else f"{r.level_ft - predicted:+.1f} ft"
        local = r.time.astimezone(tz)
        cells.append(
            (
                f"{local:%a %I:%M %p}".replace(" 0", " ", 1),
                preset.fmt_length(r.level_ft, "ft", decimals=1),
                MISSING if predicted is None else preset.fmt_length(predicted, "ft", decimals=1),
                diff,
            )
        )
    if not cells:
        out.append("No readings in this range.", style=DIM)
        return out
    _grid(out, ("Time", "Observed", "Predicted", "Difference"), cells)
    return out


def _grid(out: Text, columns: tuple[str, ...], cells: Sequence[tuple[str, ...]]) -> None:
    widths = [max(len(columns[i]), *(len(c[i]) for c in cells)) for i in range(len(columns))]

    def line(values: tuple[str, ...], style: str) -> None:
        parts = [v.ljust(widths[0]) if i == 0 else v.rjust(widths[i]) for i, v in enumerate(values)]
        out.append("  ".join(parts).rstrip() + "\n", style=style)

    line(columns, f"bold {HEADING}")
    for c in cells:
        line(c, "")


def gauge_levels(series: TideSeries | None, now: datetime, hours: float) -> list[tuple[float, float | None]]:
    """(hours before now, observed feet) oldest first."""
    if series is None:
        return []
    since = now - timedelta(hours=hours)
    return sorted(
        (-(now - r.time).total_seconds() / 3600.0, r.level_ft)
        for r in series.water_level.items
        if since <= r.time <= now
    )


def gauge_predictions(series: TideSeries | None, now: datetime, hours: float) -> list[tuple[float, float | None]]:
    if series is None:
        return []
    since = now - timedelta(hours=hours)
    return sorted(
        (-(now - p.time).total_seconds() / 3600.0, p.level_ft)
        for p in series.predictions.items
        if since <= p.time <= now
    )


def residual_ft(series: TideSeries | None) -> float | None:
    residual = None if series is None else latest_residual(series)
    return None if residual is None else residual.residual_ft


__all__ = [
    "BUOY",
    "GAUGE",
    "SORTS",
    "Row",
    "buoy_row",
    "followed_rows",
    "gauge_levels",
    "gauge_predictions",
    "gauge_row",
    "near_rows",
    "readings_table",
    "residual_ft",
    "row_text",
    "sort_rows",
    "station_name",
    "tide_readings_table",
]
