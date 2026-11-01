"""The storm detail tabs: what each one says, as Rich text or table rows.

The text products are shown from their parsed form (the models keep sections, not the raw bulletin), so the public
advisory is laid out from its headline, summary, watches and warnings, discussion, hazards and key messages.
"""

from __future__ import annotations

from datetime import datetime, tzinfo

from rich.console import Group
from rich.table import Table as RichTable
from rich.text import Text

from eyewall.clock import format_when, format_zulu
from eyewall.models.forecast import ForecastAdvisory, ForecastFix
from eyewall.models.wind import QuadrantRadii
from eyewall.palette import (
    DIM,
    HEADING,
    category_color,
    category_for_knots,
)
from eyewall.state.events import current_adv
from eyewall.state.store import StormState
from eyewall.ui.format import advisory_age, collapse, movement_text
from eyewall.ui.glyphs import UiGlyphs
from eyewall.units import MISSING, Preset

Table = tuple[tuple[str, ...], list[tuple[str, ...]]]
TCM_OUTLOOK_NOTE = "96 and 120 hour positions are the extended outlook, not a forecast."


def fmt_lat(lat: float | None) -> str:
    return MISSING if lat is None else f"{abs(lat):.1f}{'N' if lat >= 0 else 'S'}"


def fmt_lon(lon: float | None) -> str:
    return MISSING if lon is None else f"{abs(lon):.1f}{'E' if lon >= 0 else 'W'}"


def fmt_local(moment: datetime | None, tz: tzinfo | None) -> str:
    if moment is None:
        return MISSING
    local = moment.astimezone(tz)
    return f"{local:%a %I:%M %p} {local.tzname() or ''}".strip()


def fmt_radii(radii: QuadrantRadii | None) -> str:
    if radii is None:
        return MISSING
    return "/".join(MISSING if v is None else str(v) for v in (radii.ne, radii.se, radii.sw, radii.nw))


def _line(table: RichTable, label: str, value: str, *, style: str = "") -> None:
    table.add_row(Text(label, style=DIM), Text(value, style=style))


def summary(state: StormState, now: datetime, preset: Preset, tz: tzinfo | None) -> Group:
    """Label and value columns: a long value (the next advisory times) wraps under itself, not under its label."""
    storm = state.storm
    out = RichTable.grid(padding=(0, 2))
    out.add_column(no_wrap=True)
    out.add_column(ratio=1)
    headlines = Text()
    adv = current_adv(storm)
    age, _ = advisory_age(storm, now)
    _line(out, "Advisory", f"{adv or MISSING}  ({age})")
    _line(out, "Updated", format_when(storm.last_update, tz, day=True) if storm.last_update else MISSING)
    _line(out, "Position", f"{fmt_lat(storm.lat)} {fmt_lon(storm.lon)}")
    _line(out, "Max wind", preset.fmt_wind(storm.intensity_kt), style=f"bold {category_color(storm.intensity_kt)}")
    _line(out, "Pressure", preset.fmt_pressure(storm.pressure_mb))
    _line(out, "Movement", movement_text(storm, preset))
    tcm = state.advisories.forecast
    if tcm is not None:
        if tcm.gust_kt is not None:
            _line(out, "Gusts", preset.fmt_wind(tcm.gust_kt))
        if tcm.eye_diameter_nm is not None:
            _line(out, "Eye diameter", preset.fmt_distance(tcm.eye_diameter_nm))
        if tcm.position_accuracy_nm is not None:
            _line(out, "Position +/-", preset.fmt_distance(tcm.position_accuracy_nm))
    public = state.advisories.public
    if public is not None:
        if public.next_advisory:
            _line(out, "Next advisory", collapse(public.next_advisory))
        if public.forecaster:
            _line(out, "Forecaster", public.forecaster)
        if public.headlines:
            headlines.append("\n")
            for headline in public.headlines:
                headlines.append(collapse(headline) + "\n", style="bold")
    return Group(out, headlines)


def _fix_row(fix: ForecastFix, preset: Preset, tz: tzinfo | None) -> tuple[str, ...]:
    wind = fix.max_wind_kt
    category = category_for_knots(wind)
    label = fix.status or (category.value if category else MISSING)
    if fix.dissipated:
        return (
            f"{fix.tau}h",
            format_zulu(fix.valid, day=True),
            fmt_local(fix.valid, tz),
            "dissipated",
            "",
            "",
        )
    return (
        f"{fix.tau}h" + ("*" if fix.outlook else ""),
        format_zulu(fix.valid, day=True),
        fmt_local(fix.valid, tz),
        fmt_lat(fix.lat),
        fmt_lon(fix.lon),
        preset.fmt_wind(wind),
        label,
    )


