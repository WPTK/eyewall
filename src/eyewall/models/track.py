"""Best track: ATCF b-deck fixes (including invests) and the best track GIS zip."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from eyewall.geo import LatLon
from eyewall.models.wind import WindRadii


@dataclass(frozen=True, slots=True)
class BestTrackFix:
    """One time from a b-deck, with the up to three radii lines of that time merged into `radii`.

    `vmax_kt` and `mslp_mb` are None when the file holds 0 (not known). `direction_deg` and `speed_kt` are as filed;
    early rows often carry 0 for both. `type` is the ATCF level (DB, LO, TD, TS, HU, EX, SD, SS, WV, ...).
    """

    time: datetime
    lat: float
    lon: float
    vmax_kt: int | None
    mslp_mb: int | None
    type: str | None
    radii: WindRadii
    rmw_nm: int | None
    gusts_kt: int | None
    eye_nm: int | None
    pouter_mb: int | None
    router_nm: int | None
    direction_deg: int | None
    speed_kt: int | None
    name: str | None
    depth: str | None


@dataclass(frozen=True, slots=True)
class BestTrack:
    """A parsed b-deck. Invests are numbers 90 to 99; 80 to 89 are training systems and should be ignored."""

    basin_code: str
    number: int
    fixes: tuple[BestTrackFix, ...]
    skipped: int = 0

    @property
    def is_invest(self) -> bool:
        return 90 <= self.number <= 99

    @property
    def is_training(self) -> bool:
        return 80 <= self.number <= 89

    @property
    def latest(self) -> BestTrackFix | None:
        return self.fixes[-1] if self.fixes else None

    @property
    def name(self) -> str | None:
        """The newest storm name that is not the INVEST placeholder."""
        for fix in reversed(self.fixes):
            if (
                fix.name
                and fix.name.upper() not in {"INVEST", "GENESIS", "NONAME"}
                and not fix.name.upper().startswith("GENESIS")
            ):
                return fix.name
        return None


@dataclass(frozen=True, slots=True)
class BDeckFile:
    """A b-deck file in the ATCF `btk` directory listing."""

    name: str
    basin_code: str
    number: int
    year: int
    modified: datetime | None
    size_bytes: int | None

    @property
    def storm_id(self) -> str:
        return f"{self.basin_code.lower()}{self.number:02d}{self.year}"

    @property
    def is_invest(self) -> bool:
        return 90 <= self.number <= 99

    @property
    def is_training(self) -> bool:
        return 80 <= self.number <= 89


@dataclass(frozen=True, slots=True)
class BestTrackPoint:
    """A point from the best track GIS `*_pts` layer."""

    time: datetime | None
    lat: float
    lon: float
    storm_name: str | None
    storm_type: str | None
    intensity_kt: int | None
    mslp_mb: int | None
    saffir_simpson: int | None


@dataclass(frozen=True, slots=True)
class BestTrackSegment:
    """A segment from the best track GIS `*_lin` layer: one stretch of track at one storm type."""

    storm_type: str | None
    saffir_simpson: int | None
    points: tuple[LatLon, ...]


@dataclass(frozen=True, slots=True)
class BestTrackGis:
    storm_id: str | None
    points: tuple[BestTrackPoint, ...] = ()
    segments: tuple[BestTrackSegment, ...] = ()
