"""The `ABOUT 695 MI...1120 KM SW OF BERMUDA` lines of a public advisory, read into numbers and a place name."""

from __future__ import annotations

import re
from dataclasses import dataclass

_ABOUT = re.compile(
    r"^\s*ABOUT\s+(?P<mi>\d+)\s*MI(?:\.{2,}\s*(?P<km>\d+)\s*KM)?\s+(?P<dir>[A-Z]+)\s+OF\s+(?P<place>.+?)\s*$",
    re.IGNORECASE,
)
_WORDS = {
    "NORTH": "N",
    "SOUTH": "S",
    "EAST": "E",
    "WEST": "W",
    "NORTHEAST": "NE",
    "NORTHWEST": "NW",
    "SOUTHEAST": "SE",
    "SOUTHWEST": "SW",
}
_COMPASS = frozenset(
    ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW")
)
_SMALL = frozenset({"of", "the", "and", "de", "la", "del", "du", "on", "in", "by"})


@dataclass(frozen=True, slots=True)
class About:
    """How far the centre is from a place. `km` is None when the line gives only miles."""

    miles: int
    km: int | None
    direction: str
    place: str


def place_name(raw: str) -> str:
    """NHC prints places in capitals; give them back their case (`CAPE HATTERAS` is `Cape Hatteras`)."""
    out: list[str] = []
    for index, word in enumerate(raw.split()):
        lower = word.lower()
        if index and lower in _SMALL:
            out.append(lower)
        else:
            out.append("-".join(part.capitalize() for part in lower.split("-")))
    return " ".join(out)


def parse_about(line: str) -> About | None:
    """One `ABOUT ...` line, or None when it does not read that way. Missing or extra parts are tolerated."""
    match = _ABOUT.match(line)
    if match is None:
        return None
    direction = match["dir"].upper()
    direction = _WORDS.get(direction, direction)
    if direction not in _COMPASS:
        return None
    km = match["km"]
    return About(int(match["mi"]), None if km is None else int(km), direction, place_name(match["place"]))


def parse_abouts(lines: tuple[str, ...]) -> list[tuple[int, About]]:
    """Every readable line with its index in `lines`, so a sentence can name the field it came from."""
    found = [(index, parse_about(line)) for index, line in enumerate(lines)]
    return [(index, about) for index, about in found if about is not None]
