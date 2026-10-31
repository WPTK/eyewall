"""`{id}_5day.supl`: the lowest pressure and the highest wind inside each reporting interval, with their times.

A buoy reports every 10 minutes but samples far more often, so the supplemental file preserves the extremes the
regular row smooths away. PTIME and WTIME are bare `hhmm` times within the interval ending at the row's time; the row
supplies the date, and a clock time later than the row's rolls back to the previous day (an interval spanning midnight).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from eyewall.models.obs import Parsed, SupplementalReading
from eyewall.ndbc.table import Row, parse_number, parse_time, read_table


def _clock_time(row: Row, column: str, row_time: datetime) -> datetime | None:
    token = row.get(column, "")
    if len(token) != 4 or not token.isdigit():
        return None
    hour, minute = int(token[:2]), int(token[2:])
    if hour > 23 or minute > 59:
        return None
    moment = row_time.replace(hour=hour, minute=minute)
    return moment - timedelta(days=1) if moment > row_time else moment


def parse_supl(text: str) -> Parsed[SupplementalReading]:
    """Parse a .supl file by header name, newest first as published. Rows with no usable date are skipped."""
    table = read_table(text)
    readings: list[SupplementalReading] = []
    skipped = table.stray_lines
    for row in table.rows:
        moment = parse_time(row)
        if moment is None:
            skipped += 1
            continue
        readings.append(
            SupplementalReading(
                time=moment,
                min_pressure_hpa=parse_number(row, "PRES"),
                min_pressure_time=_clock_time(row, "PTIME", moment),
                peak_wind_mps=parse_number(row, "WSPD"),
                peak_wind_dir_deg=parse_number(row, "WDIR"),
                peak_wind_time=_clock_time(row, "WTIME", moment),
            )
        )
    readings.sort(key=lambda r: r.time, reverse=True)
    message = None if table.header_found else "not an NDBC supplemental table"
    return Parsed(tuple(readings), skipped, message)
