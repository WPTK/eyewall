"""Alert rules and the persisted seen set.

`AlertEngine.process` takes the events a store produced and returns the ones to show: the `[alerts]` rules decide which
kinds are wanted, and the seen set (event keys, saved under `user_data_dir("eyewall")`) stops an event the user was
already told about from firing again after a restart or a second poll of unchanged data.

`tropical_alerts` is the one filter on the api.weather.gov feed: the query also matches two non-tropical event types
(Extreme Wind Warning, Hurricane Force Wind Warning), which are dropped here.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from platformdirs import user_data_dir

from eyewall.config import AlertsConfig
from eyewall.models.events import Event, EventKind
from eyewall.models.watches import AlertsResult, WatchWarningAlert

SEEN_FILE = "seen_events.json"
SEEN_MAX_AGE = timedelta(days=30)
NON_TROPICAL_EVENTS = frozenset({"extreme wind warning", "hurricane force wind warning"})

_RULE_FOR_KIND: dict[EventKind, str | None] = {
    EventKind.NEW_STORM: None,
    EventKind.NEW_PTC: None,
    EventKind.NEW_ADVISORY: "new_advisory",
    EventKind.NEW_DISCUSSION: "new_advisory",
    EventKind.CLASSIFICATION: "classification",
    EventKind.WATCH_WARNING_ISSUED: "watches_warnings",
    EventKind.WATCH_WARNING_CHANGED: "watches_warnings",
    EventKind.WATCH_WARNING_DISCONTINUED: "watches_warnings",
    EventKind.NEW_OUTLOOK: "outlook",
    EventKind.NEW_INVEST: "outlook",
    EventKind.BUOY_THRESHOLD: "buoy_thresholds",
    EventKind.BUOY_SILENT: "buoy_thresholds",
}


def default_state_dir() -> Path:
    return Path(user_data_dir("eyewall", appauthor=False))


def tropical_alerts(result: AlertsResult) -> AlertsResult:
    """The alerts that belong to a tropical cyclone: all but the non-tropical event types the query also returns."""
    kept = tuple(a for a in result.alerts if a.event.strip().lower() not in NON_TROPICAL_EVENTS)
    dropped = len(result.alerts) - len(kept)
    return AlertsResult(kept, result.updated, result.skipped) if dropped else result


def is_wanted(kind: EventKind, rules: AlertsConfig) -> bool:
    rule = _RULE_FOR_KIND[kind]
    return True if rule is None else bool(getattr(rules, rule))


class SeenSet:
    """Event keys already reported, saved as JSON. A file that is missing or unreadable is an empty set."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._keys: dict[str, str] = {}
        self._dirty = False
        self._load()

    def _load(self) -> None:
        if self.path is None:
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._keys = {str(k): str(v) for k, v in data["keys"].items()}
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            self._keys = {}

    def __contains__(self, key: str) -> bool:
        return key in self._keys

    def __len__(self) -> int:
        return len(self._keys)

    def add(self, key: str, when: datetime) -> None:
        self._keys[key] = when.astimezone(UTC).isoformat()
        self._dirty = True

    def prune(self, now: datetime) -> None:
        cutoff = (now - SEEN_MAX_AGE).astimezone(UTC).isoformat()
        stale = [k for k, v in self._keys.items() if v < cutoff]
        for key in stale:
            del self._keys[key]
        self._dirty = self._dirty or bool(stale)

    def save(self) -> None:
        """Write the set if it changed. Failing to write is not an error: the worst case is a repeated alert."""
        if self.path is None or not self._dirty:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle, temp_name = tempfile.mkstemp(dir=self.path.parent, prefix=".tmp-")
            try:
                with os.fdopen(handle, "w", encoding="utf-8") as temp:
                    json.dump({"version": 1, "keys": self._keys}, temp, indent=0)
                os.replace(temp_name, self.path)
            except OSError:
                with contextlib.suppress(OSError):
                    os.unlink(temp_name)
                raise
            self._dirty = False
        except OSError:
            return


class AlertEngine:
    """Filters events by the `[alerts]` rules and by what was already reported."""

    def __init__(self, rules: AlertsConfig | None = None, state_dir: Path | None = None) -> None:
        self.rules = rules or AlertsConfig()
        self.seen = SeenSet(None if state_dir is None else state_dir / SEEN_FILE)
        self.log: list[Event] = []

    def process(self, events: Iterable[Event], now: datetime) -> list[Event]:
        """The events to show now, oldest first. Each is remembered, so the same event never comes back."""
        shown: list[Event] = []
        for event in events:
            if event.key in self.seen or not is_wanted(event.kind, self.rules):
                continue
            self.seen.add(event.key, now)
            shown.append(event)
        if shown:
            self.seen.prune(now)
            self.seen.save()
            self.log.extend(shown)
        return shown


def alert_summary(alert: WatchWarningAlert) -> str:
    """One line for a log: the event, the first part of the area and when it expires."""
    area = alert.area_desc if len(alert.area_desc) <= 80 else alert.area_desc[:77] + "..."
    ends = alert.ends or alert.expires
    return f"{alert.event}: {area}" + (f" until {ends:%d %b %H:%MZ}" if ends else "")
