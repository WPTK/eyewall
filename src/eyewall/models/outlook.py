"""Tropical weather outlooks: the text (TWO) and the outlook shapes (gtwo shapefiles)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from eyewall.geo import LatLon
from eyewall.models.track import BestTrack
from eyewall.models.wind import Ring


@dataclass(frozen=True, slots=True)
class Chance:
    """A formation chance: the risk label (`low`, `medium`, `high`) and the percentage. `near 0` is 0."""

    risk: str | None
    percent: int | None


@dataclass(frozen=True, slots=True)
class OutlookArea:
    """One area described in the outlook text, with its 48 hour and 7 day formation chances."""

    number: int | None
    title: str
    invest_id: str | None
    description: str
    chance_48h: Chance | None
    chance_7d: Chance | None


@dataclass(frozen=True, slots=True)
class OutlookText:
    """A parsed tropical weather outlook for one basin.

    `summary` is the text before any area (for example "Tropical cyclone formation is not expected during the next 7
    days."); `notes` is anything printed after the last area, such as the WMO headers of active advisories.
    """

    office: str | None
    issued: datetime | None
    issued_text: str | None
    region: str | None
    active_systems: str | None
    areas: tuple[OutlookArea, ...]
    summary: str
    notes: str
    forecaster: str | None

    @property
    def quiet(self) -> bool:
        """True when the outlook lists no areas of interest and no active systems."""
        return not self.areas and not self.active_systems


@dataclass(frozen=True, slots=True)
class OutlookSystem:
    """An outlook area from the gtwo shapefiles, with its polygon, track line and marker point.

    `basin_label` is NOAA's `BASIN` field (Atlantic or Pacific); the Pacific covers both the East and Central Pacific.
    """

    basin_label: str
    area_id: str
    prob_2day: int | None
    risk_2day: str | None
    prob_7day: int | None
    risk_7day: str | None
    polygons: tuple[Ring, ...] = ()
    lines: tuple[tuple[LatLon, ...], ...] = ()
    point: LatLon | None = None


@dataclass(frozen=True, slots=True)
class OutlookGis:
    issued: datetime | None
    systems: tuple[OutlookSystem, ...] = ()

    @property
    def empty(self) -> bool:
        return not self.systems


@dataclass(frozen=True, slots=True)
class Outlook:
    """Everything the outlook feed brings: the text per basin, the area shapes and the active invest b-decks."""

    texts: tuple[OutlookText, ...] = ()
    gis: OutlookGis = OutlookGis(None)
    invests: tuple[BestTrack, ...] = ()
