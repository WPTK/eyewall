"""Sentences about storms: where it is, what is in effect, how big it is, what the forecast does.

Every function takes a `StormState` (or the store) and a `units.Preset`, and returns `Words` whose sources are dotted
paths from the object passed in. A public advisory or forecast advisory is read only when its number matches the
feed's (the guard `Storm.adv_num` makes possible); otherwise the sentence falls back to the feed's own fields.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime, tzinfo

from eyewall.clock import ensure_utc
from eyewall.geo import compass_point
from eyewall.models.advisory import PublicAdvisory
from eyewall.models.forecast import ForecastAdvisory, ForecastFix
from eyewall.models.storm import Classification, Storm
from eyewall.models.watches import WatchWarningArea
from eyewall.palette import Category, WatchWarning, category_for_knots
from eyewall.state.store import StormState
from eyewall.ui.format import BASIN_NAMES, advisory_age, collapse
from eyewall.ui.products import TCM_OUTLOOK_NOTE, fmt_lat, fmt_lon
from eyewall.ui.words import Words, distance_text, wind_text
from eyewall.ui.words.about import parse_abouts
from eyewall.ui.words.glossary import MEANINGS, hazard_of, level_of, quoted_meanings
from eyewall.units import LABELS, Preset, convert

_KINDS = {
    Classification.HU: "Hurricane",
    Classification.TY: "Typhoon",
    Classification.TS: "Tropical Storm",
    Classification.TD: "Tropical Depression",
    Classification.STS: "Subtropical Storm",
    Classification.STD: "Subtropical Depression",
    Classification.PTC: "Potential Tropical Cyclone",
    Classification.PC: "Post-Tropical Cyclone",
}
_HURRICANE_CATEGORIES = {Category.H1: 1, Category.H2: 2, Category.H3: 3, Category.H4: 4, Category.H5: 5}
_STATUS = {
    "POST-TROPICAL": "post-tropical",
    "POST-TROP/EXTRATROP": "post-tropical",
    "POST-TROP/REMNT LOW": "remnant low",
    "REMNANT LOW": "remnant low",
    "EXTRATROPICAL": "extratropical",
}
_BASE = "state.advisories"
_SEVERITY = (
    ("hurricane", "warning"),
    ("hurricane", "watch"),
    ("tropical storm", "warning"),
    ("tropical storm", "watch"),
    ("storm surge", "warning"),
    ("storm surge", "watch"),
)
_THRESHOLDS = {34: {"mph": 39, "kmh": 63}, 64: {"mph": 74, "kmh": 119}}  # NHC's own figures for 34 and 64 kt
_PLURALS = {"warning": "warnings", "watch": "watches"}
_HOLD_KT = 5  # a change this small is "holding"
_NEARLY_STATIONARY_MPH = 1.0


# ----------------------------------------------------------------------------------------------------- the advisories


def current_public(state: StormState) -> PublicAdvisory | None:
    """The public advisory, when it is the one the feed lists; an older or newer copy is not trusted."""
    public, ref = state.advisories.public, state.storm.public_advisory
    if public is None:
        return None
    if ref is None or ref.adv_num is None or public.adv_num is None or ref.adv_num == public.adv_num:
        return public
    return None


def current_forecast(state: StormState) -> ForecastAdvisory | None:
    """The forecast advisory (TCM), when its number matches the feed's."""
    tcm, number = state.advisories.forecast, state.storm.adv_num
    if tcm is None:
        return None
    return tcm if number is None or tcm.adv_num is None or tcm.adv_num == number else None


# ------------------------------------------------------------------------------------------------------------- names


def storm_kind(storm: Storm) -> str:
    """`Hurricane`, `Tropical Storm` and so on, from the feed's classification."""
    return _KINDS.get(storm.classification) or (storm.classification_text or "Storm").title()


def hurricane_category(storm: Storm) -> int | None:
    """1 to 5 for a hurricane or typhoon, from the feed's wind through the Saffir-Simpson scale; else None."""
    if storm.classification not in (Classification.HU, Classification.TY):
        return None
    category = category_for_knots(storm.intensity_kt)
    return None if category is None else _HURRICANE_CATEGORIES.get(category)


def short_label(storm: Storm) -> str:
    """`Cat 4` for a hurricane, else the kind in lower case (`tropical storm`)."""
    category = hurricane_category(storm)
    return f"Cat {category}" if category else storm_kind(storm).lower()


def _name(storm: Storm) -> str:
    return f"{storm_kind(storm)} {storm.name}".strip()


def _category_word(kt: float | None) -> str:
    category = category_for_knots(kt)
    if category in _HURRICANE_CATEGORIES:
        return f"Category {_HURRICANE_CATEGORIES[category]}"
    return "tropical storm" if category is Category.TS else "tropical depression" if category is Category.TD else ""


