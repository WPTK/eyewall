"""Headless mode: run the poller with no interface and print the events.

`eyewall --replay demo --headless --until +12h` replays the recorded storm on its virtual clock, polling as the real app
would, and prints each alert-worthy event. It exists for tests and demos, and it is what proves the poller, the store
and the alert rules work before there is a UI. A second run against the same state directory prints nothing again,
because the seen set was saved.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import TextIO

from eyewall.clock import VirtualClock, parse_utc
from eyewall.config import Config
from eyewall.models.events import Event
from eyewall.poll import Poller, no_sleep
from eyewall.sources.live import LiveSource
from eyewall.sources.protocol import DataSource
from eyewall.sources.replay import ReplaySource
from eyewall.state.alerts import AlertEngine
from eyewall.state.store import Store

_RELATIVE = re.compile(r"^\+(\d+(?:\.\d+)?)([smhd])$")
_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


class UntilError(ValueError):
    """`--until` is neither a `+12h` style offset nor an ISO timestamp."""


def parse_until(text: str, start: datetime) -> datetime:
    """`+90m`, `+12h`, `+2d` (from `start`) or an ISO 8601 timestamp (UTC when it names no zone)."""
    match = _RELATIVE.match(text.strip())
    if match:
        return start + timedelta(seconds=float(match.group(1)) * _UNITS[match.group(2)])
    try:
        return parse_utc(text)
    except ValueError:
        raise UntilError(f"cannot read --until {text!r}: use +12h, +90m, +2d or an ISO timestamp") from None


def format_event(event: Event) -> str:
    return f"{event.time:%Y-%m-%d %H:%MZ}  {event.kind.value:<16} {event.message}"


@dataclass(slots=True)
class HeadlessResult:
    events: list[Event] = field(default_factory=list)
    polls: int = 0
    ended: datetime | None = None


async def run_replay(
    source: ReplaySource,
    config: Config,
    state_dir: Path | None,
    until: str,
    *,
    emit: Callable[[Event], None] | None = None,
) -> HeadlessResult:
    """Poll a replay from the start of its window until `until`, advancing the virtual clock between polls."""
    clock = source.clock
    end = parse_until(until, clock.now())
    return await _drive(source, config, state_dir, clock, end, emit)


async def _drive(
    source: DataSource,
    config: Config,
    state_dir: Path | None,
    clock: VirtualClock,
    end: datetime,
    emit: Callable[[Event], None] | None,
) -> HeadlessResult:
    result = HeadlessResult()

    def collect(events: list[Event]) -> None:
        for event in events:
            result.events.append(event)
            if emit is not None:
                emit(event)

    poller = Poller(
        source,
        Store(config),
        AlertEngine(config.alerts, state_dir),
        config.poll,
        clock=clock,
        sleep=no_sleep,
        on_events=collect,
    )
    while True:
        await poller.tick()
        result.polls += 1
        wait = poller.seconds_until_next()
        step = poller.interval("storms") if wait is None else max(wait, 1.0)
        if clock.now() + timedelta(seconds=step) > end:
            break
        clock.advance(step)
    clock.set(min(end, clock.now()))
    result.ended = clock.now()
    return result


async def run_live(
    config: Config, state_dir: Path | None, until: str | None, *, emit: Callable[[Event], None] | None = None
) -> HeadlessResult:
    """Poll the real services once, or for the duration given as `+30m`, and print the events."""
    source = LiveSource()
    result = HeadlessResult()

    def collect(events: list[Event]) -> None:
        for event in events:
            result.events.append(event)
            if emit is not None:
                emit(event)

    try:
        poller = Poller(source, Store(config), AlertEngine(config.alerts, state_dir), config.poll, on_events=collect)
        end = None if until is None else parse_until(until, source.now())
        while True:
            await poller.tick()
            result.polls += 1
            due = poller.seconds_until_next()  # 0.0 means a feed is due now: poll it now, not after a full interval
            wait = poller.interval("storms") if due is None else due
            if end is None or source.now() + timedelta(seconds=wait) > end:
                break
            await asyncio.sleep(wait)
        result.ended = source.now()
    finally:
        await source.aclose()
    return result


def print_event(event: Event, out: TextIO) -> None:
    print(format_event(event), file=out, flush=True)
