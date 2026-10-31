"""The shared reader for NDBC's whitespace-separated text tables.

latest_obs.txt, the realtime2 and 5day2 station files, the .supl and .spec files and the historical yearly files all
share one shape: a header line of column names starting with `#`, usually a second `#` line of units, then one row
per observation. The columns differ from file to file (PTDY sits in different places, historical files have no PTDY at
all), so every parser reads by column name and never by position.

Column names are case sensitive on purpose: `MM` is the month and `mm` the minute.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime

# Older historical files use these names for the same columns.
_ALIASES = {"WD": "WDIR", "BAR": "PRES", "YR": "YY"}

# What historical and .cwind files write instead of MM, per column. None of these can be a real measurement.
FILL_VALUES: dict[str, frozenset[float]] = {
    "WDIR": frozenset({999.0}),
    "WSPD": frozenset({99.0}),
    "GST": frozenset({99.0}),
    "WVHT": frozenset({99.0}),
    "DPD": frozenset({99.0}),
    "APD": frozenset({99.0}),
    "MWD": frozenset({999.0}),
    "PRES": frozenset({9999.0}),
    "PTDY": frozenset({99.0}),
    "ATMP": frozenset({999.0}),
    "WTMP": frozenset({999.0}),
    "DEWP": frozenset({999.0}),
    "VIS": frozenset({99.0}),
    "TIDE": frozenset({99.0}),
}

Row = dict[str, str]


@dataclass(frozen=True, slots=True)
class Table:
    """The rows of a text file keyed by column name. header_found is False for anything that is not a table."""

    columns: tuple[str, ...] = ()
    rows: tuple[Row, ...] = ()
    header_found: bool = False
    stray_lines: int = 0


def normalize_station_id(raw: str) -> str:
    """The form used in NDBC data file names: upper case, no surrounding space."""
    return raw.strip().upper()


def _is_header(tokens: list[str]) -> bool:
    return "MM" in tokens and "DD" in tokens and any(t in tokens for t in ("hh", "YY", "YYYY"))


def read_table(text: str) -> Table:
    """Split a file into rows keyed by the names in its header.

    The header is the first line that names the date columns. Later `#` lines (units) are ignored. A row shorter
    than the header leaves its trailing columns out; a longer row has its extra tokens dropped. Lines before the
    header that are not comments are counted in stray_lines, which is how an HTML error page shows up.
    """
    columns: tuple[str, ...] = ()
    rows: list[Row] = []
    stray = 0
    for line in text.lstrip("﻿").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        tokens = stripped.lstrip("#").split()
        if not columns:
            if _is_header(tokens):
                columns = tuple(_ALIASES.get(t, t) for t in tokens)
            elif not stripped.startswith("#"):
                stray += 1
            continue
        if stripped.startswith("#"):
            continue
        rows.append(dict(zip(columns, tokens, strict=False)))
    return Table(columns, tuple(rows), bool(columns), stray)


def parse_number(row: Row, column: str, *, fills: bool = True) -> float | None:
    """A float from a column, or None for MM, a blank, a fill value, junk or a missing column."""
    token = row.get(column)
    if token is None or token == "MM":
        return None
    try:
        value = float(token)
    except ValueError:
        return None
    if not math.isfinite(value):
        return None
    if fills and value in FILL_VALUES.get(column, ()):
        return None
    return value


def parse_text(row: Row, column: str) -> str | None:
    """A word from a column, or None for MM, N/A or a missing column."""
    token = row.get(column)
    if token is None or token in ("MM", "N/A", "NA"):
        return None
    return token


def parse_time(row: Row) -> datetime | None:
    """The UTC time from the date columns, or None when they are missing or not a real date.

    The year is YYYY or YY (two digits before 1970 mean 20xx), the minute defaults to 0 for the oldest files.
    """
    try:
        year = int(row.get("YYYY") or row["YY"])
        if year < 100:
            year += 1900 if year >= 70 else 2000
        minute = int(row["mm"]) if "mm" in row else 0
        return datetime(year, int(row["MM"]), int(row["DD"]), int(row["hh"]), minute, tzinfo=UTC)
    except (KeyError, ValueError):
        return None
