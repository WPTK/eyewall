"""The store: everything the app knows, in one place, with no I/O.

The poller feeds it with `apply_*` calls; each returns the events the change produced (see `eyewall.state.events`).
Readers (the UI later, the headless runner now) take storms, their products, the outlook, the alerts and the stations
from the attributes and the helper methods. Nothing here fetches, sleeps or reads a clock: `now` is always an argument.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from itertools import pairwise

from eyewall.config import Config
from eyewall.geo import LatLon, interpolate
from eyewall.models.advisory import AdvisorySet
from eyewall.models.events import Event
from eyewall.models.forecast import ForecastGis
from eyewall.models.graphics import FloaterProduct, GraphicLink
from eyewall.models.obs import LatestObservation, Observation, ObservationSeries, Station, TideSeries, TideStation
from eyewall.models.outlook import Outlook
from eyewall.models.storm import AdvNum, CurrentStorms, Storm
from eyewall.models.track import BestTrack
from eyewall.models.watches import AlertsResult, WatchWarningAlert
from eyewall.models.wind import WindRadiiGis
from eyewall.state import events as ev
from eyewall.state.alerts import tropical_alerts
from eyewall.state.nearby import NearbyStation, TrackFix, nearby_stations
from eyewall.state.trends import PressureTendency, pressure_tendency

# A storm is a threat to the United States when its center or a forecast position is inside one of these boxes
# (south, west, north, east): the Atlantic and Gulf coasts with the Caribbean territories, and Hawaii.
US_BOXES = (
    (17.5, -100.0, 46.0, -64.0),
    (18.0, -161.0, 23.0, -154.0),
)
US_NEAR_NM_DEG = 3.0  # slack, in degrees, around the boxes
TENDENCY_MAX_AGE = timedelta(hours=2)


@dataclass(frozen=True, slots=True)
class StormState:
    """One active storm with everything fetched for its current advisory.

    `fetched_key` is the (advisory number, last update) the products were fetched for, so the poller can tell a storm
    whose products are current from one whose advisory just changed.
    """

    storm: Storm
    advisories: AdvisorySet = field(default_factory=AdvisorySet)
    forecast_gis: ForecastGis | None = None
    radii_gis: WindRadiiGis | None = None
    track: BestTrack | None = None
    graphics: tuple[GraphicLink, ...] = ()
    satellite: tuple[FloaterProduct, ...] = ()
    fetched_key: tuple[str | None, datetime | None] | None = None


def storm_key(storm: Storm) -> tuple[str | None, datetime | None]:
    adv = ev.current_adv(storm)
    return (None if adv is None else str(adv), storm.last_update)


def _in_box(lat: float, lon: float) -> bool:
    slack = US_NEAR_NM_DEG
    return any(s - slack <= lat <= n + slack and w - slack <= lon <= e + slack for s, w, n, e in US_BOXES)


class Store:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or Config()
        self.storms: dict[str, StormState] = {}
        self.storms_loaded = False
        self.outlook: Outlook | None = None
        self.alerts: AlertsResult = AlertsResult()
        self.stations: dict[str, Station] = {}
        self.latest: dict[str, LatestObservation] = {}
        self.series: dict[str, ObservationSeries] = {}
        self.tide_stations: tuple[TideStation, ...] = ()
        self.tide_series: dict[str, TideSeries] = {}
        self.tide_errors: dict[str, str] = {}

    # ---- storms -----------------------------------------------------------------------------------------------

    def _enabled(self, storm: Storm) -> bool:
        basin = storm.basin
        return basin is None or basin.value in self.config.basins.enabled

    def apply_storms(self, current: CurrentStorms, now: datetime) -> list[Event]:
        """Take the storm list. A storm that left the list is dropped; a new one starts with no products."""
        fresh = {s.id: s for s in current.storms if self._enabled(s)}
        before = {sid: st.storm for sid, st in self.storms.items()} if self.storms_loaded else None
        events = ev.storm_events(before, fresh, now)
        merged: dict[str, StormState] = {}
        for storm_id, storm in fresh.items():
            old = self.storms.get(storm_id)
            merged[storm_id] = replace(old, storm=storm) if old else StormState(storm)
        self.storms = merged
        self.storms_loaded = True
        return events

    def apply_products(
        self,
        storm_id: str,
        now: datetime,
        *,
        key: tuple[str | None, datetime | None] | None,
        advisories: AdvisorySet | None = None,
        forecast_gis: ForecastGis | None = None,
        radii_gis: WindRadiiGis | None = None,
        track: BestTrack | None = None,
        graphics: tuple[GraphicLink, ...] | None = None,
    ) -> list[Event]:
        """Store what was fetched for the storm's current advisory and return the events its text produced."""
        state = self.storms.get(storm_id)
        if state is None:
            return []
        events: list[Event] = []
        changes: dict[str, object] = {} if key is None else {"fetched_key": key}  # None: tried again next poll
        if advisories is not None:
            stepped_back = _is_older(advisories, state.advisories)
            if stepped_back:
                pass  # the replay stepped back: show that advisory as it was, with no events and nothing newer mixed in
            else:
                advisories = _keep_previous(state.advisories, advisories)
                previous = state.advisories if state.advisories != AdvisorySet() else None
                events += ev.watch_warning_events(state.storm, previous, advisories, now)
                events += ev.discussion_events(state.storm, previous, advisories, now)
            changes["advisories"] = advisories
            # The cone and the wind radii belong to one advisory; never show an older advisory's next to newer text.
            # Judged by base number against the newest product, so a retry that merges in the previous forecast, or an
            # intermediate advisory (GIS 30A beside forecast 30), does not throw away a current cone. A replay that
            # stepped back also drops a cone from a later advisory than the text it now shows.
            newest = ev.fetched_adv(advisories)
            if newest is not None:
                for field_name, gis in (("forecast_gis", state.forecast_gis), ("radii_gis", state.radii_gis)):
                    if gis is not None and (
                        _older(gis.adv_num, newest) or (stepped_back and _newer(gis.adv_num, newest))
                    ):
                        changes[field_name] = None
        if forecast_gis is not None:
            changes["forecast_gis"] = forecast_gis
        if radii_gis is not None:
            changes["radii_gis"] = radii_gis
        if track is not None:
            changes["track"] = track
        if graphics is not None:
            changes["graphics"] = graphics
        self.storms[storm_id] = replace(state, **changes)  # type: ignore[arg-type]
        return events

    def apply_satellite(self, storm_id: str, products: tuple[FloaterProduct, ...]) -> None:
        state = self.storms.get(storm_id)
        if state is not None:
            self.storms[storm_id] = replace(state, satellite=products)

    # ---- outlook and alerts -----------------------------------------------------------------------------------

    def apply_outlook(self, outlook: Outlook, now: datetime) -> list[Event]:
        events = ev.outlook_events(self.outlook, outlook, now)
        self.outlook = outlook
        return events

    def apply_alerts(self, result: AlertsResult) -> None:
        self.alerts = tropical_alerts(result)

    def us_threat(self) -> bool:
        """True while an active storm is at or forecast near US land or has a coastal watch or warning in effect."""
        for state in self.storms.values():
            if self.watches_in_effect(state):
                return True
            for lat, lon in self._path(state):
                if _in_box(lat, lon):
                    return True
        return False

    @staticmethod
    def watches_in_effect(state: StormState) -> bool:
        public = state.advisories.public
        return bool(public and public.watches_warnings.in_effect)

    def _path(self, state: StormState) -> list[LatLon]:
        points: list[LatLon] = []
        storm = state.storm
        if storm.lat is not None and storm.lon is not None:
            points.append((storm.lat, storm.lon))
        points.extend((f.lat, f.lon) for f in track_fixes(state) if f.hours > 0)
        return points

    # ---- stations ---------------------------------------------------------------------------------------------

    def apply_stations(self, stations: tuple[Station, ...]) -> None:
        self.stations = {s.id: s for s in stations}

    def apply_latest(self, latest: tuple[LatestObservation, ...]) -> None:
        self.latest = {item.station_id.upper(): item for item in latest}

    def apply_series(self, series: ObservationSeries) -> None:
        self.series[series.station_id.upper()] = series

    def apply_tide_stations(self, stations: tuple[TideStation, ...]) -> None:
        self.tide_stations = stations

    def apply_tide_series(self, series: TideSeries) -> None:
        self.tide_series[series.station_id] = series
        self.tide_errors.pop(series.station_id, None)

    def apply_tide_error(self, station_id: str, message: str) -> None:
        self.tide_errors[station_id] = message

    def nearby_buoys(self, storm_id: str, now: datetime | None = None) -> list[NearbyStation[Station]]:
        """The buoys near a storm. A station the catalog says has no weather data (DART, currents, a retired buoy) is
        left out unless it is watchlisted or we hold data for it, so it cannot displace a working buoy."""
        wanted = {w.strip().upper() for w in self.config.watchlist.ndbc}
        stations = [
            s
            for s in self.stations.values()
            if s.met is not False
            or s.id.upper() in wanted
            or s.id.upper() in self.series
            or s.id.upper() in self.latest
        ]
        return self._nearby(storm_id, stations, self.config.watchlist.ndbc, now)

    def nearby_tides(self, storm_id: str, now: datetime | None = None) -> list[NearbyStation[TideStation]]:
        return self._nearby(storm_id, self.tide_stations, self.config.watchlist.coops, now)

    def _nearby[S: (Station, TideStation)](
        self, storm_id: str, stations: object, watchlist: tuple[str, ...], now: datetime | None
    ) -> list[NearbyStation[S]]:
        state = self.storms.get(storm_id)
        if state is None or state.storm.lat is None or state.storm.lon is None:
            return []
        center, track = track_from(state, (state.storm.lat, state.storm.lon), now)
        return nearby_stations(
            center,
            track,
            stations,  # type: ignore[arg-type]
            config=self.config.nearby,
            watchlist=watchlist,
        )

    def active_alerts(self, now: datetime) -> tuple[WatchWarningAlert, ...]:
        """The NWS alerts not yet over: an alert past its end (or expiry) is dropped, as the store may hold the last
        answer from a failed poll or a cached copy for hours."""
        return tuple(a for a in self.alerts.alerts if (end := a.ends or a.expires) is None or end > now)

    def newest_observation(self, station_id: str) -> Observation | None:
        """The newest row for a buoy: the polled series or its row in latest_obs.txt, whichever is newer. A series stops
        refreshing once nothing asks for the buoy, while latest_obs is read on every poll."""
        series = self.series.get(station_id.upper())
        latest = self.latest.get(station_id.upper())
        rows = [
            o for o in (None if series is None else series.latest, None if latest is None else latest.observation) if o
        ]
        return max(rows, key=lambda o: o.time, default=None)

    def buoy_events(self, now: datetime) -> list[Event]:
        """Threshold crossings and silences at each storm's nearby buoys, from the series fetched so far."""
        events: list[Event] = []
        for storm_id, state in self.storms.items():
            for entry in self.nearby_buoys(storm_id, now):
                series = self.series.get(entry.station.id.upper())
                if series is not None:
                    newest = self.newest_observation(entry.station.id)
                    events += ev.buoy_events(state.storm, entry.station.id, series, now, newest=newest)
        return events

    def tendency(self, station_id: str, now: datetime) -> PressureTendency | None:
        """The 3 hour pressure change at a station, or None when there is no data or the station has gone quiet.

        `trends.pressure_tendency` does not look at how old its reading is, so the check lives here, on the same reading
        it uses: the newest row that has a pressure, not the newest row of any kind.
        """
        series = self.series.get(station_id.upper())
        if series is None:
            return None
        tendency = pressure_tendency(series.observations)
        times = [o.time for o in series.observations if o.pressure_hpa is not None]
        if tendency is None or not times:
            return None
        if max(timedelta(0), now - max(times)) > TENDENCY_MAX_AGE:
            return None
        return tendency


