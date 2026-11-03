"""Sentences about the tropical weather outlook: how many areas NHC is watching and their chances of forming."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from eyewall.models.outlook import Outlook, OutlookSystem
from eyewall.ui.format import BASIN_NAMES, collapse, text_basins
from eyewall.ui.words import Words

_GIS_BASINS = {"atlantic": ("AL",), "pacific": ("EP", "CP")}


@dataclass(frozen=True, slots=True)
class _Area:
    label: str
    p2: int | None
    p7: int | None
    sources: tuple[str, ...]
    basin: str = ""  # where it is, in words: `Central Pacific`


def _a(percent: int) -> str:
    """`a 30%` but `an 80%`."""
    return "an" if str(percent).startswith("8") or percent in (11, 18) else "a"


def _basin_of(system: OutlookSystem) -> str:
    """The basin an area sits in. NOAA's shapefiles say only Atlantic or Pacific, so the Pacific is split at 140W."""
    if system.basin_label.strip().lower() == "atlantic":
        return BASIN_NAMES["AL"]
    ring = system.polygons[0] if system.polygons else ()
    lons = [p[1] for p in ring] or ([system.point[1]] if system.point else [])
    if not lons:
        return ""
    lon = sum(lons) / len(lons)
    return BASIN_NAMES["CP"] if lon < -140.0 or lon > 0.0 else BASIN_NAMES["EP"]


def _in(area: _Area) -> str:
    return f" in the {area.basin}" if area.basin else ""


def _chances(area: _Area) -> str:
    """The 7 day chance first: it is the one the map labels the area with."""
    if area.p2 is not None and area.p7 is not None:
        return f"{_a(area.p7)} {area.p7}% chance it forms within 7 days, and {area.p2}% within 2 days"
    if area.p2 is not None:
        return f"{_a(area.p2)} {area.p2}% chance it forms within 2 days"
    if area.p7 is not None:
        return f"{_a(area.p7)} {area.p7}% chance it forms within 7 days"
    return "no formation chance is given"


def _areas(outlook: Outlook, enabled: Sequence[str], now: datetime | None = None) -> list[_Area]:
    """The areas from the outlook shapes, or from the outlook text when the shapes did not arrive or are past
    `GIS_DROP_AFTER` (a kept copy must not win over the fresh text)."""
    found: list[_Area] = []
    gis_old = outlook.gis.expired(now)
    for index, system in enumerate(() if gis_old else outlook.gis.systems):
        basins = _GIS_BASINS.get(system.basin_label.strip().lower(), ())
        if basins and not set(basins) & set(enabled):
            continue
        base = f"outlook.gis.systems[{index}]"
        label = f"{system.basin_label} area {system.area_id}".strip()
        found.append(
            _Area(
                label, system.prob_2day, system.prob_7day, (f"{base}.prob_2day", f"{base}.prob_7day"), _basin_of(system)
            )
        )
    if found or not (outlook.gis.empty or gis_old):
        return found
    for t_index, text in enumerate(outlook.texts):
        basins = text_basins(text)
        if not set(basins) & set(enabled):
            continue
        for a_index, area in enumerate(text.areas):
            base = f"outlook.texts[{t_index}].areas[{a_index}]"
            p2 = area.chance_48h.percent if area.chance_48h else None
            p7 = area.chance_7d.percent if area.chance_7d else None
            label = f"{BASIN_NAMES[basins[0]]} area {area.number or a_index + 1}"
            found.append(_Area(label, p2, p7, (f"{base}.chance_48h", f"{base}.chance_7d"), BASIN_NAMES[basins[0]]))
    return found


def area_count(outlook: Outlook | None, enabled: Sequence[str], now: datetime | None = None) -> int:
    """How many areas NHC is watching in the enabled basins (0 when the outlook has not arrived)."""
    return 0 if outlook is None else len(_areas(outlook, enabled, now))


def _summaries(outlook: Outlook, enabled: Sequence[str], covered: set[str]) -> list[Words]:
    """NHC's own summary for each enabled basin that has no area, as issued, once per basin. One text can speak for two
    basins (the East and Central Pacific): each is judged on its own, so an area in one leaves the other's quiet said.
    With more than one basin shown, each line leads with its name, so `not expected` is not read for the wrong ocean."""
    found: dict[str, tuple[int, str]] = {}
    for index, text in enumerate(outlook.texts):
        summary = collapse(text.summary)
        if not summary or text.areas:
            continue
        for code in text_basins(text):
            name = BASIN_NAMES[code]
            if code in enabled and name not in covered:
                found.setdefault(name, (index, summary))
    named = len(found) > 1 or bool(covered)
    order = [BASIN_NAMES[c] for c in ("AL", "EP", "CP")]
    return [
        Words(f"{name}: {found[name][1]}" if named else found[name][1], (f"outlook.texts[{found[name][0]}].summary",))
        for name in order
        if name in found
    ]


def outlook_sentences(
    outlook: Outlook | None, enabled: Sequence[str], *, summaries: bool = True, now: datetime | None = None
) -> list[Words]:
    """`NHC is watching 1 area in the Atlantic: a 70% chance it forms within 7 days, and 30% within 2 days.`

    With several areas, a lead sentence and one line each. A basin with none says so in NHC's own summary, after the
    areas of the others.
    """
    if outlook is None:
        return [Words("Waiting for the first outlook.")]
    areas = _areas(outlook, enabled, now)
    out: list[Words] = []
    if len(areas) == 1:
        out = [Words(f"NHC is watching 1 area{_in(areas[0])}: {_chances(areas[0])}.", areas[0].sources)]
    elif areas:
        lead = Words(f"NHC is watching {len(areas)} areas.", ("outlook.gis.systems",))
        out = [lead, *(Words(f"{a.label}: {_chances(a)}.", a.sources) for a in areas)]
    if summaries:
        out += _summaries(outlook, enabled, {a.basin for a in areas})
    return out or [Words("No outlook has been issued yet.")]


OUTLOOK_OLD = "The outlook could not be updated, so what follows may be out of date."


def current_sentences(
    outlook: Outlook | None, enabled: Sequence[str], *, old: bool, summaries: bool = True, now: datetime | None = None
) -> list[str]:
    """The outlook in sentences. When its feed has failed or stopped, a warning leads and only the areas it named
    follow: `not expected` is not said on the strength of an answer that may be stale."""
    if old and outlook is not None:
        areas = (
            outlook_sentences(outlook, enabled, summaries=False, now=now) if area_count(outlook, enabled, now) else []
        )
        return [OUTLOOK_OLD, *(w.text for w in areas)]
    return [w.text for w in outlook_sentences(outlook, enabled, summaries=summaries, now=now)]
