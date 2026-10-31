"""Diff successive states into events.

Every function here is pure: it takes the previous and the current value of one thing (the storm list, a storm's
advisories, the outlook, a station's series) plus `now`, and returns the `Event`s that follow. Whether an event is
worth telling the user, and whether it was already told, is decided later by `eyewall.state.alerts`.

Two policies keep a launch quiet:

- Watches and warnings, classification changes and discussions are compared with the previous state, and with none
  (the first load) they produce nothing: what was already in effect when eyewall started is not news.
- Storms, advisories and outlooks are always keyed by their own identity, so the first load reports them once and the
  persisted seen set stops a restart from reporting them again.
- Buoy events look at the series, not at a previous state: a crossing counts when it happened within `CROSSING_WINDOW`
  of now, and silence counts for a station that stopped reporting within `SILENCE_WINDOW`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta

from eyewall.models.advisory import AdvisorySet
from eyewall.models.events import Event, EventKind, Severity, make_key
from eyewall.models.obs import Observation, ObservationSeries
from eyewall.models.outlook import Outlook
from eyewall.models.storm import AdvNum, Classification, Storm
from eyewall.models.watches import WatchWarningArea
from eyewall.palette import WatchWarning
from eyewall.state.trends import SILENT_AFTER
from eyewall.units import convert

THRESHOLDS_KT = (34, 50, 64)
CROSSING_WINDOW = timedelta(hours=3)
SILENCE_WINDOW = timedelta(hours=24)

_WARNING_KINDS = frozenset(
    {WatchWarning.TROPICAL_STORM_WARNING, WatchWarning.HURRICANE_WARNING, WatchWarning.SURGE_WARNING}
)


def current_adv(storm: Storm) -> AdvNum | None:
    """The newest advisory number among the storm's text products.

    An intermediate advisory (31A) is a public advisory only, so the forecast advisory still carries 31; the newest
    number across the products is the one that tells the advisory changed.
    """
    refs = (storm.forecast_advisory, storm.public_advisory, storm.forecast_discussion, storm.wind_speed_probabilities)
    return max((r.adv_num for r in refs if r is not None and r.adv_num is not None), default=None)


def fetched_adv(advisories: AdvisorySet) -> AdvNum | None:
    """The newest advisory number among the products that were fetched."""
    products = (advisories.forecast, advisories.public, advisories.discussion, advisories.wind_probabilities)
    return max((p.adv_num for p in products if p is not None and p.adv_num is not None), default=None)


def missing_products(storm: Storm, advisories: AdvisorySet) -> bool:
    """True when the feed lists a text product that did not come back parsed: tgftp lags one product at a time."""
    pairs = (
        (storm.forecast_advisory, advisories.forecast),
        (storm.public_advisory, advisories.public),
        (storm.forecast_discussion, advisories.discussion),
        (storm.wind_speed_probabilities, advisories.wind_probabilities),
    )
    return any(ref is not None and product is None for ref, product in pairs)


def _label(storm: Storm) -> str:
    return f"{storm.classification_text} {storm.name}".strip() if storm.name else storm.id


def storm_events(prev: Mapping[str, Storm] | None, curr: Mapping[str, Storm], now: datetime) -> list[Event]:
    """New storms (and potential cyclones), new advisories including intermediates, and classification changes."""
    events: list[Event] = []
    for storm_id, storm in curr.items():
        before = None if prev is None else prev.get(storm_id)
        adv = current_adv(storm)
        adv_text = None if adv is None else str(adv)
        if before is None:
            kind = EventKind.NEW_PTC if storm.classification is Classification.PTC else EventKind.NEW_STORM
            what = "potential tropical cyclone" if kind is EventKind.NEW_PTC else "tropical cyclone"
            events.append(
                Event(
                    kind,
                    make_key(kind, storm_id, None),
                    f"{_label(storm)}: new {what}",
                    now,
                    storm_id,
                    severity=Severity.NOTICE,
                )
            )
        if adv is not None and (before is None or current_adv(before) != adv):
            kind = EventKind.NEW_ADVISORY
            wind = "" if storm.intensity_kt is None else f", {storm.intensity_kt} kt"
            events.append(
                Event(
                    kind,
                    make_key(kind, storm_id, adv_text),
                    f"{_label(storm)}: advisory {adv}{wind}",
                    now,
                    storm_id,
                    adv_text,
                )
            )
        if before is not None and before.classification is not storm.classification:
            kind = EventKind.CLASSIFICATION
            subject = f"{before.classification.value}>{storm.classification.value}"
            events.append(
                Event(
                    kind,
                    make_key(kind, storm_id, adv_text, subject),
                    f"{storm.name or storm_id}: {before.classification_text} became {storm.classification_text}",
                    now,
                    storm_id,
                    adv_text,
                    subject,
                    Severity.NOTICE,
                )
            )
    return events


def _blocks(advisories: AdvisorySet | None) -> dict[str, WatchWarningArea] | None:
    """The watch and warning blocks of a public advisory by upper-case label; None without a readable advisory."""
    if advisories is None or advisories.public is None:
        return None
    return {block.label.strip().upper(): block for block in advisories.public.watches_warnings.in_effect}


def _places(block: WatchWarningArea) -> str:
    text = "; ".join(block.areas)
    return text if len(text) <= 120 else text[:117] + "..."


def watch_warning_events(storm: Storm, prev: AdvisorySet | None, curr: AdvisorySet, now: datetime) -> list[Event]:
    """Watches and warnings issued, changed or discontinued between two public advisories of the same storm.

    Blocks are matched by their label because the area text drifts in wording between advisories. Nothing is reported
    when either side is missing.
    """
    before, after = _blocks(prev), _blocks(curr)
    if before is None or after is None or curr.public is None:
        return []
    adv = None if curr.public.adv_num is None else str(curr.public.adv_num)
    name = storm.name or storm.id
    events: list[Event] = []

    def add(kind: EventKind, label: str, block: WatchWarningArea, verb: str) -> None:
        severity = Severity.WARNING if block.kind in _WARNING_KINDS else Severity.NOTICE
        events.append(
            Event(
                kind,
                make_key(kind, storm.id, adv, label),
                f"{name}: {block.label.title()} {verb}: {_places(block)}",
                now,
                storm.id,
                adv,
                label,
                severity,
            )
        )

    for label, block in after.items():
        if label not in before:
            add(EventKind.WATCH_WARNING_ISSUED, label, block, "issued")
        elif set(block.areas) != set(before[label].areas):
            add(EventKind.WATCH_WARNING_CHANGED, label, block, "changed")
    for label, block in before.items():
        if label not in after:
            add(EventKind.WATCH_WARNING_DISCONTINUED, label, block, "discontinued")
    return events


def discussion_events(storm: Storm, prev: AdvisorySet | None, curr: AdvisorySet, now: datetime) -> list[Event]:
    """A new forecast discussion: the discussion's advisory number differs from the previous one's."""
    if prev is None or prev.discussion is None or curr.discussion is None:
        return []
    old, new = prev.discussion.adv_num, curr.discussion.adv_num
    if new is None or new == old:
        return []
    kind = EventKind.NEW_DISCUSSION
    return [
        Event(
            kind,
            make_key(kind, storm.id, str(new)),
            f"{storm.name or storm.id}: new forecast discussion {new}",
            now,
            storm.id,
            str(new),
        )
    ]


def _outlook_issues(outlook: Outlook | None) -> dict[str, datetime]:
    return {
        (text.region or "outlook"): text.issued
        for text in (outlook.texts if outlook else ())
        if text.issued is not None
    }


def invest_ids(outlook: Outlook | None) -> dict[str, str]:
    """The invest id (such as `al912026`) of each invest in an outlook, mapped to its newest name or number."""
    found: dict[str, str] = {}
    for track in outlook.invests if outlook else ():
        latest = track.latest
        if latest is None:
            continue
        found[f"{track.basin_code.lower()}{track.number:02d}{latest.time.year}"] = (
            f"{track.number:02d}{track.basin_code}"
        )
    return found


def outlook_events(prev: Outlook | None, curr: Outlook, now: datetime) -> list[Event]:
    """A newly issued outlook, and a newly appeared invest. With no previous outlook only the issue is reported."""
    events: list[Event] = []
    before = _outlook_issues(prev)
    for region, issued in _outlook_issues(curr).items():
        if before.get(region) != issued:
            kind = EventKind.NEW_OUTLOOK
            stamp = issued.strftime("%Y%m%dT%H%MZ")
            events.append(
                Event(
                    kind,
                    make_key(kind, None, stamp, region),
                    f"New tropical weather outlook ({region}), issued {issued:%d %b %H:%MZ}",
                    now,
                    subject=region,
                )
            )
    if prev is not None:
        known = invest_ids(prev)
        for invest_id, label in invest_ids(curr).items():
            if invest_id not in known:
                kind = EventKind.NEW_INVEST
                events.append(
                    Event(
                        kind,
                        make_key(kind, invest_id, None),
                        f"New invest: {label.upper()}",
                        now,
                        invest_id,
                        subject=label,
                        severity=Severity.NOTICE,
                    )
                )
    return events


def buoy_events(
    storm: Storm,
    station_id: str,
    series: ObservationSeries,
    now: datetime,
    *,
    thresholds: Iterable[int] = THRESHOLDS_KT,
    newest: Observation | None = None,
) -> list[Event]:
    """A nearby buoy's sustained wind crossing 34, 50 or 64 kt lately, and a buoy that has just gone silent.

    Silence is judged from `newest`, the newest report the store holds for the buoy (the series or latest_obs.txt,
    whichever is newer), so a series that stopped refreshing does not make a reporting buoy silent. Without it the
    series' own newest row is used.
    """
    events: list[Event] = []
    peak_kt = 0.0
    when: dict[int, datetime] = {}
    for obs in sorted(series.observations, key=lambda o: o.time):
        if obs.wind_speed_mps is None or now - obs.time > CROSSING_WINDOW or obs.time > now:
            continue
        kt = convert(obs.wind_speed_mps, "mps", "kt")
        peak_kt = max(peak_kt, kt)
        for threshold in thresholds:
            if kt >= threshold:
                when.setdefault(threshold, obs.time)
    for threshold in sorted(when):
        kind = EventKind.BUOY_THRESHOLD
        subject = f"{station_id.upper()}:{threshold}"
        events.append(
            Event(
                kind,
                make_key(kind, storm.id, None, subject),
                f"Buoy {station_id.upper()} near {storm.name or storm.id}: sustained wind reached {threshold} kt "
                f"(peak {peak_kt:.0f} kt)",
                when[threshold],
                storm.id,
                None,
                subject,
                Severity.WARNING if threshold >= 50 else Severity.NOTICE,
            )
        )
    latest = max((o for o in (series.latest, newest) if o is not None), key=lambda o: o.time, default=None)
    age = None if latest is None else max(timedelta(0), now - latest.time)
    if latest is not None and age is not None and age > SILENT_AFTER and age - SILENT_AFTER <= SILENCE_WINDOW:
        kind = EventKind.BUOY_SILENT
        subject = f"{station_id.upper()}:{latest.time:%Y%m%dT%H%MZ}"
        events.append(
            Event(
                kind,
                make_key(kind, storm.id, None, subject),
                f"Buoy {station_id.upper()} near {storm.name or storm.id} stopped reporting "
                f"(last report {latest.time:%d %b %H:%MZ})",
                now,
                storm.id,
                None,
                subject,
                Severity.NOTICE,
            )
        )
    return events