def _is_older(new: AdvisorySet, old: AdvisorySet) -> bool:
    """True when a product in both sets was issued earlier in the new one, which only happens when a replay steps back.

    A partial refetch (one product missing) or a set whose newest product predates a stored intermediate advisory
    has no such product pair, so it keeps the usual merge.
    """
    earlier = later = False
    for fresh, stored in (
        (new.forecast, old.forecast),
        (new.public, old.public),
        (new.discussion, old.discussion),
        (new.wind_probabilities, old.wind_probabilities),
    ):
        if fresh is None or stored is None or fresh.issued is None or stored.issued is None:
            continue
        earlier |= fresh.issued < stored.issued
        later |= fresh.issued > stored.issued
    return earlier and not later


def _older(adv_num: AdvNum | None, newest: AdvNum) -> bool:
    """True when a product's advisory number is from an earlier advisory than `newest`; the suffix does not count."""
    return adv_num is not None and adv_num.number < newest.number


def _newer(adv_num: AdvNum | None, newest: AdvNum) -> bool:
    return adv_num is not None and adv_num.number > newest.number


def _keep_previous(old: AdvisorySet, new: AdvisorySet) -> AdvisorySet:
    """A product that did not come back (tgftp lags one at a time) keeps the previous one instead of wiping it."""
    return AdvisorySet(
        forecast=new.forecast or old.forecast,
        public=new.public or old.public,
        discussion=new.discussion or old.discussion,
        wind_probabilities=new.wind_probabilities or old.wind_probabilities,
    )


