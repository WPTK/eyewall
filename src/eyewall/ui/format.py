"""What the dashboard says: the storm list rows, the side panels and the alert titles, as Rich text.

Pure functions of the store and a few settings, so they are tested without a terminal. Units stay as NOAA reported them
and are converted here, at display time, through a `units.Preset`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from rich.text import Text

from eyewall.clock import format_age
from eyewall.geo import compass_point
from eyewall.models.events import Event, EventKind, Severity
from eyewall.models.outlook import Chance, Outlook, OutlookArea, OutlookText
from eyewall.models.storm import Classification, Storm
from eyewall.models.watches import WatchWarningAlert
from eyewall.models.wind import QuadrantRadii
from eyewall.palette import (
    ACCENT,
    DIM,
    HEADING,
    NEUTRAL,
    SEVERITY_CUES,
    WATCH_WARNING_COLORS,
    category_color,
    category_for_knots,
    risk_color,
    storm_force,
)
from eyewall.state.store import Store, StormState
from eyewall.ui import stations as st
from eyewall.ui.glyphs import UiGlyphs
from eyewall.units import MISSING, Preset

BASIN_NAMES = {"AL": "Atlantic", "EP": "East Pacific", "CP": "Central Pacific"}
INVEST_LETTER = {"AL": "L", "EP": "E", "CP": "C"}
QUIET_TEXT = "No tropical cyclones"
OLD_ADVISORY_HOURS = 6.0
MAX_PANEL_ALERTS = 5
MAX_STRIP_BUOYS = 5
EVENT_TITLES: dict[EventKind, str] = {
    EventKind.NEW_STORM: "New storm",
    EventKind.NEW_PTC: "Potential cyclone",
    EventKind.NEW_INVEST: "New invest",
    EventKind.NEW_ADVISORY: "New advisory",
    EventKind.CLASSIFICATION: "Classification",
    EventKind.WATCH_WARNING_ISSUED: "Watch or warning issued",
    EventKind.WATCH_WARNING_CHANGED: "Watch or warning changed",
    EventKind.WATCH_WARNING_DISCONTINUED: "Watch or warning ended",
    EventKind.NEW_OUTLOOK: "Outlook",
    EventKind.NEW_DISCUSSION: "Discussion",
    EventKind.BUOY_THRESHOLD: "Buoy",
    EventKind.BUOY_SILENT: "Buoy silent",
}
SEVERITY_COLORS = {severity: SEVERITY_CUES[severity.value].color for severity in Severity}


# ----------------------------------------------------------------------------------------------------- small helpers


def collapse(text: str) -> str:
    """Whitespace runs to single spaces: NHC text is hard-wrapped at 69 columns."""
    return " ".join(text.split())


def class_label(storm: Storm) -> str:
    """The badge text: PTC for a potential cyclone, else TD, TS or the hurricane category from the wind."""
    if storm.classification is Classification.PTC:
        return "PTC"
    if storm.classification in (Classification.HU, Classification.TY, Classification.TS, Classification.TD):
        category = category_for_knots(storm.intensity_kt)
        if category is not None:
            return category.value
    return (storm.classification_text or storm.classification.value)[:3].upper()


def storm_color(storm: Storm) -> str:
    return category_color(storm.intensity_kt)


def movement_text(storm: Storm, preset: Preset) -> str:
    speed = storm.movement_speed_mph
    if storm.movement_dir_deg is None or speed is None:
        return "movement unknown"
    if speed < 1:
        return "nearly stationary"
    return f"{compass_point(storm.movement_dir_deg)} at {preset.fmt_wind(speed, 'mph')}"


def advisory_age(storm: Storm, now: datetime) -> tuple[str, bool]:
    """The age of the newest product as text, and whether it is old enough to flag."""
    if storm.last_update is None:
        return "no advisory", True
    seconds = (now - storm.last_update).total_seconds()
    return format_age(max(0.0, seconds)), seconds > OLD_ADVISORY_HOURS * 3600


def chance_text(chance: Chance | None) -> str:
    if chance is None or chance.percent is None:
        return "--"
    return f"{chance.percent}%"


def text_basins(text: OutlookText) -> tuple[str, ...]:
    """The basins an outlook text covers, from its `For the ...:` line."""
    region = (text.region or "").lower()
    if "atlantic" in region:
        return ("AL",)
    found: list[str] = []
    if "eastern" in region or "east pacific" in region:
        found.append("EP")
    if "central" in region:
        found.append("CP")
    return tuple(found) or ("EP",)


# ------------------------------------------------------------------------------------------------------- storm list


@dataclass(frozen=True, slots=True)
class Row:
    """One row of the storm list. `kind`: header, storm, ptc, invest or quiet; header and quiet are not selectable."""

    kind: str
    id: str
    text: Text
    basin: str = ""

    @property
    def selectable(self) -> bool:
        return self.kind in ("storm", "ptc", "invest")


def _invest_basin(area: OutlookArea, text: OutlookText, outlook: Outlook) -> str:
    basins = text_basins(text)
    if len(basins) == 1 or area.invest_id is None:
        return basins[0]
    for track in outlook.invests:
        if f"{track.basin_code}{track.number:02d}".upper() == area.invest_id.upper() and track.latest is not None:
            return "CP" if track.latest.lon < -140.0 else "EP"
    return basins[0]


def invest_label(area: OutlookArea, basin: str, index: int) -> str:
    """`Invest 94L` when the outlook names the invest, else `Area 1` (the numbered area in the outlook text)."""
    if area.invest_id:
        return f"Invest {area.invest_id[2:]}{INVEST_LETTER.get(area.invest_id[:2].upper(), '')}"
    return f"Area {area.number or index}"


def outlook_areas_by_basin(outlook: Outlook | None) -> dict[str, list[tuple[str, OutlookArea]]]:
    """Each basin's outlook areas as (row id, area) pairs, in the order the outlook lists them.

    NHC's East Pacific outlook can also describe a Central Pacific area that the CPHC outlook lists too. Texts that
    cover one basin are read first and claim their areas, so the broader text does not list them a second time.
    """
    found: dict[str, list[tuple[str, OutlookArea]]] = {}
    if outlook is None:
        return found
    claimed: set[tuple[str, str]] = set()
    for text in sorted(outlook.texts, key=lambda t: len(text_basins(t))):
        for index, area in enumerate(text.areas, start=1):
            marker = (collapse(area.title).lower(), collapse(area.description)[:80].lower())
            if marker in claimed:
                continue
            claimed.add(marker)
            basin = _invest_basin(area, text, outlook)
            row_id = f"invest:{area.invest_id or f'{basin}-{area.number or index}'}"
            found.setdefault(basin, []).append((row_id, area))
    return found


def _storm_row(state: StormState, now: datetime, preset: Preset, g: UiGlyphs) -> Row:
    storm = state.storm
    color = storm_color(storm)
    label = class_label(storm)
    head = Text(no_wrap=True, overflow="ellipsis")
    head.append(f" {label:<3}", style=f"bold {color}")
    head.append(f" {storm.name.upper()}", style="bold")
    head.append(
        f"  {preset.fmt_wind(storm.intensity_kt)}  {preset.fmt_pressure(storm.pressure_mb)}",
        style=color if storm.intensity_kt is not None else DIM,
    )
    age, old = advisory_age(storm, now)
    adv = state.advisories.adv_num or storm.adv_num
    detail = Text(no_wrap=True, overflow="ellipsis")
    detail.append(f"     {movement_text(storm, preset)} {g.sep} ", style=DIM)
    detail.append(f"adv {adv}" if adv else "no advisory", style=DIM)
    detail.append(f" {g.sep} {age}", style=ACCENT if old else DIM)
    kind = "ptc" if storm.classification is Classification.PTC else "storm"
    return Row(kind, storm.id, Text("\n").join([head, detail]), storm.basin.value if storm.basin else "")


def _invest_row(row_id: str, area: OutlookArea, basin: str, index: int) -> Row:
    head = Text(no_wrap=True, overflow="ellipsis")
    head.append(f" {invest_label(area, basin, index)}", style="bold")
    detail = Text(no_wrap=True, overflow="ellipsis")
    detail.append("     2d ", style=DIM)
    detail.append(chance_text(area.chance_48h), style=risk_color(area.chance_48h.risk if area.chance_48h else None))
    detail.append("  7d ", style=DIM)
    detail.append(chance_text(area.chance_7d), style=risk_color(area.chance_7d.risk if area.chance_7d else None))
    return Row("invest", row_id, Text("\n").join([head, detail]), basin)


def _names(codes: list[str]) -> str:
    """The basins in a line of the storm list, short enough for its narrowest width (30 columns with ': none')."""
    if codes == ["EP", "CP"]:
        return "Pacific"
    names = ", ".join(BASIN_NAMES[c] for c in codes)
    return names if len(names) <= 22 else ", ".join(codes)


def build_rows(
    store: Store, basins: tuple[str, ...], now: datetime, preset: Preset, g: UiGlyphs, *, unreachable: bool = False
) -> list[Row]:
    """The storm list: a header and the storms and invests of each basin that has any, then a dim line."""
    by_basin = outlook_areas_by_basin(store.outlook)
    rows: list[Row] = []
    empty: list[str] = []
    for code in basins:
        states = [s for s in store.storms.values() if s.storm.basin is not None and s.storm.basin.value == code]
        states.sort(key=lambda s: (s.storm.classification is Classification.PTC, -(s.storm.intensity_kt or 0)))
        invests = by_basin.get(code, [])
        if not states and not invests:
            empty.append(code)
            continue
        header = Text(f" {BASIN_NAMES[code].upper()}", style=f"bold {HEADING}", no_wrap=True)
        rows.append(Row("header", f"header:{code}", header, code))
        rows.extend(_storm_row(state, now, preset, g) for state in states)
        for index, (row_id, area) in enumerate(invests, start=1):
            rows.append(_invest_row(row_id, area, code, index))
    if empty:
        if not store.storms_loaded:
            line = "no connection" if unreachable else "loading..."
        elif len(empty) == len(basins):
            line = QUIET_TEXT
        else:
            line = f"{_names(empty)}: none"
        rows.append(Row("quiet", "quiet", Text(f" {line}", style=DIM, no_wrap=True), empty[0]))
    return rows


# ------------------------------------------------------------------------------------------------------------ panels


def _kv(text: Text, label: str, value: str, *, style: str = "") -> None:
    text.append(f"{label} ", style=DIM)
    text.append(value, style=style)


def headline_panel(store: Store, selected: str | None, basins: tuple[str, ...]) -> Text:
    """The latest headline and key messages for the selected storm; the outlook summary when nothing is selected."""
    out = Text()
    state = store.storms.get(selected or "")
    if state is not None:
        public = state.advisories.public
        out.append(f"{state.storm.name.upper()}", style=f"bold {storm_color(state.storm)}")
        adv = state.advisories.adv_num
        if adv is not None:
            out.append(f"  advisory {adv}", style=DIM)
        out.append("\n")
        if public is None:
            out.append("Waiting for the public advisory.", style=DIM)
            return out
        for headline in public.headlines:
            out.append(collapse(headline) + "\n")
        messages = public.key_messages or (
            state.advisories.discussion.key_messages if state.advisories.discussion else ()
        )
        for message in messages:
            out.append("- ", style=DIM)
            out.append(collapse(message) + "\n")
        return out
    area = _selected_area(store, selected)
    if area is not None:
        out.append(f"{invest_label(area, '', 1)}\n", style="bold")
        out.append(collapse(area.description))
        return out
    if store.outlook is None:
        out.append("Waiting for the tropical weather outlook.", style=DIM)
        return out
    for text in store.outlook.texts:
        covered = [b for b in text_basins(text) if b in basins]
        if not covered:
            continue
        out.append(f"{' / '.join(BASIN_NAMES[b] for b in covered)}\n", style=f"bold {HEADING}")
        out.append(collapse(text.summary) + "\n")
        if text.active_systems:
            out.append(collapse(text.active_systems) + "\n", style=DIM)
    return out


def _selected_area(store: Store, selected: str | None) -> OutlookArea | None:
    if not selected or not selected.startswith("invest:"):
        return None
    for areas in outlook_areas_by_basin(store.outlook).values():
        for row_id, area in areas:
            if row_id == selected:
                return area
    return None


def _cut(text: str, limit: int) -> str:
    """Text cut at a word boundary within `limit` characters, with an ellipsis where it was cut."""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def ww_panel(store: Store, selected: str | None, g: UiGlyphs, now: datetime) -> Text:
    """Watches and warnings in effect, each with a color chip, then the NWS zone alerts."""
    out = Text()
    state = store.storms.get(selected or "")
    public = state.advisories.public if state else None
    if public is not None:
        blocks = public.watches_warnings
        for area in blocks.in_effect:
            color = WATCH_WARNING_COLORS.get(area.kind, NEUTRAL) if area.kind else NEUTRAL
            out.append(f"{g.chip} ", style=color)
            out.append(f"{collapse(area.label)}\n", style=f"bold {color}")
            out.append("   " + ", ".join(collapse(a) for a in area.areas) + "\n")
        if not blocks.in_effect:
            out.append("No coastal watches or warnings in effect.\n", style=DIM)
        for change in blocks.changes:
            out.append(f"{g.sep} {collapse(change)}\n", style=DIM)
    alerts = store.active_alerts(now)
    if alerts:
        out.append("\nNWS alerts\n", style=f"bold {HEADING}")
        for alert in alerts[:MAX_PANEL_ALERTS]:
            out.append(f"{g.chip} ", style=_alert_color(alert))
            out.append(f"{alert.event}: ", style="bold")
            out.append(_cut(collapse(alert.area_desc), 90) + "\n")
        if len(alerts) > MAX_PANEL_ALERTS:
            out.append(f"+{len(alerts) - MAX_PANEL_ALERTS} more\n", style=DIM)
    return out


def _alert_color(alert: WatchWarningAlert) -> str:
    return WATCH_WARNING_COLORS.get(alert.kind, NEUTRAL) if alert.kind else NEUTRAL


def _radii_cells(radii: QuadrantRadii, preset: Preset) -> str:
    """One threshold's radii, each value named by its quadrant, so the row needs no header line above it."""
    values = (("NE", radii.ne), ("SE", radii.se), ("SW", radii.sw), ("NW", radii.nw))
    cells = [
        f"{name} {MISSING if value is None else preset.fmt_distance(value, decimals=0).split()[0]}"
        for name, value in values
    ]
    return " ".join(cells) + f" {preset.distance}"


