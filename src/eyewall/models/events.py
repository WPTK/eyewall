"""Events: what changed between two successive states of the store, in a form the alert rules and the UI can use."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class EventKind(StrEnum):
    NEW_STORM = "new_storm"
    NEW_PTC = "new_ptc"
    NEW_INVEST = "new_invest"
    NEW_ADVISORY = "new_advisory"
    CLASSIFICATION = "classification"
    WATCH_WARNING_ISSUED = "ww_issued"
    WATCH_WARNING_CHANGED = "ww_changed"
    WATCH_WARNING_DISCONTINUED = "ww_discontinued"
    NEW_OUTLOOK = "new_outlook"
    NEW_DISCUSSION = "new_discussion"
    BUOY_THRESHOLD = "buoy_threshold"
    BUOY_SILENT = "buoy_silent"


class Severity(StrEnum):
    INFO = "info"
    NOTICE = "notice"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class Event:
    """One thing that happened.

    `key` identifies it for de-duplication: the same event seen again after a restart has the same key. It is built
    from the storm id, the advisory number where the event belongs to one, the kind and the subject (an area, a
    station, a threshold), so a repeated poll of unchanged data never fires twice.
    """

    kind: EventKind
    key: str
    message: str
    time: datetime
    storm_id: str | None = None
    adv_num: str | None = None
    subject: str | None = None
    severity: Severity = Severity.INFO


def make_key(kind: EventKind, storm_id: str | None, adv_num: str | None, subject: str | None = None) -> str:
    """The de-duplication key: (storm id, advisory number, kind) plus the subject when the event has one."""
    return "|".join((storm_id or "-", adv_num or "-", kind.value, subject or "-"))
