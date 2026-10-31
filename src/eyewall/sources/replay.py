"""The replay data source: a recorded storm served on a virtual clock.

At moment T the source builds what NOAA would have served then: CurrentStorms from the newest advisory products issued
at or before T, the best track up to T, and each buoy's and gauge's rows up to T. Nothing after T leaks out, so
stepping the clock back to an earlier advisory shows exactly what was known at that time.

The bundle format is described in `eyewall.sources.bundle`.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path

from eyewall.clock import VirtualClock
from eyewall.coops.data import parse_air_pressure, parse_predictions, parse_water_level, parse_wind
from eyewall.coops.stations import merge_tide_stations, parse_tide_stations
from eyewall.models.advisory import AdvisorySet, Discussion, PublicAdvisory
from eyewall.models.forecast import ForecastAdvisory, ForecastGis
from eyewall.models.graphics import FloaterProduct, GraphicKind, GraphicLink
from eyewall.models.obs import (
    LatestObservation,
    ObservationSeries,
    Parsed,
    Prediction,
    Station,
    SupplementalReading,
    TideSeries,
    TideStation,
)
from eyewall.models.outlook import Outlook
from eyewall.models.storm import AdvNum, Classification, CurrentStorms, GisRef, ProductRef, Storm
from eyewall.models.track import BestTrack
from eyewall.models.watches import AlertsResult
from eyewall.models.wind import WindProbabilities, WindRadiiGis
from eyewall.ndbc.stations import parse_stations
from eyewall.ndbc.stdmet import parse_stdmet
from eyewall.providers.base import ParseError
from eyewall.providers.nhc import ids
from eyewall.providers.nhc.atcf import parse_bdeck
from eyewall.providers.nhc.gis import parse_forecast_zip, parse_radii_zip
from eyewall.providers.nhc.tcm import parse_tcm
from eyewall.providers.nhc.text import parse_pws, parse_tcd, parse_tcp
from eyewall.render.images import ImageError, check_image_bytes
from eyewall.sources import bundle
from eyewall.sources.bundle import BundleError

MPH_PER_KT = 1.15078
# A storm stays on the list this long after its last recorded advisory, as it would while NHC wrote the next one.
LINGER = timedelta(hours=6)
SERIES_WINDOW = timedelta(days=5)
LATEST_WINDOW = timedelta(hours=2)
TIDE_WINDOW = timedelta(days=3)
PREDICTION_AHEAD = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class _Product[P]:
    """One recorded text product and when it was issued."""

    issued: datetime
    adv: AdvNum
    value: P


def _classification(kind: str) -> Classification:
    upper = kind.upper()
    if "POTENTIAL" in upper:
        return Classification.PTC
    if "POST-TROP" in upper or "REMNANT" in upper:
        return Classification.PC
    if "SUBTROPICAL" in upper:
        return Classification.STS if "STORM" in upper else Classification.STD
    if "HURRICANE" in upper:
        return Classification.HU
    if "STORM" in upper:
        return Classification.TS
    if "DEPRESSION" in upper:
        return Classification.TD
    return Classification.UNKNOWN


class ReplaySource:
    """`DataSource` over a recorded bundle. `clock` is the virtual clock the whole app shares during a replay."""

    name = "replay"

    def __init__(self, directory: Path, clock: VirtualClock | None = None) -> None:
        self.directory = directory
        self.manifest = bundle.read_manifest(directory)
        self.clock = clock if clock is not None else VirtualClock(self.manifest.start)
        self._tcm: list[_Product[ForecastAdvisory]] = []
        self._tcp: list[_Product[PublicAdvisory]] = []
        self._tcd: list[_Product[Discussion]] = []
        self._pws: list[_Product[WindProbabilities]] = []
        try:
            self._load_text()
            self._gis_issued = self._index_gis()
            self._best_track = self._load_best_track()
            self._stations = self._load_stations()
            self._series: dict[str, ObservationSeries] = {}
            self._forecast_cache: dict[str, ForecastGis] = {}
            self._radii_cache: dict[str, WindRadiiGis] = {}
            self._tide_stations = self._load_tide_stations()
        except BundleError:
            raise
        except (ValueError, KeyError, TypeError, AttributeError, OSError) as exc:
            raise BundleError(f"{directory}: the recording could not be read ({exc})") from exc

    # ---- loading ----------------------------------------------------------------------------------------------

    def _read(self, relative: str) -> bytes | None:
        """A file of the bundle, or None when it is missing. A name from the bundle's own listings (a tide station id)
        that climbs out of the folder is refused, not read."""
        try:
            path = (self.directory / relative).resolve()
            if not path.is_relative_to(self.directory.resolve()):
                return None
            return path.read_bytes()
        except (OSError, ValueError):
            return None

    def _load_text(self) -> None:
        folder = self.directory / "nhc" / self.manifest.storm_id
        if not folder.is_dir():
            raise BundleError(f"{self.directory}: no advisories under nhc/{self.manifest.storm_id}")
        for path in sorted(folder.glob("*.txt")):
            label, _, rest = path.name.partition(".")
            kind = rest.removesuffix(".txt")
            adv = ids.parse_adv_num(label)
            if adv is None:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            try:
                if kind == "tcm":
                    tcm = parse_tcm(text)
                    self._tcm.append(_Product(tcm.issued, adv, tcm))
                elif kind == "tcp":
                    tcp = parse_tcp(text)
                    if tcp.issued is not None:
                        self._tcp.append(_Product(tcp.issued, adv, tcp))
                elif kind == "tcd":
                    tcd = parse_tcd(text)
                    if tcd.issued is not None:
                        self._tcd.append(_Product(tcd.issued, adv, tcd))
                elif kind == "pws":
                    pws = parse_pws(text)
                    if pws.issued is not None:
                        self._pws.append(_Product(pws.issued, adv, pws))
            except (ParseError, ValueError):
                continue
        for products in (self._tcm, self._tcp, self._tcd, self._pws):
            products.sort(key=lambda p: (p.issued, p.adv))
        if not self._tcm and not self._tcp:
            raise BundleError(f"{self.directory}: no readable advisories")

    def _index_gis(self) -> dict[str, datetime]:
        """The moment each GIS advisory label became available: when the advisory with that number was issued."""
        issued: dict[str, datetime] = {}
        for product in (*self._tcm, *self._tcp):
            issued.setdefault(ids.format_adv_num(product.adv), product.issued)
        folder = self.directory / "gis" / self.manifest.storm_id
        found: dict[str, datetime] = {}
        if folder.is_dir():
            for path in folder.glob("*_5day.zip"):
                label = path.name.removesuffix("_5day.zip")
                if label in issued:
                    found[label] = issued[label]
        return found

    def _load_best_track(self) -> BestTrack | None:
        body = self._read(bundle.bdeck_path(self.manifest.storm_id))
        if body is None:
            return None
        try:
            return parse_bdeck(body)
        except ParseError:
            return None

    def _load_stations(self) -> dict[str, Station]:
        body = self._read(bundle.STATIONS_XML)
        return {s.id: s for s in parse_stations(body).items} if body else {}

    def _load_tide_stations(self) -> tuple[TideStation, ...]:
        listings = []
        for listing in bundle.TIDE_LISTINGS:
            body = self._read(bundle.coops_listing_path(listing))
            if body:
                listings.append(parse_tide_stations(body, listing))
        return merge_tide_stations(listings)

    # ---- the transport the app drives -------------------------------------------------------------------------

    def now(self) -> datetime:
        return self.clock.now()

    def stale(self, feed: str) -> bool:
        return False

    def start_poll(self, feed: str) -> None:
        return None

    def advisory_times(self) -> tuple[datetime, ...]:
        """Every moment an advisory (including intermediates) was issued, oldest first."""
        return tuple(sorted({p.issued for p in (*self._tcm, *self._tcp)}))

    def step_advisory(self, direction: int) -> datetime | None:
        """Move the clock to the next (direction > 0) or previous advisory. None when there is none that way."""
        times = self.advisory_times()
        now = self.clock.now()
        if direction > 0:
            index = bisect.bisect_right(times, now)
            target = times[index] if index < len(times) else None
        else:
            index = bisect.bisect_left(times, now) - 1
            target = times[index] if index >= 0 else None
        if target is not None:
            self.clock.set(target)
        return target

    # ---- storms -----------------------------------------------------------------------------------------------

    @staticmethod
    def _latest[P](products: list[_Product[P]], moment: datetime) -> _Product[P] | None:
        found = [p for p in products if p.issued <= moment]
        return found[-1] if found else None

    def _ref(self, product: _Product[object] | None, kind: str) -> ProductRef | None:
        if product is None:
            return None
        url = f"replay:{bundle.text_path(self.manifest.storm_id, ids.format_adv_num(product.adv), kind)}"
        return ProductRef(product.adv, product.issued, product.issued, url)

    def _gis_ref(self, moment: datetime, layer: str) -> GisRef | None:
        available = [
            (issued, label)
            for label, issued in self._gis_issued.items()
            if issued <= moment and (self.directory / bundle.gis_path(self.manifest.storm_id, label, layer)).exists()
        ]
        if not available:
            return None
        issued, label = max(available)
        adv = ids.parse_adv_num(label)
        return GisRef(adv, issued, issued, f"replay:{bundle.gis_path(self.manifest.storm_id, label, layer)}")

    def _storm(self, moment: datetime) -> Storm | None:
        tcm = self._latest(self._tcm, moment)
        tcp = self._latest(self._tcp, moment)
        tcd = self._latest(self._tcd, moment)
        pws = self._latest(self._pws, moment)
        stamps = [p.issued for p in (tcm, tcp, tcd, pws) if p is not None]
        if not stamps or moment > max(stamps) + LINGER:
            return None
        base = tcm.value if tcm else None
        lat = base.lat if base else None
        lon = base.lon if base else None
        wind_kt = base.max_wind_kt if base else None
        pressure = base.pressure_mb if base else None
        direction = base.movement_dir_deg if base else None
        speed_mph = round(base.movement_speed_kt * MPH_PER_KT, 1) if base and base.movement_speed_kt else None
        classification = _classification(base.kind) if base else Classification.UNKNOWN
        if tcp is not None and (tcm is None or tcp.issued > tcm.issued):
            summary = tcp.value.summary
            lat, lon = summary.lat or lat, summary.lon or lon
            if summary.max_wind_mph is not None:
                wind_kt = round(summary.max_wind_mph / MPH_PER_KT)
            pressure = summary.pressure_mb or pressure
            direction = summary.movement_dir_deg if summary.movement_dir_deg is not None else direction
            speed_mph = summary.movement_speed_mph if summary.movement_speed_mph is not None else speed_mph
        forecast_zip = self._gis_ref(moment, "5day")
        radii_zip = self._gis_ref(moment, "fcst")
        return Storm(
            id=self.manifest.storm_id,
            bin_number=self.manifest.bin,
            name=self.manifest.storm_name,
            classification=classification,
            classification_text=classification.value,
            intensity_kt=wind_kt,
            pressure_mb=pressure,
            lat=lat,
            lon=lon,
            movement_dir_deg=direction,
            movement_speed_mph=speed_mph,
            last_update=max(stamps),
            public_advisory=self._ref(tcp, "tcp"),
            forecast_advisory=self._ref(tcm, "tcm"),
            wind_speed_probabilities=self._ref(pws, "pws"),
            forecast_discussion=self._ref(tcd, "tcd"),
            forecast_track=forecast_zip,
            track_cone=forecast_zip,
            wind_watches_warnings=forecast_zip,
            initial_wind_extent=radii_zip,
            forecast_wind_radii=radii_zip,
        )

    async def storms(self) -> CurrentStorms:
        storm = self._storm(self.clock.now())
        return CurrentStorms((storm,) if storm else ())

    async def advisory(self, storm: Storm, *, fallback: bool = False) -> AdvisorySet:
        def pick[P](products: list[_Product[P]], ref: ProductRef | None) -> P | None:
            if ref is None or ref.adv_num is None:
                return None
            return next((p.value for p in products if p.adv == ref.adv_num), None)

        return AdvisorySet(
            forecast=pick(self._tcm, storm.forecast_advisory),
            public=pick(self._tcp, storm.public_advisory),
            discussion=pick(self._tcd, storm.forecast_discussion),
            wind_probabilities=pick(self._pws, storm.wind_speed_probabilities),
        )

    def _zip(self, ref: GisRef | None, layer: str) -> bytes | None:
        if ref is None or ref.adv_num is None:
            return None
        return self._read(bundle.gis_path(self.manifest.storm_id, ids.format_adv_num(ref.adv_num), layer))

    async def forecast_gis(self, storm: Storm) -> ForecastGis | None:
        ref = storm.forecast_track
        if ref is None or ref.adv_num is None:
            return None
        label = ids.format_adv_num(ref.adv_num)
        if label not in self._forecast_cache:
            body = self._zip(ref, "5day")
            if body is None:
                return None
            try:
                self._forecast_cache[label] = parse_forecast_zip(body)
            except ParseError:
                return None
        return self._forecast_cache[label]

    async def radii_gis(self, storm: Storm) -> WindRadiiGis | None:
        ref = storm.forecast_wind_radii
        if ref is None or ref.adv_num is None:
            return None
        label = ids.format_adv_num(ref.adv_num)
        if label not in self._radii_cache:
            body = self._zip(ref, "fcst")
            if body is None:
                return None
            try:
                self._radii_cache[label] = parse_radii_zip(body)
            except ParseError:
                return None
        return self._radii_cache[label]

    async def track(self, storm: Storm) -> BestTrack | None:
        if self._best_track is None:
            return None
        now = self.clock.now()
        return replace(self._best_track, fixes=tuple(f for f in self._best_track.fixes if f.time <= now))

    async def graphics(self, storm: Storm) -> tuple[GraphicLink, ...]:
        now = self.clock.now()
        newest: dict[str, tuple[datetime, GraphicLink]] = {}
        for entry in self.manifest.graphics:
            adv = ids.parse_adv_num(entry.adv)
            issued = self._gis_issued.get(entry.adv)
            if adv is None or issued is None or issued > now:
                continue
            try:
                kind = GraphicKind(entry.kind)
            except ValueError:
                kind = GraphicKind.OTHER
            link = GraphicLink(
                kind=kind,
                product=entry.product,
                url=f"replay:graphics/{entry.file}",
                media=entry.file.rpartition(".")[2].lower(),
                adv_num=adv,
            )
            if entry.kind not in newest or newest[entry.kind][0] < issued:
                newest[entry.kind] = (issued, link)
        return tuple(link for _, link in newest.values())

    async def satellite(self, storm: Storm) -> tuple[FloaterProduct, ...]:
        return ()

    async def satellite_product(self, storm: Storm, product: str) -> FloaterProduct | None:
        return None

    async def image(self, url: str) -> bytes:
        """A still the bundle recorded, named by a `replay:graphics/<file>` link."""
        relative = url.removeprefix("replay:")
        path = (self.directory / relative).resolve()
        if not url.startswith("replay:graphics/") or not path.is_relative_to((self.directory / "graphics").resolve()):
            raise ImageError(f"{url}: not an image in this recording")
        try:
            return check_image_bytes(url, path.read_bytes())
        except OSError as exc:
            raise ImageError(f"{url}: {exc.strerror or exc}") from exc

    async def outlook(self) -> Outlook:
        return Outlook()

    async def alerts(self) -> AlertsResult:
        return AlertsResult()

    # ---- buoys ------------------------------------------------------------------------------------------------

    async def ndbc_stations(self) -> tuple[Station, ...]:
        return tuple(self._stations.values())

    def _full_series(self, station_id: str) -> ObservationSeries:
        key = station_id.upper()
        if key not in self._series:
            body = self._read(bundle.ndbc_path(key))
            text = body.decode("utf-8", errors="replace") if body else ""
            self._series[key] = parse_stdmet(text, key) if body else ObservationSeries(key)
        return self._series[key]

    async def ndbc_series(self, station_id: str) -> ObservationSeries:
        full = self._full_series(station_id)
        now = self.clock.now()
        rows = tuple(o for o in full.observations if now - SERIES_WINDOW <= o.time <= now)
        return ObservationSeries(full.station_id, rows, full.skipped)

    async def ndbc_latest(self) -> tuple[LatestObservation, ...]:
        now = self.clock.now()
        found: list[LatestObservation] = []
        for station_id, station in self._stations.items():
            newest = next((o for o in self._full_series(station_id).observations if o.time <= now), None)
            if newest is not None and now - newest.time <= LATEST_WINDOW:
                found.append(LatestObservation(station_id, station.lat, station.lon, newest))
        return tuple(found)

    # ---- tide gauges ------------------------------------------------------------------------------------------

    async def ndbc_supplemental(self, station_id: str) -> Parsed[SupplementalReading]:
        """The bundle keeps no `.supl` files; the buoy detail then falls back to the regular rows for its extremes."""
        return Parsed(message="The recording has no supplemental file.")

    async def coops_stations(self) -> tuple[TideStation, ...]:
        return self._tide_stations

    async def coops_series(self, station: TideStation, datum: str) -> TideSeries:
        now = self.clock.now()

        def window[T](parsed: Parsed[T]) -> Parsed[T]:
            kept = tuple(i for i in parsed.items if now - TIDE_WINDOW <= i.time <= now)  # type: ignore[attr-defined]
            return replace(parsed, items=kept)

        level_body = self._read(bundle.coops_path(station.id, "water_level"))
        wind_body = self._read(bundle.coops_path(station.id, "wind"))
        pressure_body = self._read(bundle.coops_path(station.id, "air_pressure"))
        prediction_body = self._read(bundle.coops_path(station.id, "predictions"))
        predictions: Parsed[Prediction] = Parsed(message="not recorded")
        if prediction_body:  # a prediction is a table, so the live source serves the hours ahead as well
            parsed = parse_predictions(prediction_body)
            kept = tuple(p for p in parsed.items if now - TIDE_WINDOW <= p.time <= now + PREDICTION_AHEAD)
            predictions = replace(parsed, items=kept)
        return TideSeries(
            station.id,
            datum,
            window(parse_water_level(level_body)) if level_body else Parsed(message="not recorded"),
            window(parse_wind(wind_body)) if wind_body else Parsed(message="not recorded"),
            window(parse_air_pressure(pressure_body)) if pressure_body else Parsed(message="not recorded"),
            predictions,
        )
