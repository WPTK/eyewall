"""Builders for the store, event and poller tests: small storms, advisories and a scriptable data source."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from eyewall.clock import VirtualClock
from eyewall.models.advisory import AdvisorySet, Discussion, PublicAdvisory, PublicSummary, WatchWarningText
from eyewall.models.forecast import ForecastAdvisory
from eyewall.models.graphics import FloaterProduct, GraphicLink
from eyewall.models.obs import (
    LatestObservation,
    Observation,
    ObservationSeries,
    Station,
    TideSeries,
    TideStation,
)
from eyewall.models.outlook import Outlook
from eyewall.models.storm import AdvNum, Classification, CurrentStorms, ProductRef, Storm
from eyewall.models.watches import AlertsResult, WatchWarningArea
from eyewall.models.wind import WindRadii
from eyewall.net import FetchError, HttpError
from eyewall.palette import WatchWarning

T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def adv(text: str) -> AdvNum:
    digits = "".join(c for c in text if c.isdigit())
    return AdvNum(int(digits), text[len(digits) :].upper())


def make_storm(
    adv_num: str = "1",
    *,
    storm_id: str = "al012026",
    name: str = "Ana",
    classification: Classification = Classification.TS,
    lat: float = 25.0,
    lon: float = -75.0,
    updated: datetime = T0,
    intermediate_only: bool = False,
) -> Storm:
    """A storm at advisory `adv_num`. With `intermediate_only` just the public advisory carries it (31A style)."""
    ref = ProductRef(adv(adv_num), updated, updated, None)
    older = ProductRef(adv("".join(c for c in adv_num if c.isdigit())), updated, updated, None)
    return Storm(
        id=storm_id,
        bin_number="AT1",
        name=name,
        classification=classification,
        classification_text=classification.value,
        intensity_kt=50,
        pressure_mb=1000,
        lat=lat,
        lon=lon,
        movement_dir_deg=300,
        movement_speed_mph=10.0,
        last_update=updated,
        public_advisory=ref,
        forecast_advisory=older if intermediate_only else ref,
        forecast_discussion=older if intermediate_only else ref,
    )


def area(label: str, *places: str) -> WatchWarningArea:
    kinds = {
        "TROPICAL STORM WATCH": WatchWarning.TROPICAL_STORM_WATCH,
        "TROPICAL STORM WARNING": WatchWarning.TROPICAL_STORM_WARNING,
        "HURRICANE WARNING": WatchWarning.HURRICANE_WARNING,
    }
    return WatchWarningArea(label, kinds.get(label.upper()), places)


def make_public(adv_num: str, *areas: WatchWarningArea, issued: datetime = T0) -> PublicAdvisory:
    return PublicAdvisory(
        storm_id="al012026",
        kind="TROPICAL STORM",
        name="ANA",
        adv_num=adv(adv_num),
        issued=issued,
        issued_text=None,
        headlines=(),
        summary=PublicSummary(),
        watches_warnings=WatchWarningText(in_effect=areas),
        discussion="",
        hazards=(),
        key_messages=(),
        next_advisory="",
        forecaster=None,
    )


def make_forecast(adv_num: str) -> ForecastAdvisory:
    n = adv(adv_num)
    return ForecastAdvisory(
        "al012026", "TROPICAL STORM", "ANA", AdvNum(n.number, ""), T0, T0, None, None, None, None, None, None, None,
        None, None, None, None, WindRadii(), None, None, (),
    )  # fmt: skip


def make_discussion(adv_num: str) -> Discussion:
    n = adv(adv_num)
    return Discussion("al012026", "TROPICAL STORM", "ANA", AdvNum(n.number, ""), T0, None, (), (), (), None)


def advisories(adv_num: str, *areas: WatchWarningArea) -> AdvisorySet:
    """Every product `make_storm` lists: the forecast and discussion carry the base number, the public the full one."""
    return AdvisorySet(
        forecast=make_forecast(adv_num),
        public=make_public(adv_num, *areas),
        discussion=make_discussion(adv_num),
    )


def obs(time: datetime, wind_kt: float | None = None, pressure: float | None = None) -> Observation:
    return Observation(
        time=time,
        wind_speed_mps=None if wind_kt is None else wind_kt * 1852 / 3600,
        pressure_hpa=pressure,
    )


def series(station: str, *rows: Observation) -> ObservationSeries:
    return ObservationSeries(station, tuple(sorted(rows, key=lambda o: o.time, reverse=True)))


def station(station_id: str, lat: float, lon: float) -> Station:
    return Station(station_id, station_id, lat, lon)


def gauge(station_id: str, lat: float, lon: float, *, great_lakes: bool = False) -> TideStation:
    return TideStation(station_id, station_id, lat, lon, great_lakes=great_lakes)


@dataclass
class FakeSource:
    """A `DataSource` whose answers a test sets and whose calls it can count."""

    clock: VirtualClock
    name: str = "fake"
    current: CurrentStorms = field(default_factory=CurrentStorms)
    texts: dict[str, AdvisorySet] = field(default_factory=dict)  # by the newest advisory number asked for
    fallback_texts: dict[str, AdvisorySet] = field(default_factory=dict)
    stations: tuple[Station, ...] = ()
    tide_stations: tuple[TideStation, ...] = ()
    buoy_series: dict[str, ObservationSeries] = field(default_factory=dict)
    fail: set[str] = field(default_factory=set)
    cached: set[str] = field(default_factory=set)
    calls: list[str] = field(default_factory=list)
    datums: list[tuple[str, str]] = field(default_factory=list)
    bad_datum: set[str] = field(default_factory=set)
    fail_products: set[str] = field(default_factory=set)  # forecast_gis, radii_gis, track or graphics
    alert_result: AlertsResult = field(default_factory=AlertsResult)

    def now(self) -> datetime:
        return self.clock.now()

    def stale(self, feed: str) -> bool:
        return feed in self.cached

    def start_poll(self, feed: str) -> None:
        return None

    def count(self, name: str) -> int:
        return self.calls.count(name)

    def _call(self, name: str, feed: str | None = None) -> None:
        self.calls.append(name)
        if (feed or name) in self.fail:
            raise FetchError("fake://" + name, "network down")

    def set_storm(self, adv_num: str, updated: datetime | None = None, **kw: object) -> None:
        self.current = CurrentStorms((make_storm(adv_num, updated=updated or self.clock.now(), **kw),))  # type: ignore[arg-type]

    async def storms(self) -> CurrentStorms:
        self._call("storms")
        return self.current

    async def advisory(self, storm: Storm, *, fallback: bool = False) -> AdvisorySet:
        self.calls.append("advisory-fallback" if fallback else "advisory")
        refs = (storm.public_advisory, storm.forecast_advisory)
        key = str(max(r.adv_num for r in refs if r is not None and r.adv_num is not None))
        table = self.fallback_texts if fallback else self.texts
        return table.get(key, AdvisorySet())

    async def forecast_gis(self, storm: Storm):
        self.calls.append("forecast_gis")
        if "forecast_gis" in self.fail_products:
            raise FetchError("fake://forecast_gis", "network down")
        return None

    async def radii_gis(self, storm: Storm):
        self.calls.append("radii_gis")
        if "radii_gis" in self.fail_products:
            raise FetchError("fake://radii_gis", "network down")
        return None

    async def track(self, storm: Storm):
        self.calls.append("track")
        if "track" in self.fail_products:
            raise FetchError("fake://track", "network down")
        return None

    async def graphics(self, storm: Storm) -> tuple[GraphicLink, ...]:
        self.calls.append("graphics")
        if "graphics" in self.fail_products:
            raise FetchError("fake://graphics", "network down")
        return ()

    async def satellite(self, storm: Storm) -> tuple[FloaterProduct, ...]:
        self._call("satellite")
        return ()

    async def outlook(self) -> Outlook:
        self._call("outlook")
        return Outlook()

    async def alerts(self) -> AlertsResult:
        self._call("alerts")
        return self.alert_result

    async def ndbc_stations(self) -> tuple[Station, ...]:
        self.calls.append("ndbc_stations")
        return self.stations

    async def ndbc_latest(self) -> tuple[LatestObservation, ...]:
        self._call("ndbc_latest", "buoys")
        return ()

    async def ndbc_series(self, station_id: str) -> ObservationSeries:
        self.calls.append(f"series:{station_id}")
        return self.buoy_series.get(station_id.upper(), ObservationSeries(station_id.upper()))

    async def coops_stations(self) -> tuple[TideStation, ...]:
        self.calls.append("coops_stations")
        return self.tide_stations

    async def coops_series(self, station: TideStation, datum: str) -> TideSeries:
        self.datums.append((station.id, datum))
        if station.id in self.bad_datum:
            raise HttpError("fake://coops/" + station.id, 400)
        return TideSeries(station.id, datum)


def retime(storm: Storm, updated: datetime) -> Storm:
    return replace(storm, last_update=updated)