FORECAST_COLUMNS = (
    "TAU",
    "Valid (Z)",
    "Local",
    "Lat",
    "Lon",
    "Wind",
    "Cat",
)


def forecast_table(state: StormState, preset: Preset, tz: tzinfo | None) -> Table:
    """The forecast advisory's positions, with the current position first. Gusts and radii are in the advisory text."""
    tcm = state.advisories.forecast
    rows: list[tuple[str, ...]] = []
    if tcm is not None:
        now_fix = ForecastFix(0, tcm.synoptic, tcm.lat, tcm.lon, tcm.max_wind_kt, tcm.gust_kt, tcm.radii)
        rows.append(_fix_row(now_fix, preset, tz))
        rows.extend(_fix_row(fix, preset, tz) for fix in tcm.fixes)
    elif state.forecast_gis is not None:
        for p in state.forecast_gis.points:
            category = category_for_knots(p.max_wind_kt)
            rows.append(
                (
                    f"{p.tau}h",
                    format_zulu(p.valid, day=True) if p.valid else MISSING,
                    fmt_local(p.valid, tz),
                    fmt_lat(p.lat),
                    fmt_lon(p.lon),
                    preset.fmt_wind(p.max_wind_kt),
                    category.value if category else MISSING,
                )
            )
    return FORECAST_COLUMNS, rows


def forecast_note(state: StormState) -> str:
    tcm = state.advisories.forecast
    if tcm is None:
        return "No forecast advisory yet."
    return TCM_OUTLOOK_NOTE if tcm.outlook_fixes else ""


def public_advisory(state: StormState, g: UiGlyphs) -> Text:
    """The public advisory (TCP), laid out from its sections."""
    public = state.advisories.public
    out = Text()
    if public is None:
        out.append("The public advisory has not been fetched yet.", style=DIM)
        return out
    out.append(
        f"{public.kind or ''} {public.name or ''}  Advisory {public.adv_num or MISSING}\n".strip() + "\n", style="bold"
    )
    if public.issued_text:
        out.append(collapse(public.issued_text) + "\n", style=DIM)
    for headline in public.headlines:
        out.append("\n" + collapse(headline) + "\n", style="bold")
    summary_ = public.summary
    if summary_.location_text:
        out.append("\nSummary of information\n", style=f"bold {HEADING}")
        out.append(collapse(summary_.location_text) + "\n")
        for about in summary_.about:
            out.append(f"{g.sep} {collapse(about)}\n", style=DIM)
        out.append(f"Max sustained winds {summary_.max_wind_mph} mph. " if summary_.max_wind_mph else "")
        out.append(f"Present movement {collapse(summary_.movement_text)}. " if summary_.movement_text else "")
        out.append(f"Pressure {summary_.pressure_mb} mb.\n" if summary_.pressure_mb else "\n")
    if public.watches_warnings.text:
        out.append("\nWatches and warnings\n", style=f"bold {HEADING}")
        out.append(public.watches_warnings.text.strip() + "\n")
    for title, body in public.hazards:
        out.append(f"\n{collapse(title).title()}\n", style=f"bold {HEADING}")
        out.append(collapse(body) + "\n")
    if public.discussion:
        out.append("\nDiscussion and outlook\n", style=f"bold {HEADING}")
        out.append(collapse(public.discussion) + "\n")
    if public.key_messages:
        out.append("\nKey messages\n", style=f"bold {HEADING}")
        for message in public.key_messages:
            out.append(f"{g.sep} {collapse(message)}\n")
    if public.next_advisory:
        out.append("\nNext advisory: " + collapse(public.next_advisory) + "\n", style=DIM)
    return out


def _tcm_header(tcm: ForecastAdvisory) -> str:
    return f"{tcm.kind} {tcm.name or ''}  Forecast/Advisory {tcm.adv_num or MISSING}"


