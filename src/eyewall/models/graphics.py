"""Links to NOAA graphics: the NHC forecast graphics and the NESDIS satellite floater products."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from eyewall.models.storm import AdvNum


class GraphicKind(StrEnum):
    CONE = "cone"
    WIND_PROBABILITY = "wind_probability"
    ARRIVAL_EARLIEST = "arrival_earliest"
    ARRIVAL_MOST_LIKELY = "arrival_most_likely"
    SURGE_WATCH_WARNING = "surge_watch_warning"
    SURGE_PEAK = "surge_peak"
    SURGE_FLOODING = "surge_flooding"
    KEY_MESSAGES = "key_messages"
    CURRENT_WIND = "current_wind"
    RAINFALL = "rainfall"
    RIP_CURRENTS = "rip_currents"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class GraphicLink:
    """One graphic found on a forecast graphics page.

    `product` is the product name taken from the file name (`5day_cone_with_line_and_wind`), `media` the file
    extension (`png`, `gif`, `jpg`, `kmz`). `days` and `threshold_kt` are filled in when the name carries them.
    """

    kind: GraphicKind
    product: str
    url: str
    media: str
    adv_num: AdvNum | None = None
    days: int | None = None
    threshold_kt: int | None = None


@dataclass(frozen=True, slots=True)
class FloaterProduct:
    """The newest still image and loop for one NESDIS floater product (GEOCOLOR, AirMass, a band number...).

    `still_url` is the newest time-stamped still; `latest_url` is the rolling `latest.jpg`/`1000x1000.jpg` copy.
    `loop_url` is the full loop; when only time-ranged loops exist it is the newest of those.
    """

    storm_id: str
    product: str
    base_url: str
    still_url: str | None = None
    still_time: datetime | None = None
    latest_url: str | None = None
    loop_url: str | None = None
    loop_start: datetime | None = None
    loop_end: datetime | None = None