def top_probabilities(state: StormState) -> list[tuple[int, str, int]]:
    """For each of 34, 50 and 64 kt, the place with the highest cumulative chance: (threshold, place, percent)."""
    pws = state.advisories.wind_probabilities
    if pws is None:
        return []
    best: dict[int, tuple[str, int]] = {}
    for row in pws.rows:
        peak = max((c.cumulative for c in row.cells if c is not None), default=None)
        if peak is not None and (row.threshold_kt not in best or peak > best[row.threshold_kt][1]):
            best[row.threshold_kt] = (row.location, peak)
    return [(kt, *best[kt]) for kt in sorted(best)]


def wind_panel(store: Store, selected: str | None, preset: Preset) -> Text:
    """Max wind, gusts, the radii by quadrant, and the likeliest 34, 50 and 64 knot locations."""
    out = Text()
    state = store.storms.get(selected or "")
    if state is None:
        return out
    storm = state.storm
    tcm = state.advisories.forecast
    wind = storm.intensity_kt if storm.intensity_kt is not None else tcm.max_wind_kt if tcm else None
    _kv(out, "Max wind", preset.fmt_wind(wind), style=f"bold {category_color(wind)}")
    # The feed's wind and pressure are the newest advisory; the TCM's gust and eye belong to its own. When the TCM is
    # behind, they describe an older storm than the number beside them, so they are left out.
    current = tcm is not None and (storm.adv_num is None or tcm.adv_num is None or tcm.adv_num == storm.adv_num)
    if tcm is not None and current and tcm.gust_kt is not None:
        out.append("  ")
        _kv(out, "gusts", preset.fmt_wind(tcm.gust_kt))
    out.append("\n")
    pressure = storm.pressure_mb if storm.pressure_mb is not None else tcm.pressure_mb if tcm else None
    _kv(out, "Pressure", preset.fmt_pressure(pressure))
    if tcm is not None and current and tcm.eye_diameter_nm is not None:
        out.append("  ")
        _kv(out, "eye", preset.fmt_distance(tcm.eye_diameter_nm))
    out.append("\n")
    if tcm is not None and not tcm.radii.empty:
        for kt in (34, 50, 64):
            radii = tcm.radii.for_threshold(kt)
            if radii is not None:
                out.append(f"{kt} kt".ljust(7), style=f"bold {category_color(kt)}")
                out.append(_radii_cells(radii, preset) + "\n")
    probabilities = top_probabilities(state)
    if probabilities:
        out.append("\nMost likely (5 day)\n", style=DIM)
        for kt, place, percent in probabilities:
            out.append(f"{kt} kt ".ljust(7), style=f"bold {category_color(kt)}")
            out.append(f"{percent:>3}%  {place.title()}\n")
    return out


