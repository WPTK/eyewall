"""Time parsing shared by the NHC parsers.

NHC writes times three ways: ISO 8601 in CurrentStorms.json, `2100 UTC MON AUG 18 2025` or `500 PM EDT Mon Aug 18 2025`
in product headers, and a bare day, hour and minute (`19/0600Z`) in forecast lines. The last has no month, so it is
resolved against a reference time. Everything returned is timezone-aware UTC.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from eyewall.clock import parse_utc

# Hours added to local time to get UTC, for the zone abbreviations NHC, CPHC and the NWS use in headers.
_TZ_OFFSET_HOURS: dict[str, int] = {
    "UTC": 0,
    "GMT": 0,
    "Z": 0,
    "AST": -4,
    "ADT": -3,
    "EST": -5,
    "EDT": -4,
    "CST": -6,
    "CDT": -5,
    "MST": -7,
    "MDT": -6,
    "PST": -8,
    "PDT": -7,
    "AKST": -9,
    "AKDT": -8,
    "HST": -10,
    "HDT": -9,
    "SST": -11,
    "CHST": 10,
}

_MONTHS = {
    name: index
    for index, name in enumerate(
        ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), start=1
    )
}

_HEADER_TIME = re.compile(
    r"(?P<hour>\d{1,2})(?P<minute>\d{2})\s*(?P<ampm>AM|PM)?\s+(?P<tz>[A-Za-z]{1,4})\s+"
    r"(?:(?P<dow>[A-Za-z]{3})\s+)?(?P<mon>[A-Za-z]{3})\s+(?P<day>\d{1,2})\s+(?P<year>\d{4})",
    re.IGNORECASE,
)


def parse_iso(text: object) -> datetime | None:
    """An ISO 8601 timestamp (a trailing Z is fine) as UTC, or None when it is empty or malformed."""
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        return parse_utc(text)
    except ValueError:
        return None


def parse_header_time(text: str) -> datetime | None:
    """A product header time such as `500 PM EDT Mon Aug 18 2025` or `2100 UTC MON AUG 18 2025`, as UTC.

    Returns None when the text holds no such time or names a zone eyewall does not know.
    """
    match = _HEADER_TIME.search(text)
    if match is None:
        return None
    offset = _TZ_OFFSET_HOURS.get(match["tz"].upper())
    month = _MONTHS.get(match["mon"].upper())
    if offset is None or month is None:
        return None
    hour, minute = int(match["hour"]), int(match["minute"])
    ampm = (match["ampm"] or "").upper()
    if ampm:
        hour = hour % 12 + (12 if ampm == "PM" else 0)
    try:
        local = datetime(int(match["year"]), month, int(match["day"]), hour % 24, minute, tzinfo=UTC)
    except ValueError:
        return None
    if hour == 24:
        local += timedelta(days=1)
    return local - timedelta(hours=offset)


def resolve_day_time(day: int, hour: int, minute: int, reference: datetime) -> datetime | None:
    """The moment with this day of month, hour and minute that lies closest to the reference time.

    Forecast lines give only `19/0600Z`; the month and year come from whichever neighbouring month puts the result
    nearest the advisory. A forecast is at most five days out, so the choice is never ambiguous.
    """
    best: datetime | None = None
    for month_offset in (-1, 0, 1):
        month_index = reference.year * 12 + (reference.month - 1) + month_offset
        year, month = divmod(month_index, 12)
        try:
            candidate = datetime(year, month + 1, day, hour, minute, tzinfo=UTC)
        except ValueError:
            continue
        if best is None or abs(candidate - reference) < abs(best - reference):
            best = candidate
    return best
