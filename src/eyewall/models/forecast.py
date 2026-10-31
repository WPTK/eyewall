"""The forecast advisory (TCM text) and the forecast GIS layers (cone, points, track line, warnings)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from eyewall.geo import LatLon
from eyewall.models.storm import AdvNum
from eyewall.models.watches import WatchWarningSegment
from eyewall.models.wind import Ring, SeasRadii, WindRadii


@dataclass(frozen=True, slots=True)
class ForecastFix:
    """One forecast or outlook position from a TCM.

    `tau` counts hours from the synoptic time, which is three hours before the advisory. Fixes at 12 to 72 hours are
    forecasts; the ones at 96 and 120 hours are the extended outlook (`outlook` is true). A system that is forecast to
    dissipate has no position and `dissipated` set. `status` is the text NHC adds after the position, such as
    `POST-TROP/REMNT LOW`.
    """

    tau: int
    valid: datetime
    lat: float | None
    lon: float | None
    max_wind_kt: int | None
    gust_kt: int | None
    radii: WindRadii
    status: str | None = None
    dissipated: bool = False
    outlook: bool = False


@dataclass(frozen=True, slots=True)
class PriorFix:
    """The `AT dd/hhmmZ CENTER WAS LOCATED NEAR` line: where the center was at the synoptic time."""

    time: datetime
    lat: float
    lon: float


@dataclass(frozen=True, slots=True)
class ForecastAdvisory:
    """A parsed forecast/advisory (TCM). The numeric truth behind the map; units are NOAA's (knots, nautical miles)."""

    storm_id: str | None
    kind: str
    name: str | None
    adv_num: AdvNum | None
    issued: datetime
    synoptic: datetime
    center_kind: str | None
    lat: float | None
    lon: float | None
    position_accuracy_nm: int | None
    movement_text: str | None
    movement_dir_deg: int | None
    movement_speed_kt: int | None
    pressure_mb: int | None
    eye_diameter_nm: int | None
    max_wind_kt: int | None
    gust_kt: int | None
    radii: WindRadii
    seas: SeasRadii | None
    prior: PriorFix | None
    fixes: tuple[ForecastFix, ...]
    is_final: bool = False
    next_advisory: datetime | None = None

    @property
    def forecast_fixes(self) -> tuple[ForecastFix, ...]:
        return tuple(f for f in self.fixes if not f.outlook)

    @property
    def outlook_fixes(self) -> tuple[ForecastFix, ...]:
        return tuple(f for f in self.fixes if f.outlook)

    @property
    def post_tropical(self) -> bool:
        return "POST-TROP" in self.kind

    @property
    def potential(self) -> bool:
        return "POTENTIAL" in self.kind

    @property
    def remnants(self) -> bool:
        return self.kind.startswith("REMNANTS")


@dataclass(frozen=True, slots=True)
class ForecastPoint:
    """A forecast point from the `*_5day_pts` layer. NOAA's 9999 fills become None."""

    tau: int
    lat: float
    lon: float
    max_wind_kt: int | None
    gust_kt: int | None
    mslp_mb: int | None
    storm_type: str | None
    development: str | None
    saffir_simpson: int | None
    date_label: str | None
    local_label: str | None
    timezone: str | None
    valid: datetime | None
    direction_deg: int | None
    speed_kt: int | None


@dataclass(frozen=True, slots=True)
class ForecastGis:
    """The `*_5day` zip: forecast points, the track line, the cone and the coastal watch and warning lines.

    A layer missing from the zip comes back empty. Longitudes are wrapped to (-180, 180]; a ring that crosses the
    dateline therefore jumps between 180 and -180, so unwrap relative to the map center before drawing.
    """

    storm_name: str | None
    storm_type: str | None
    adv_num: AdvNum | None
    adv_date_text: str | None
    issued: datetime | None
    points: tuple[ForecastPoint, ...] = ()
    track: tuple[tuple[LatLon, ...], ...] = ()
    cone: tuple[Ring, ...] = ()
    watch_warnings: tuple[WatchWarningSegment, ...] = ()
