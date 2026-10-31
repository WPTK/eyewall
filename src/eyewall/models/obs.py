"""Observation records from NDBC stations and CO-OPS tide gauges.

Frozen dataclasses with no behaviour beyond tiny conveniences. Every measurement is optional because both services
leave out whatever a station does not report. Units stay as NOAA reported them and are written into the field names:
NDBC speaks metres per second, hectopascals, degrees Celsius and metres; the CO-OPS requests made by eyewall use the
"english" unit system, so water levels are feet, winds knots and pressure millibars. Convert only for display.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Parsed[T]:
    """What a tolerant parser found: the records, how many malformed rows it skipped, and any NOAA message.

    message is the explanation NOAA gave when it had no data (CO-OPS answers 200 with an error object), never an
    exception: no data is a normal state for a gauge that does not offer a product.
    """

    items: tuple[T, ...] = ()
    skipped: int = 0
    message: str | None = None


# --- NDBC ---------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Station:
    """An NDBC station from activestations.xml.

    id is upper case, the form used in data file names (the XML lists C-MAN ids in lower case). The four flags say
    whether the station reported that kind of data in the last 8 hours; None means the catalog omitted the flag.
    """

    id: str
    name: str
    lat: float
    lon: float
    type: str = ""
    owner: str = ""
    program: str = ""
    elevation_m: float | None = None
    met: bool | None = None
    currents: bool | None = None
    water_quality: bool | None = None
    dart: bool | None = None


@dataclass(frozen=True, slots=True)
class Observation:
    """One row of standard meteorological data. Every measurement may be None."""

    time: datetime
    wind_dir_deg: float | None = None
    wind_speed_mps: float | None = None
    gust_mps: float | None = None
    wave_height_m: float | None = None
    dominant_period_s: float | None = None
    average_period_s: float | None = None
    mean_wave_dir_deg: float | None = None
    pressure_hpa: float | None = None
    pressure_tendency_hpa: float | None = None
    air_temp_c: float | None = None
    water_temp_c: float | None = None
    dewpoint_c: float | None = None
    visibility_nmi: float | None = None
    tide_ft: float | None = None


@dataclass(frozen=True, slots=True)
class LatestObservation:
    """A row of latest_obs.txt: the station's newest observation and where the station is."""

    station_id: str
    lat: float | None
    lon: float | None
    observation: Observation


@dataclass(frozen=True, slots=True)
class ObservationSeries:
    """A station's observations, newest first. Empty means the station is not reporting (its file was a 404)."""

    station_id: str
    observations: tuple[Observation, ...] = ()
    skipped: int = 0

    @property
    def latest(self) -> Observation | None:
        return self.observations[0] if self.observations else None

    @property
    def reporting(self) -> bool:
        return bool(self.observations)


@dataclass(frozen=True, slots=True)
class SupplementalReading:
    """One row of a .supl file: the lowest pressure and the highest wind within a reporting interval."""

    time: datetime
    min_pressure_hpa: float | None = None
    min_pressure_time: datetime | None = None
    peak_wind_mps: float | None = None
    peak_wind_dir_deg: float | None = None
    peak_wind_time: datetime | None = None


@dataclass(frozen=True, slots=True)
class WaveSummary:
    """One row of a .spec file. Directions are compass text (ENE) exactly as NDBC prints them."""

    time: datetime
    wave_height_m: float | None = None
    swell_height_m: float | None = None
    swell_period_s: float | None = None
    wind_wave_height_m: float | None = None
    wind_wave_period_s: float | None = None
    swell_direction: str | None = None
    wind_wave_direction: str | None = None
    steepness: str | None = None
    average_period_s: float | None = None
    mean_wave_dir_deg: float | None = None


# --- CO-OPS -------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TideStation:
    """A CO-OPS station from the metadata API.

    products says which listing the station came from: "water_level" for type=waterlevels, "met" for type=met
    (wind and air pressure). great_lakes gauges answer HTTP 400 to MLLW; ask for IGLD instead.
    """

    id: str
    name: str
    lat: float
    lon: float
    state: str = ""
    great_lakes: bool = False
    products: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class WaterLevelReading:
    """One 6-minute water level in feet above the requested datum.

    sigma_ft is the standard deviation of the 1-second samples; flags is the raw "0,0,0,0" string (outlier, flat
    tolerance, rate of change, limit exceeded) and quality is "p" preliminary or "v" verified.
    """

    time: datetime
    level_ft: float | None = None
    sigma_ft: float | None = None
    flags: str = ""
    quality: str = ""

    @property
    def flagged(self) -> bool:
        """True when any quality check marked this reading."""
        return "1" in self.flags.replace(",", "")


@dataclass(frozen=True, slots=True)
class Prediction:
    """A tide prediction in feet above the datum. kind is "H" or "L" for high/low tide, None for interval data."""

    time: datetime
    level_ft: float | None = None
    kind: str | None = None


@dataclass(frozen=True, slots=True)
class TideWind:
    """A 6-minute wind observation at a tide gauge, in knots."""

    time: datetime
    speed_kt: float | None = None
    direction_deg: float | None = None
    direction_text: str | None = None
    gust_kt: float | None = None
    flags: str = ""


@dataclass(frozen=True, slots=True)
class TidePressure:
    """A 6-minute air pressure observation at a tide gauge, in millibars."""

    time: datetime
    pressure_mb: float | None = None
    flags: str = ""
