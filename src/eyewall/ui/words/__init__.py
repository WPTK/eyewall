"""Plain-language sentences for storms, outlooks and stations.

Pure functions with no Textual in them. Every builder returns a `Words`: the sentence and the names of the source fields
it read, so a test can check that each claim traces to something NOAA reported. Units come from a `units.Preset`; a
sentence is rebuilt whenever the reader cycles the units.
"""

from __future__ import annotations

from dataclasses import dataclass

from eyewall.textclean import printable
from eyewall.units import LABELS, Preset, convert


@dataclass(frozen=True, slots=True)
class Words:
    """One sentence and the fields behind it, as dotted paths from the object the builder was given (`storm.name`)."""

    text: str
    sources: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "text", printable(self.text))  # names in a sentence come straight from a feed

    def __str__(self) -> str:
        return self.text


def round5(value: float) -> int:
    """Round to the nearest 5, the way NHC rounds converted speeds and distances."""
    return int(5 * round(value / 5))


def wind_text(preset: Preset, kt: float | None = None, mph: float | None = None) -> str | None:
    """A storm wind in the preset's unit, or None when neither source is known.

    Rule 1: knots come from the knot field; miles per hour use NHC's own figure when the caller has it; km/h and any
    mph worked out from knots are rounded to 5, which is how NHC prints them (120 kt is 140 mph, not 138).
    """
    unit = preset.wind
    if unit == "kt" and kt is not None:
        value = round(kt)
    elif unit == "mph" and mph is not None:
        value = round(mph)
    elif kt is not None:
        value = round5(convert(kt, "kt", unit))
    elif mph is not None:
        value = round5(convert(mph, "mph", unit))
    else:
        return None
    return f"{value} {LABELS[unit]}"


def distance_text(preset: Preset, *, nm: float | None = None, mi: float | None = None, km: float | None = None) -> str:
    """A distance in the preset's unit from whichever of nautical miles, miles and kilometres is known.

    Rule 2: miles and kilometres are NHC's own figures when given; nautical miles are worked out from NHC's miles and
    rounded to 5.
    """
    unit = preset.distance
    if unit == "mi" and mi is not None:
        value = round(mi)
    elif unit == "km" and km is not None:
        value = round(km)
    elif nm is not None:
        value = round5(convert(nm, "nm", unit))
    elif mi is not None:
        value = round5(convert(mi, "mi", unit))
    elif km is not None:
        value = round5(convert(km, "km", unit))
    else:
        raise ValueError("a distance needs nm, mi or km")
    return f"{value} {LABELS[unit]}"