def forecast_advisory(state: StormState, preset: Preset) -> Text:
    """The forecast advisory (TCM), laid out from its fields."""
    tcm = state.advisories.forecast
    out = Text()
    if tcm is None:
        out.append("The forecast advisory has not been fetched yet.", style=DIM)
        return out
    out.append(_tcm_header(tcm) + "\n", style="bold")
    out.append(f"Issued {format_zulu(tcm.issued, day=True)}  synoptic {format_zulu(tcm.synoptic)}\n", style=DIM)
    out.append(f"\nCenter {fmt_lat(tcm.lat)} {fmt_lon(tcm.lon)}")
    if tcm.position_accuracy_nm is not None:
        out.append(f" (+/- {tcm.position_accuracy_nm} nm)")
    out.append("\n")
    if tcm.movement_text:
        out.append(f"Present movement {collapse(tcm.movement_text)}\n")
    if tcm.pressure_mb is not None:
        out.append(f"Minimum central pressure {tcm.pressure_mb} mb\n")
    out.append(f"Max sustained wind {preset.fmt_wind(tcm.max_wind_kt)}, gusts {preset.fmt_wind(tcm.gust_kt)}\n")
    for kt in (64, 50, 34):
        radii = tcm.radii.for_threshold(kt)
        if radii is not None:
            out.append(f"{kt} kt winds extend (NE SE SW NW, nm): {fmt_radii(radii)}\n")
    if tcm.seas is not None:
        out.append(f"Seas {tcm.seas.height} {tcm.seas.unit.lower()} or more (nm): {fmt_radii(tcm.seas.radii)}\n")
    out.append("\nForecast\n", style=f"bold {HEADING}")
    for fix in tcm.fixes:
        row = _fix_row(fix, preset, None)
        out.append(f"{row[0]:>5} {row[1]:<14}")
        out.append(f" {row[3]} {row[4]}  {row[5]}\n" if not fix.dissipated else " dissipated\n")
    if tcm.is_final:
        out.append("\nThis is the last advisory on this system.\n", style="bold")
    return out


def discussion(state: StormState, g: UiGlyphs) -> Text:
    tcd = state.advisories.discussion
    out = Text()
    if tcd is None:
        out.append("The forecast discussion has not been fetched yet.", style=DIM)
        return out
    out.append(f"{tcd.kind or ''} {tcd.name or ''}  Discussion {tcd.adv_num or MISSING}\n".strip() + "\n", style="bold")
    if tcd.issued_text:
        out.append(collapse(tcd.issued_text) + "\n", style=DIM)
    for paragraph in tcd.paragraphs:
        out.append("\n" + collapse(paragraph) + "\n")
    if tcd.key_messages:
        out.append("\nKey messages\n", style=f"bold {HEADING}")
        for message in tcd.key_messages:
            out.append(f"{g.sep} {collapse(message)}\n")
    if tcd.forecaster:
        out.append(f"\nForecaster {tcd.forecaster}\n", style=DIM)
    return out


def wind_probabilities(state: StormState) -> Table:
    """The PWS table: one row per place and threshold, a column per time period (cumulative percent)."""
    pws = state.advisories.wind_probabilities
    if pws is None:
        return ("Location", "Kt"), []
    columns = ("Location", "Kt", *(f"{h}h" for h in pws.forecast_hours))
    rows = []
    for row in pws.rows:
        cells = tuple(MISSING if c is None else ("<1" if c.cumulative == 0 else str(c.cumulative)) for c in row.cells)
        rows.append((row.location, str(row.threshold_kt), *cells))
    return columns, rows


def probabilities_note(state: StormState) -> str:
    if state.advisories.wind_probabilities is None:
        return "No wind speed probabilities yet."
    return "Cumulative chance (percent) of winds of at least 34, 50 and 64 kt by hour; <1 is under one percent."


HISTORY_COLUMNS = ("Time (Z)", "Lat", "Lon", "Wind", "Pressure", "Type", "Cat")


def history_table(state: StormState, preset: Preset) -> Table:
    """The best track, newest first."""
    rows: list[tuple[str, ...]] = []
    if state.track is not None:
        for fix in reversed(state.track.fixes):
            category = category_for_knots(fix.vmax_kt)
            rows.append(
                (
                    f"{fix.time:%b %d %H:%M}",
                    fmt_lat(fix.lat),
                    fmt_lon(fix.lon),
                    preset.fmt_wind(fix.vmax_kt),
                    preset.fmt_pressure(fix.mslp_mb),
                    fix.type or MISSING,
                    category.value if category else MISSING,
                )
            )
    return HISTORY_COLUMNS, rows