# ----------------------------------------------------------------------------------------------------------- the lead


def _movement(state: StormState, preset: Preset) -> tuple[str, list[str]] | None:
    storm, public = state.storm, current_public(state)
    sources: list[str]
    if (
        public is not None
        and public.summary.movement_dir_deg is not None
        and public.summary.movement_speed_mph is not None
    ):
        degrees, mph = public.summary.movement_dir_deg, float(public.summary.movement_speed_mph)
        sources = [f"{_BASE}.public.summary.movement_dir_deg", f"{_BASE}.public.summary.movement_speed_mph"]
    elif storm.movement_dir_deg is not None and storm.movement_speed_mph is not None:
        degrees, mph = storm.movement_dir_deg, storm.movement_speed_mph
        sources = ["state.storm.movement_dir_deg", "state.storm.movement_speed_mph"]
    else:
        return None
    if mph < _NEARLY_STATIONARY_MPH:
        return "nearly stationary", sources
    tcm = current_forecast(state)
    kt = tcm.movement_speed_kt if tcm is not None else None  # NHC's own knots, which its km/h are worked from
    if kt is not None:
        sources.append(f"{_BASE}.forecast.movement_speed_kt")
    if preset.wind == "mph":
        speed = f"{round(mph)} mph"
    elif kt is not None:
        speed = f"{round(convert(kt, 'kt', preset.wind))} {LABELS[preset.wind]}"
    else:
        speed = f"{round(convert(mph, 'mph', preset.wind))} {LABELS[preset.wind]}"
    return f"moving {compass_point(degrees)} at {speed}", sources


def storm_lead(state: StormState, preset: Preset) -> Words:
    """`Hurricane Erin, Category 4, is about 695 mi SW of Bermuda and moving NW at 10 mph.`"""
    storm = state.storm
    sources = ["state.storm.classification", "state.storm.name"]
    head = _name(storm)
    category = hurricane_category(storm)
    if category:
        head += f", Category {category},"
        sources.append("state.storm.intensity_kt")
    clauses: list[str] = []
    public = current_public(state)
    abouts = parse_abouts(public.summary.about)[:2] if public is not None else []
    if abouts:
        places = [f"{distance_text(preset, mi=a.miles, km=a.km)} {a.direction} of {a.place}" for _, a in abouts]
        clauses.append("about " + " and ".join(places))
        sources += [f"{_BASE}.public.summary.about[{index}]" for index, _ in abouts]
    elif storm.lat is not None and storm.lon is not None:
        clauses.append(f"at {fmt_lat(storm.lat)} {fmt_lon(storm.lon)}")
        sources += ["state.storm.lat", "state.storm.lon"]
    moving = _movement(state, preset)
    if moving is not None:
        clauses.append(moving[0])
        sources += moving[1]
    text = f"{head} is {' and '.join(clauses)}." if clauses else f"{head}."
    return Words(text.replace(",,", ","), tuple(sources))


def storm_wind(state: StormState, preset: Preset, *, with_knots: bool = False) -> Words | None:
    """`Maximum sustained winds are 140 mph.` With `with_knots`, knots follow in brackets."""
    storm, public = state.storm, current_public(state)
    mph = public.summary.max_wind_mph if public is not None else None
    kt = storm.intensity_kt
    if kt is None:
        tcm = current_forecast(state)
        kt = tcm.max_wind_kt if tcm is not None else None
    sources = []
    if preset.wind == "mph" and mph is not None:
        sources.append(f"{_BASE}.public.summary.max_wind_mph")
    elif kt is not None:
        sources.append("state.storm.intensity_kt")
    elif mph is not None:
        sources.append(f"{_BASE}.public.summary.max_wind_mph")
    text = wind_text(preset, kt=kt, mph=mph if preset.wind == "mph" or kt is None else None)
    if text is None:
        return None
    if with_knots and preset.wind != "kt" and kt is not None:
        text += f" ({round(kt)} kt)"
    return Words(f"Maximum sustained winds are {text}.", tuple(sources))


def updated(storm: Storm, now: datetime) -> Words:
    """`Updated 2h07m ago.`"""
    age, _old = advisory_age(storm, now)
    if storm.last_update is None:
        return Words("No advisory time is known yet.", ("state.storm.last_update",))
    return Words(f"Updated {age} ago.", ("state.storm.last_update",))


def next_advisory(state: StormState) -> Words | None:
    """The next advisory time, as NHC wrote it (`Next intermediate advisory at 200 PM EDT.`)."""
    public = current_public(state)
    if public is None or not public.next_advisory.strip():
        return None
    return Words(collapse(public.next_advisory), (f"{_BASE}.public.next_advisory",))


# -------------------------------------------------------------------------------------------------------- all storms


