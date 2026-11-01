"""Sentences about the tropical weather outlook: how many areas NHC is watching and their chances of forming."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

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


def _areas(outlook: Outlook, enabled: Sequence[str]) -> list[_Area]:
    """The areas from the outlook shapes, or from the outlook text when the shapes did not arrive."""
    found: list[_Area] = []
    for index, system in enumerate(outlook.gis.systems):
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
    if found or not outlook.gis.empty:
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


def area_count(outlook: Outlook | None, enabled: Sequence[str]) -> int:
    """How many areas NHC is watching in the enabled basins (0 when the outlook has not arrived)."""
    return 0 if outlook is None else len(_areas(outlook, enabled))


def outlook_sentences(outlook: Outlook | None, enabled: Sequence[str]) -> list[Words]:
    """`NHC is watching 1 area in the Atlantic: a 70% chance it forms within 7 days, and 30% within 2 days.`

    With several areas, a lead sentence and one line each. With none, the outlook's own summary as issued.
    """
    if outlook is None:
        return [Words("Waiting for the first outlook.")]
    areas = _areas(outlook, enabled)
    if len(areas) == 1:
        return [Words(f"NHC is watching 1 area{_in(areas[0])}: {_chances(areas[0])}.", areas[0].sources)]
    if areas:
        lead = Words(f"NHC is watching {len(areas)} areas.", ("outlook.gis.systems",))
        return [lead, *(Words(f"{a.label}: {_chances(a)}.", a.sources) for a in areas)]
    out: list[Words] = []
    seen: set[str] = set()
    for index, text in enumerate(outlook.texts):
        if not set(text_basins(text)) & set(enabled):
            continue
        summary = collapse(text.summary)
        if summary and summary not in seen:
            seen.add(summary)
            out.append(Words(summary, (f"outlook.texts[{index}].summary",)))
    return out or [Words("No outlook has been issued yet.")]
