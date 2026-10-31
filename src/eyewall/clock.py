"""Clocks and time formatting.

Everything that depends on "now" (freshness, advisory age, alert expiry, replay) asks a Clock instead of the system,
so tests and the replay mode can control time. All datetimes in eyewall are timezone-aware UTC.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """The current time, timezone-aware UTC."""
        ...

    def monotonic(self) -> float:
        """Seconds from an arbitrary start that never go backwards, for measuring intervals."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()


def ensure_utc(moment: datetime) -> datetime:
    """The moment converted to UTC. Naive datetimes are rejected because their meaning is a guess."""
    if moment.tzinfo is None:
        raise ValueError("naive datetime; eyewall uses timezone-aware UTC")
    return moment.astimezone(UTC)


def parse_utc(text: str) -> datetime:
    """Parse an ISO 8601 timestamp such as 2026-09-25T06:00:00.000Z. A timestamp with no zone is taken as UTC."""
    moment = datetime.fromisoformat(text.strip())
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


class VirtualClock:
    """A clock that only moves when told to. Drives replay and deterministic tests.

    advance() moves both readings forward. set() jumps now() anywhere, including backwards (replay stepping to an
    earlier advisory), but monotonic() only ever grows.
    """

    def __init__(self, start: datetime) -> None:
        self._now = ensure_utc(start)
        self._monotonic = 0.0

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._monotonic

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("a clock cannot advance by a negative amount")
        self._now += timedelta(seconds=seconds)
        self._monotonic += seconds

    def set(self, moment: datetime) -> None:
        self._now = ensure_utc(moment)


def format_age(seconds: float | None) -> str:
    """Format as 12s, 3m05s or 2h07m. A missing age is shown as --."""
    if seconds is None:
        return "--"
    s = max(0, int(seconds))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m{s % 60:02d}s"
    return f"{s // 3600}h{(s % 3600) // 60:02d}m"


def format_zulu(moment: datetime, *, day: bool = False) -> str:
    """Format as 12:34Z, or Mon 12:34Z with day=True."""
    utc = ensure_utc(moment)
    stamp = f"{utc:%H:%M}Z"
    return f"{utc:%a} {stamp}" if day else stamp


def format_when(moment: datetime, tz: tzinfo | None = None, *, day: bool = False) -> str:
    """Format as 21:00Z (17:00 EDT), or Wed 21:00Z (Wed 17:00 EDT) with day=True; just the Zulu part without a zone."""
    stamp = format_zulu(moment, day=day)
    local = ensure_utc(moment).astimezone(tz) if tz is not None else None
    if local is None or local.utcoffset() == timedelta(0):
        return stamp
    clock = f"{local:%a %H:%M}" if day else f"{local:%H:%M}"
    return f"{stamp} ({clock} {local.tzname() or ''})".replace(" )", ")")
