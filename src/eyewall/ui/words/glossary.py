"""What watches and warnings mean, in NHC's own words.

The advisory carries the "A ... means ..." sentences itself, so `quoted_meanings` reads them from there. The fixed table
is copied from NHC wording for an advisory that left them out.
"""

from __future__ import annotations

import re

Hazard = str  # "hurricane", "tropical storm" or "storm surge"
Level = str  # "watch" or "warning"

MEANINGS: dict[tuple[Hazard, Level], str] = {
    ("hurricane", "warning"): "A Hurricane Warning means that hurricane conditions are expected somewhere within the "
    "warning area.",
    ("hurricane", "watch"): "A Hurricane Watch means that hurricane conditions are possible within the watch area, "
    "generally within 48 hours.",
    ("tropical storm", "warning"): "A Tropical Storm Warning means that tropical storm conditions are expected "
    "somewhere within the warning area.",
    ("tropical storm", "watch"): "A Tropical Storm Watch means that tropical storm conditions are possible within "
    "the watch area, generally within 48 hours.",
    ("storm surge", "warning"): "A Storm Surge Warning means there is a danger of life-threatening inundation, from "
    "rising water moving inland from the coastline, in the indicated locations.",
    ("storm surge", "watch"): "A Storm Surge Watch means there is a possibility of life-threatening inundation, from "
    "rising water moving inland from the coastline, in the indicated locations during the next 48 hours.",
}

_MEANS = re.compile(r"\b(?:A|An)\s+([A-Za-z ]+?)\s+(Watch|Warning)\s+means\b", re.IGNORECASE)
_HAZARDS = ("tropical storm", "hurricane", "storm surge")


def hazard_of(label: str) -> Hazard | None:
    """The hazard named in a label such as `Tropical Storm Warning`, or None."""
    lower = label.lower()
    return next((h for h in _HAZARDS if h in lower), None)


def level_of(label: str) -> Level | None:
    lower = label.lower()
    return "warning" if "warning" in lower else "watch" if "watch" in lower else None


def quoted_meanings(text: str) -> dict[tuple[Hazard, Level], str]:
    """The first sentence of each `A Tropical Storm Warning means ...` paragraph in the advisory, as issued."""
    flat = text.replace("-\n", "-")
    found: dict[tuple[Hazard, Level], str] = {}
    for match in _MEANS.finditer(flat):
        hazard, level = hazard_of(match[1]), match[2].lower()
        if hazard is None:
            continue
        rest = flat[match.start() :]
        end = re.search(r"\.(?=\s|$)", rest)
        sentence = " ".join((rest[: end.end()] if end else rest).split())
        found.setdefault((hazard, level), sentence)
    return found
