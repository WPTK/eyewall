"""CO-OPS datagetter products: water level, predictions, air pressure and wind.

Every value is a string in the JSON and a missing one is an empty string. Timestamps are `YYYY-MM-DD HH:MM` in GMT
because eyewall always asks for `time_zone=gmt`. eyewall asks for `units=english`, so water levels and predictions are
feet, wind knots and pressure millibars. A product a station does not offer comes back as HTTP 200 with
`{"error": {"message": "No data was found..."}}`, which parses to an empty result carrying that message; a bad datum or
an unknown station comes back as HTTP 400 and raises in the client.

Water level requires a datum: MLLW for the coasts, while the Great Lakes answer HTTP 400 to it and need IGLD.
Observation series are newest first like the NDBC ones; predictions run oldest first so the next high tide is first.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

from eyewall.models.obs import Parsed, Prediction, TidePressure, TideWind, WaterLevelReading
from eyewall.providers.base import ParseError

DATAGETTER_URL = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
APPLICATION = "eyewall"
DEFAULT_DATUM = "MLLW"

Product = Literal["water_level", "predictions", "air_pressure", "wind"]
Latest = Literal["latest", "recent", "today"]
Interval = Literal["hilo", "h"]

_STATION_ID = re.compile(r"^[0-9A-Za-z]{5,10}$")


def datagetter_params(
    product: Product,
    station: str,
    *,
    datum: str | None = None,
    date: Latest | None = None,
    begin: datetime | None = None,
    end: datetime | None = None,
    hours: int | None = None,
    interval: Interval | None = None,
) -> dict[str, str]:
    """Query parameters for one product at one station.

    Choose a window with `date` (latest reading, the recent 3 days, or today) or with `begin`, `end` and `hours`
    (any two of the three); with nothing given the latest reading is asked for. Water level and predictions always
    carry a datum. `interval` applies to predictions only: "hilo" for high and low tides, "h" hourly, none for 6-minute.
    """
    if not _STATION_ID.fullmatch(station):
        raise ValueError(f"not a CO-OPS station id: {station!r}")
    windowed = begin is not None or end is not None or hours is not None
    if date is not None and windowed:
        raise ValueError("give either date or begin/end/hours, not both")
    params = {
        "product": product,
        "station": station,
        "units": "english",
        "time_zone": "gmt",
        "format": "json",
        "application": APPLICATION,
    }
    if product in ("water_level", "predictions"):
        params["datum"] = datum or DEFAULT_DATUM
    if interval is not None and product == "predictions":
        params["interval"] = interval
    if not windowed:
        params["date"] = date or "latest"
        return params
    if begin is not None:
        params["begin_date"] = begin.astimezone(UTC).strftime("%Y%m%d %H:%M")
    if end is not None:
        params["end_date"] = end.astimezone(UTC).strftime("%Y%m%d %H:%M")
    if hours is not None:
        params["range"] = str(hours)
    return params


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _time(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).strip().replace(" ", "T")).replace(tzinfo=UTC)
    except ValueError:
        return None


def _text(value: Any) -> str | None:
    text = "" if value is None else str(value).strip()
    return text or None


def _records[T](
    text: str | bytes, key: str, build: Callable[[dict[str, Any], datetime], T], *, newest_first: bool
) -> Parsed[T]:
    try:
        payload = json.loads(text)
    except ValueError as exc:  # an HTML page or a cut-off body is not an answer: raise, so no caller stores it as one
        raise ParseError("invalid CO-OPS JSON") from exc
    if not isinstance(payload, dict):
        raise ParseError("unexpected CO-OPS payload")
    error = payload.get("error")
    if isinstance(error, dict):
        return Parsed(message=str(error.get("message") or "CO-OPS reported an error").strip())
    rows = payload.get(key)
    if rows is None:
        return Parsed(message=f"CO-OPS payload has no {key!r}")
    if not isinstance(rows, list):
        return Parsed(message=f"CO-OPS {key!r} is not a list")
    timed: list[tuple[datetime, T]] = []
    skipped = 0
    for row in rows:
        moment = _time(row.get("t")) if isinstance(row, dict) else None
        if moment is None:
            skipped += 1
            continue
        timed.append((moment, build(row, moment)))
    timed.sort(key=lambda pair: pair[0], reverse=newest_first)
    return Parsed(tuple(record for _, record in timed), skipped)


def parse_water_level(text: str | bytes) -> Parsed[WaterLevelReading]:
    """Observed water levels in feet above the requested datum, newest first, quality flags kept."""
    return _records(
        text,
        "data",
        lambda r, t: WaterLevelReading(
            t, _number(r.get("v")), _number(r.get("s")), str(r.get("f") or ""), str(r.get("q") or "")
        ),
        newest_first=True,
    )


def parse_predictions(text: str | bytes) -> Parsed[Prediction]:
    """Tide predictions in feet, soonest first. High and low tides carry kind "H" or "L"; interval data has none."""
    return _records(
        text,
        "predictions",
        lambda r, t: Prediction(t, _number(r.get("v")), _text(r.get("type"))),
        newest_first=False,
    )


def parse_air_pressure(text: str | bytes) -> Parsed[TidePressure]:
    """Air pressure in millibars, newest first."""
    return _records(
        text,
        "data",
        lambda r, t: TidePressure(t, _number(r.get("v")), str(r.get("f") or "")),
        newest_first=True,
    )


def parse_wind(text: str | bytes) -> Parsed[TideWind]:
    """Wind in knots, newest first: speed, direction in degrees and as compass text, and gust."""
    return _records(
        text,
        "data",
        lambda r, t: TideWind(
            t, _number(r.get("s")), _number(r.get("d")), _text(r.get("dr")), _number(r.get("g")), str(r.get("f") or "")
        ),
        newest_first=True,
    )
