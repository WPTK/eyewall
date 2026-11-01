"""Small shared wording helpers: a storm's badge, colour, movement and advisory age, the basins an outlook text covers
and the alert-log titles.

Pure functions, so they are tested without a terminal. Units stay as NOAA reported them
and are converted here, at display time, through a `units.Preset`.
"""

from __future__ import annotations

from datetime import datetime

from eyewall.clock import format_age
from eyewall.geo import compass_point
from eyewall.models.events import Event, EventKind, Severity
from eyewall.models.outlook import OutlookText
from eyewall.models.storm import Classification, Storm
from eyewall.palette import (
    SEVERITY_CUES,
    category_color,
    category_for_knots,
)
from eyewall.textclean import printable
from eyewall.units import Preset

BASIN_NAMES = {"AL": "Atlantic", "EP": "East Pacific", "CP": "Central Pacific"}
OLD_ADVISORY_HOURS = 6.0
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
    return " ".join(printable(text).split())


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


def event_title(event: Event) -> str:
    return EVENT_TITLES.get(event.kind, event.kind.value)