def _joined(names: Sequence[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _level(state: StormState) -> str | None:
    """`warning` when the storm has any warning in effect, else `watch` when it has a watch, else None."""
    public = current_public(state)
    levels = set() if public is None else {_area_level(a) for a in public.watches_warnings.in_effect if a.areas}
    return "warning" if "warning" in levels else "watch" if "watch" in levels else None


def several_storms(states: Sequence[StormState]) -> Words:
    """`2 storms: Erin (Cat 4) and Fernand (tropical storm). Erin has warnings in effect.`"""
    labels = [f"{s.storm.name} ({short_label(s.storm)})" for s in states]
    sources = [f"states[{i}].storm.name" for i in range(len(states))]
    text = f"{len(states)} storms: {_joined(labels)}."
    for level in ("warning", "watch"):
        picked = [(i, s.storm.name) for i, s in enumerate(states) if _level(s) == level]
        if picked:
            verb = "has" if len(picked) == 1 else "have"
            text += f" {_joined([name for _, name in picked])} {verb} {_PLURALS[level]} in effect."
            sources += [f"states[{i}].advisories.public.watches_warnings.in_effect" for i, _ in picked]
    return Words(text, tuple(sources))


def nothing_active(enabled: Iterable[str]) -> Words:
    """`No tropical storms in the Atlantic right now.`"""
    names = [BASIN_NAMES[b] for b in enabled if b in BASIN_NAMES]
    where = _joined(names) if names else "watched basins"
    return Words(f"No tropical storms in the {where} right now.", ("config.basins.enabled",))


# ---------------------------------------------------------------------------------------------- watches and warnings


def _area_hazard(area: WatchWarningArea) -> str | None:
    by_kind = {
        WatchWarning.HURRICANE_WARNING: "hurricane",
        WatchWarning.HURRICANE_WATCH: "hurricane",
        WatchWarning.TROPICAL_STORM_WARNING: "tropical storm",
        WatchWarning.TROPICAL_STORM_WATCH: "tropical storm",
        WatchWarning.SURGE_WARNING: "storm surge",
        WatchWarning.SURGE_WATCH: "storm surge",
    }
    return by_kind.get(area.kind) if area.kind is not None else hazard_of(area.label)


def _area_level(area: WatchWarningArea) -> str | None:
    if area.kind is not None:
        return "warning" if area.kind.value in ("TWR", "HWR", "SURGE_WARNING") else "watch"
    return level_of(area.label)


def warning_sentences(state: StormState) -> list[Words]:
    """One sentence per watch or warning in effect, most serious first.

    `Tropical storm conditions are expected in Turks and Caicos Islands and Southeast Bahamas.` A warning is
    "expected", a watch is "possible", as NHC defines them.
    """
    public = current_public(state)
    if public is None:
        return []
    areas = list(enumerate(public.watches_warnings.in_effect))

    def rank(item: tuple[int, WatchWarningArea]) -> tuple[int, int]:
        key = (_area_hazard(item[1]), _area_level(item[1]))
        return (_SEVERITY.index(key) if key in _SEVERITY else len(_SEVERITY), item[0])

    out: list[Words] = []
    for index, area in sorted(areas, key=rank):
        if not area.areas:
            continue
        shown = " and ".join(area.areas[:2])
        extra = len(area.areas) - 2
        where = shown + (f", +{extra} more" if extra > 0 else "")
        hazard, level = _area_hazard(area), _area_level(area)
        source = f"{_BASE}.public.watches_warnings.in_effect[{index}]"
        chance = "expected" if level == "warning" else "possible"
        if hazard is None or level is None:
            text = f"{area.label} is in effect in {where}."
        elif hazard == "storm surge":
            text = f"Life-threatening storm surge is {chance} in {where}."
        else:
            text = f"{hazard.capitalize()} conditions are {chance} in {where}."
        out.append(Words(text, (f"{source}.label", f"{source}.kind", f"{source}.areas")))
    return out


def meaning_sentences(state: StormState) -> list[Words]:
    """What each kind of watch or warning in effect means, quoted from the advisory, else NHC's glossary."""
    public = current_public(state)
    if public is None:
        return []
    text = public.watches_warnings.text
    quoted = quoted_meanings(text)
    out: list[Words] = []
    seen: set[tuple[str, str]] = set()
    for _, area in sorted(enumerate(public.watches_warnings.in_effect), key=lambda i: _meaning_rank(i[1])):
        hazard, level = _area_hazard(area), _area_level(area)
        if hazard is None or level is None or (hazard, level) in seen:
            continue
        seen.add((hazard, level))
        if (hazard, level) in quoted:
            out.append(Words(quoted[(hazard, level)], (f"{_BASE}.public.watches_warnings.text",)))
        else:
            out.append(Words(MEANINGS[(hazard, level)], (f"glossary.MEANINGS[{hazard!r}, {level!r}]",)))
    return out


def _meaning_rank(area: WatchWarningArea) -> int:
    key = (_area_hazard(area), _area_level(area))
    return _SEVERITY.index(key) if key in _SEVERITY else len(_SEVERITY)


# --------------------------------------------------------------------------------------------------- size and forecast


def _reach(preset: Preset, nm: int | None) -> str:
    return distance_text(preset, nm=nm) if nm is not None else ""


def size_sentence(state: StormState, preset: Preset) -> Words | None:
    """`Tropical-storm-force winds (39+ mph) reach up to 140 mi from the centre; hurricane-force (74+ mph) to 45 mi.`

    Read only when the forecast advisory matches the feed's.
    """
    tcm = current_forecast(state)
    if tcm is None or tcm.radii.kt34 is None or tcm.radii.kt34.largest is None:
        return None

    def threshold(kt: int) -> str:
        return f"{_THRESHOLDS[kt].get(preset.wind, kt)}+ {LABELS[preset.wind]}"

    sources = [f"{_BASE}.forecast.radii.kt34"]
    text = (
        f"Tropical-storm-force winds ({threshold(34)}) reach up to {_reach(preset, tcm.radii.kt34.largest)} "
        "from the centre"
    )
    hurricane = tcm.radii.kt64
    if hurricane is not None and hurricane.largest:
        text += f"; hurricane-force ({threshold(64)}) to {_reach(preset, hurricane.largest)}"
        sources.append(f"{_BASE}.forecast.radii.kt64")
    return Words(text + ".", tuple(sources))


def _fix_status(fix: ForecastFix) -> str:
    if fix.dissipated:
        return "dissipated"
    if fix.status:
        return _STATUS.get(fix.status.upper(), fix.status.lower())
    return _category_word(fix.max_wind_kt) or "tropical system"


def forecast_rows(state: StormState, preset: Preset, tz: tzinfo | None) -> list[Words]:
    """One line per forecast fix: `Tue 05:00 PM EDT  Category 4  125 mph  27.0N 74.0W`, then the days 4-5 note."""
    tcm = current_forecast(state)
    if tcm is None:
        return []
    out: list[Words] = []
    for index, fix in enumerate(tcm.fixes):
        local = ensure_utc(fix.valid).astimezone(tz)
        when = f"{local:%a %I:%M %p} {local.tzname() or ''}".strip()
        base = f"{_BASE}.forecast.fixes[{index}]"
        if fix.dissipated:
            out.append(Words(f"{when}  dissipated", (f"{base}.valid", f"{base}.dissipated")))
            continue
        parts = [when, _fix_status(fix)]
        wind = wind_text(preset, kt=fix.max_wind_kt)
        if wind:
            parts.append(wind)
        if fix.lat is not None and fix.lon is not None:
            parts.append(f"{fmt_lat(fix.lat)} {fmt_lon(fix.lon)}")
        sources = (f"{base}.valid", f"{base}.max_wind_kt", f"{base}.lat", f"{base}.lon", f"{base}.status")
        out.append(Words("  ".join(parts), sources))
    if tcm.outlook_fixes:
        out.append(Words(TCM_OUTLOOK_NOTE, (f"{_BASE}.forecast.outlook_fixes",)))
    return out


def strongest(state: StormState, tz: tzinfo | None) -> Words | None:
    """`Strongest: Category 4 now, then weakening.` From the storm's wind now and the forecast fixes."""
    storm, tcm = state.storm, current_forecast(state)
    if storm.intensity_kt is None or tcm is None:
        return None
    fixes = [f for f in tcm.forecast_fixes if f.max_wind_kt is not None and not f.dissipated]
    if not fixes:
        return None
    peak_fix = max(fixes, key=lambda f: (f.max_wind_kt or 0, -f.tau))
    peak_kt = peak_fix.max_wind_kt or 0
    sources = ["state.storm.intensity_kt", f"{_BASE}.forecast.fixes"]
    if peak_kt <= storm.intensity_kt + _HOLD_KT:  # the storm is at its strongest now
        peak_kt, when, last_is_peak = storm.intensity_kt, "now", False
    else:
        local = ensure_utc(peak_fix.valid).astimezone(tz)
        when, last_is_peak = f"on {local:%A}", peak_fix is fixes[-1]
    word = _category_word(peak_kt) or "tropical depression"
    head = f"Strongest: {word} {when}"
    last_kt = fixes[-1].max_wind_kt or 0
    if last_is_peak:
        return Words(f"{head}, strengthening through the forecast.", tuple(sources))
    return Words(f"{head}, then {'weakening' if last_kt < peak_kt - _HOLD_KT else 'holding'}.", tuple(sources))
