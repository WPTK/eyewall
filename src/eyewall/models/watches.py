"""Coastal watches and warnings: the GIS line segments and the api.weather.gov alerts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from eyewall.geo import LatLon
from eyewall.palette import WatchWarning


@dataclass(frozen=True, slots=True)
class WatchWarningSegment:
    """One coastal watch or warning line from the `*_ww_wwlin` layer.

    `code` is NHC's TCWW code as published (TWA, TWR, HWA, HWR). `kind` is the matching palette value, or None for a
    code eyewall does not know, so a new code never breaks parsing.
    """

    code: str
    kind: WatchWarning | None
    points: tuple[LatLon, ...]


@dataclass(frozen=True, slots=True)
class WatchWarningArea:
    """A watch or warning block from a public advisory: its kind and the places listed under it."""

    label: str
    kind: WatchWarning | None
    areas: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WatchWarningAlert:
    """An api.weather.gov alert for a tropical event type."""

    id: str
    event: str
    kind: WatchWarning | None
    headline: str | None
    area_desc: str
    severity: str | None
    urgency: str | None
    certainty: str | None
    status: str | None
    message_type: str | None
    sender_name: str | None
    sent: datetime | None
    effective: datetime | None
    onset: datetime | None
    expires: datetime | None
    ends: datetime | None
    description: str | None
    instruction: str | None
    zones: tuple[str, ...]
    same_codes: tuple[str, ...]
    rings: tuple[tuple[LatLon, ...], ...]


@dataclass(frozen=True, slots=True)
class AlertsResult:
    """The alerts feed. `skipped` counts features that were not usable."""

    alerts: tuple[WatchWarningAlert, ...] = ()
    updated: datetime | None = None
    skipped: int = 0
