"""Historical standard meteorological files, read for replay recording only.

Two kinds, both `.txt.gz` and both with the same columns as the current files except that PTDY is gone and missing data
is a fill value (99.0, 999, 9999.0) instead of MM, which `eyewall.ndbc.table` already knows:

- `data/historical/stdmet/{id}h{yyyy}.txt.gz`: a whole past year, id in lower case, oldest row first. A buoy's file can
  stop early: 41010's 2025 file ends on 31 July, so it holds nothing from Hurricane Erin in August.
- `data/stdmet/{Mon}/{id}{M}{yyyy}.txt.gz`: a finished month of the current year, the month number without a leading
  zero (seen for July and August 2026, a 404 for January). The most recently finished month is a plain `{id}.txt` with
  no year in the name, and a month still under way has no file yet.
"""

from __future__ import annotations

import gzip
import io
from datetime import datetime

from eyewall.models.obs import Observation, ObservationSeries
from eyewall.ndbc.stdmet import parse_stdmet

MAX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024  # a year of 10-minute rows is about 5 MB
_GZIP_MAGIC = b"\x1f\x8b"


def decompress(data: bytes) -> str:
    """The text of a historical file, gunzipping it when it is gzip.

    Raises ValueError for a corrupt or truncated gzip stream and for anything absurdly large.
    """
    if data[:2] == _GZIP_MAGIC:
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as handle:
                data = handle.read(MAX_UNCOMPRESSED_BYTES + 1)
        except (OSError, EOFError) as exc:
            raise ValueError(f"historical file is not valid gzip ({exc})") from exc
        if len(data) > MAX_UNCOMPRESSED_BYTES:
            raise ValueError("historical file is larger than expected")
    return data.decode("utf-8", errors="replace")


def parse_historical(data: bytes, station_id: str) -> ObservationSeries:
    """Parse a yearly or monthly file, gzipped or not, into a series sorted newest first."""
    try:
        text = decompress(data)
    except ValueError as exc:
        return ObservationSeries(station_id.upper(), message=str(exc))
    return parse_stdmet(text, station_id)


def select_period(series: ObservationSeries, start: datetime, end: datetime) -> ObservationSeries:
    """The observations from start to end inclusive (both timezone-aware), as a series of the same station."""
    kept: tuple[Observation, ...] = tuple(o for o in series.observations if start <= o.time <= end)
    return ObservationSeries(series.station_id, kept, series.skipped)