def track_fixes(state: StormState, now: datetime | None = None) -> list[TrackFix]:
    """The forecast positions as `TrackFix`es with hours counted from the storm's current center.

    The TCM counts hours from the synoptic time, three hours before the advisory, while the center is the position at
    the advisory time, so each fix is placed by its valid time instead. The GIS points are the fallback.

    With `now`, hours count from now and fixes already past are dropped, so the hours to a station's closest approach
    shrink between advisories. Without it they count from the advisory (enough to ask whether any fix lies ahead).
    """
    storm = state.storm
    tcm = state.advisories.forecast
    if tcm is not None:
        origin = now or tcm.issued
        return [
            TrackFix((fix.valid - origin).total_seconds() / 3600.0, fix.lat, fix.lon)
            for fix in tcm.fixes
            if fix.lat is not None and fix.lon is not None and fix.valid > origin
        ]
    if state.forecast_gis is not None and storm.last_update is not None:
        origin = now or storm.last_update
        return [
            TrackFix((p.valid - origin).total_seconds() / 3600.0, p.lat, p.lon)
            for p in state.forecast_gis.points
            if p.valid is not None and p.valid > origin
        ]
    return []


def track_from(state: StormState, center: LatLon, now: datetime | None) -> tuple[LatLon, list[TrackFix]]:
    """Where the storm is at `now` and the forecast fixes still ahead of it, hours counted from now.

    The center is the position at the storm's last update. Once `now` is later, the storm is placed by interpolating
    along the center and the fixes already passed, so the path from here on does not cut across the real track.
    When every fix is past the storm sits at the last one with nothing ahead (an ETA of 0, not a dropped station).
    Without `now` the center and `track_fixes(state)` are returned unchanged.
    """
    ahead = track_fixes(state, now)
    if now is None:
        return center, ahead
    tcm = state.advisories.forecast
    if tcm is not None:
        # The center is the feed's position, valid at its last update, which can be later than the TCM that is held.
        origin = max(tcm.issued, state.storm.last_update or tcm.issued)
        stamped = [(f.valid, (f.lat, f.lon)) for f in tcm.fixes if f.lat is not None and f.lon is not None]
    elif state.forecast_gis is not None and state.storm.last_update is not None:
        origin = state.storm.last_update
        stamped = [(p.valid, (p.lat, p.lon)) for p in state.forecast_gis.points if p.valid is not None]
    else:
        return center, ahead
    anchors = [(origin, center), *sorted((t, pos) for t, pos in stamped if t > origin)]
    if now <= origin:
        return center, ahead
    for (t0, p0), (t1, p1) in pairwise(anchors):
        if t0 <= now < t1:
            return interpolate(p0, p1, (now - t0) / (t1 - t0)), ahead
    return anchors[-1][1], ahead
