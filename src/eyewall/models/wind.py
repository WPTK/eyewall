"""Wind radii, seas radii and the wind speed probability table."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from eyewall.geo import LatLon
from eyewall.models.storm import AdvNum

Ring = tuple[LatLon, ...]


@dataclass(frozen=True, slots=True)
class QuadrantRadii:
    """Radius in nautical miles in each quadrant. None means NOAA gave no value; 0 means none in that quadrant."""

    ne: int | None = None
    se: int | None = None
    sw: int | None = None
    nw: int | None = None

    @property
    def largest(self) -> int | None:
        values = [v for v in (self.ne, self.se, self.sw, self.nw) if v is not None]
        return max(values) if values else None


@dataclass(frozen=True, slots=True)
class WindRadii:
    """Radii by wind threshold. A threshold NOAA left out (it does not apply) is None."""

    kt34: QuadrantRadii | None = None
    kt50: QuadrantRadii | None = None
    kt64: QuadrantRadii | None = None

    def for_threshold(self, kt: int) -> QuadrantRadii | None:
        return {34: self.kt34, 50: self.kt50, 64: self.kt64}.get(kt)

    @property
    def empty(self) -> bool:
        return self.kt34 is None and self.kt50 is None and self.kt64 is None


@dataclass(frozen=True, slots=True)
class SeasRadii:
    """The radii of seas at or above a height. NOAA reports 4 m (`M`) or 12 ft (`FT`) depending on the product."""

    height: int
    unit: str
    radii: QuadrantRadii


@dataclass(frozen=True, slots=True)
class RadiiPolygon:
    """One wind radii polygon from the `forecastradii` or `initialradii` layers."""

    kt: int
    tau: int | None
    valid: datetime | None
    synoptic: datetime | None
    radii: QuadrantRadii
    rings: tuple[Ring, ...]


@dataclass(frozen=True, slots=True)
class WindRadiiGis:
    storm_id: str | None
    adv_num: AdvNum | None
    initial: tuple[RadiiPolygon, ...] = ()
    forecast: tuple[RadiiPolygon, ...] = ()


@dataclass(frozen=True, slots=True)
class ProbabilityCell:
    """One time period of the wind probability table. NOAA prints `X` for less than one percent; that is 0 here."""

    onset: int
    cumulative: int


@dataclass(frozen=True, slots=True)
class WindProbabilityRow:
    location: str
    threshold_kt: int
    cells: tuple[ProbabilityCell | None, ...]


@dataclass(frozen=True, slots=True)
class WindProbabilities:
    """The PWS product: probabilities of 34, 50 and 64 kt winds at named places over the next five days."""

    storm_id: str | None
    name: str | None
    adv_num: AdvNum | None
    issued: datetime | None
    forecast_hours: tuple[int, ...]
    rows: tuple[WindProbabilityRow, ...]
    skipped: int = 0

    def for_location(self, location: str) -> tuple[WindProbabilityRow, ...]:
        wanted = location.strip().upper()
        return tuple(r for r in self.rows if r.location.upper() == wanted)

    @property
    def locations(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for row in self.rows:
            seen.setdefault(row.location, None)
        return tuple(seen)