def surge_panel(store: Store, selected: str | None) -> Text:
    """The peak surge text from the public advisory; the surge watches and warnings are in the warnings panel."""
    out = Text()
    state = store.storms.get(selected or "")
    public = state.advisories.public if state else None
    if public is None:
        return out
    for title, body in public.hazards:
        if "SURGE" in title.upper():
            out.append(f"{collapse(title).title()}\n", style=f"bold {HEADING}")
            out.append(_cut(collapse(body), 600))
            break
    return out


def buoy_strip(store: Store, selected: str | None, now: datetime, preset: Preset, g: UiGlyphs) -> Text:
    """The five nearest buoys with wind, pressure and the three hour pressure change."""
    out = Text()
    if selected not in store.storms:
        return out
    entries = store.nearby_buoys(selected, now)[:MAX_STRIP_BUOYS]
    if not entries:
        out.append("No buoys near this storm yet.", style=DIM)
        return out
    for entry in entries:
        obs = st.newest_observation(store, entry.station.id)
        out.append(entry.station.id.ljust(6), style="bold")
        out.append(f"{entry.distance_nm:>4.0f}nm {compass_point(entry.bearing_deg):<3} ", style=DIM)
        if st.buoy_state(store, entry.station.id, now) in ("silent", "dark"):
            out.append(f" {st.NOT_REPORTING}\n", style=DIM)
            continue
        wind_kt = None if obs is None or obs.wind_speed_mps is None else obs.wind_speed_mps / 0.514444
        out.append(preset.fmt_wind(wind_kt).rjust(7), style=category_color(wind_kt) if storm_force(wind_kt) else "")
        pressure = None if obs is None else obs.pressure_hpa
        out.append(" " + preset.fmt_pressure(pressure, "hpa").rjust(8))
        tendency = store.tendency(entry.station.id, now)
        out.append(" ")
        out.append_text(st.delta_text(None if tendency is None else tendency.delta_hpa, preset, g))
        out.append("\n")
    return out


# --------------------------------------------------------------------------------------------------------- status bar


def event_title(event: Event) -> str:
    return EVENT_TITLES.get(event.kind, event.kind.value)
