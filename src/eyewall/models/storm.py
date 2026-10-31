"""Storms as listed in CurrentStorms.json, and the small value types shared by every NHC product.

Everything here is a frozen dataclass. Units stay as NOAA reported them: `movement_speed_mph` is in miles per hour
because that feed says so (the forecast advisory text uses knots), and the field name carries the unit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Basin(StrEnum):
    """The three basins eyewall follows. Values are the two-letter prefixes used in storm ids and ATCF files."""

    AL = "AL"
    EP = "EP"
    CP = "CP"


class Classification(StrEnum):
    """The `classification` codes in CurrentStorms.json. Anything else becomes UNKNOWN (the raw text is kept)."""

    TD = "TD"
    STD = "STD"
    TS = "TS"
    HU = "HU"
    STS = "STS"
    PTC = "PTC"
    PC = "PC"
    TY = "TY"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True, order=True)
class AdvNum:
    """An advisory number such as 30 or 18A. The suffix marks an intermediate advisory and is always upper case."""

    number: int
    suffix: str = ""

    @property
    def intermediate(self) -> bool:
        return bool(self.suffix)

    def __str__(self) -> str:
        return f"{self.number}{self.suffix}"


@dataclass(frozen=True, slots=True)
class ProductRef:
    """A text product listed for a storm: where it is and which advisory it belongs to."""

    adv_num: AdvNum | None = None
    issued: datetime | None = None
    updated: datetime | None = None
    url: str | None = None


@dataclass(frozen=True, slots=True)
class GisRef:
    """A GIS product listed for a storm: a zip of shapefiles, a KMZ and/or a KML (the surge products)."""

    adv_num: AdvNum | None = None
    issued: datetime | None = None
    updated: datetime | None = None
    zip_url: str | None = None
    kmz_url: str | None = None
    kml_url: str | None = None


@dataclass(frozen=True, slots=True)
class WindProbabilityGisRef:
    """The `windSpeedProbabilitiesGIS` object, which has one URL per file instead of a zip and a KMZ."""

    issued: datetime | None = None
    updated: datetime | None = None
    zip_5km_url: str | None = None
    zip_half_degree_url: str | None = None
    kmz_34kt_url: str | None = None
    kmz_50kt_url: str | None = None
    kmz_64kt_url: str | None = None


@dataclass(frozen=True, slots=True)
class Storm:
    """One active tropical cyclone from CurrentStorms.json. Key storms by `id`, never by `bin_number`."""

    id: str
    bin_number: str | None
    name: str
    classification: Classification
    classification_text: str
    intensity_kt: int | None
    pressure_mb: int | None
    lat: float | None
    lon: float | None
    movement_dir_deg: int | None
    movement_speed_mph: float | None
    last_update: datetime | None
    public_advisory: ProductRef | None = None
    forecast_advisory: ProductRef | None = None
    wind_speed_probabilities: ProductRef | None = None
    forecast_discussion: ProductRef | None = None
    forecast_graphics: ProductRef | None = None
    forecast_track: GisRef | None = None
    track_cone: GisRef | None = None
    initial_wind_extent: GisRef | None = None
    forecast_wind_radii: GisRef | None = None
    wind_watches_warnings: GisRef | None = None
    best_track: GisRef | None = None
    earliest_arrival_ts_winds: GisRef | None = None
    most_likely_ts_winds: GisRef | None = None
    wind_speed_probabilities_gis: WindProbabilityGisRef | None = None
    storm_surge_watch_warning: GisRef | None = None
    potential_storm_surge_flooding: GisRef | None = None
    peak_surge: GisRef | None = None

    @property
    def basin(self) -> Basin | None:
        """The basin in the storm id. A storm that crossed 140 W keeps its `ep` id, so this can differ from the bin."""
        try:
            return Basin(self.id[:2].upper())
        except ValueError:
            return None

    @property
    def bin_basin(self) -> Basin | None:
        """The basin of the product bin: AT is the Atlantic, EP and CP are themselves."""
        prefix = (self.bin_number or "")[:2].upper()
        if prefix == "AT":
            return Basin.AL
        try:
            return Basin(prefix)
        except ValueError:
            return None

    @property
    def adv_num(self) -> AdvNum | None:
        """The advisory number of the newest text product, from the forecast advisory first."""
        for ref in (self.forecast_advisory, self.public_advisory, self.forecast_discussion):
            if ref is not None and ref.adv_num is not None:
                return ref.adv_num
        return None

    @property
    def is_potential(self) -> bool:
        return self.classification is Classification.PTC


@dataclass(frozen=True, slots=True)
class CurrentStorms:
    """The parsed CurrentStorms.json. `skipped` counts entries that were not usable (no id)."""

    storms: tuple[Storm, ...] = ()
    skipped: int = 0

    def by_id(self, storm_id: str) -> Storm | None:
        wanted = storm_id.lower()
        return next((s for s in self.storms if s.id == wanted), None)
