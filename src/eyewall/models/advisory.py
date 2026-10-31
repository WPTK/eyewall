"""The text advisories: public advisory (TCP) and discussion (TCD), plus the bundle of all four products."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from eyewall.models.forecast import ForecastAdvisory
from eyewall.models.storm import AdvNum
from eyewall.models.watches import WatchWarningArea
from eyewall.models.wind import WindProbabilities


@dataclass(frozen=True, slots=True)
class PublicSummary:
    """The `SUMMARY OF ... INFORMATION` block. The public advisory reports mph and km/h, not knots."""

    location_text: str | None = None
    lat: float | None = None
    lon: float | None = None
    about: tuple[str, ...] = ()
    max_wind_mph: int | None = None
    movement_text: str | None = None
    movement_dir_deg: int | None = None
    movement_speed_mph: int | None = None
    pressure_mb: int | None = None
    pressure_in: float | None = None


@dataclass(frozen=True, slots=True)
class WatchWarningText:
    """The `WATCHES AND WARNINGS` section: what changed, what is in effect and the section's own words."""

    changes: tuple[str, ...] = ()
    in_effect: tuple[WatchWarningArea, ...] = ()
    none_in_effect: bool = False
    text: str = ""


@dataclass(frozen=True, slots=True)
class PublicAdvisory:
    """A parsed public advisory (TCP)."""

    storm_id: str | None
    kind: str | None
    name: str | None
    adv_num: AdvNum | None
    issued: datetime | None
    issued_text: str | None
    headlines: tuple[str, ...]
    summary: PublicSummary
    watches_warnings: WatchWarningText
    discussion: str
    hazards: tuple[tuple[str, str], ...]
    key_messages: tuple[str, ...]
    next_advisory: str
    forecaster: str | None
    is_last: bool = False

    @property
    def headline(self) -> str | None:
        """The headlines joined into one line, or None when the advisory has none."""
        return " ".join(self.headlines) if self.headlines else None


@dataclass(frozen=True, slots=True)
class DiscussionFix:
    """One line of the `FORECAST POSITIONS AND MAX WINDS` table. Dissipated lines have no position or wind."""

    hour: int
    valid: datetime | None
    lat: float | None
    lon: float | None
    wind_kt: int | None
    wind_mph: int | None
    status: str | None = None
    dissipated: bool = False


@dataclass(frozen=True, slots=True)
class Discussion:
    """A parsed forecast discussion (TCD)."""

    storm_id: str | None
    kind: str | None
    name: str | None
    adv_num: AdvNum | None
    issued: datetime | None
    issued_text: str | None
    paragraphs: tuple[str, ...]
    key_messages: tuple[str, ...]
    forecast: tuple[DiscussionFix, ...]
    forecaster: str | None
    is_last: bool = False


@dataclass(frozen=True, slots=True)
class ProductListing:
    """One entry of an api.weather.gov product list: enough to pick the newest product and fetch it."""

    id: str
    code: str | None
    name: str | None
    office: str | None
    wmo_id: str | None
    issued: datetime | None


@dataclass(frozen=True, slots=True)
class ApiProduct:
    """An api.weather.gov product with its raw text, the fallback when tgftp fails."""

    id: str
    code: str | None
    office: str | None
    wmo_id: str | None
    issued: datetime | None
    text: str


@dataclass(frozen=True, slots=True)
class AdvisorySet:
    """Every text product for one storm. A product that could not be fetched or parsed is None."""

    forecast: ForecastAdvisory | None = None
    public: PublicAdvisory | None = None
    discussion: Discussion | None = None
    wind_probabilities: WindProbabilities | None = None

    @property
    def adv_num(self) -> AdvNum | None:
        for product in (self.forecast, self.public, self.discussion, self.wind_probabilities):
            if product is not None and product.adv_num is not None:
                return product.adv_num
        return None
