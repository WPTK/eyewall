"""Symbols for the interface in two sets: unicode, and plain ASCII for the legacy Windows console.

The map has its own set (`render.canvas.Glyphs`); this one covers the chrome around it: freshness dots, the replay
transport, tendency arrows and the chips beside watches and warnings.
"""

from __future__ import annotations

from dataclasses import dataclass

from eyewall.palette import FRESHNESS_CUES, PRESSURE_TREND_CUES


@dataclass(frozen=True, slots=True)
class UiGlyphs:
    fresh: str
    stale: str
    error: str
    loading: str
    play: str
    pause: str
    chip: str
    rising: str
    falling: str
    steady: str
    sep: str
    ellipsis: str
    alert: str
    rule: str
    crumb: str


UNICODE = UiGlyphs(
    fresh=FRESHNESS_CUES["fresh"].glyph,
    stale=FRESHNESS_CUES["stale"].glyph,
    error=FRESHNESS_CUES["error"].glyph,
    loading=FRESHNESS_CUES["loading"].glyph,
    play="▶",
    pause="⏸",
    chip="■",
    rising=PRESSURE_TREND_CUES["rise"].glyph,
    falling=PRESSURE_TREND_CUES["fall"].glyph,
    steady=PRESSURE_TREND_CUES["steady"].glyph,
    sep="·",
    ellipsis="…",
    alert="!",
    rule="─",
    crumb="›",  # noqa: RUF001 (a single right-pointing angle quotation mark)
)

ASCII = UiGlyphs(
    fresh=FRESHNESS_CUES["fresh"].ascii_glyph,
    stale=FRESHNESS_CUES["stale"].ascii_glyph,
    error=FRESHNESS_CUES["error"].ascii_glyph,
    loading=FRESHNESS_CUES["loading"].ascii_glyph,
    play=">",
    pause="||",
    chip="#",
    rising=PRESSURE_TREND_CUES["rise"].ascii_glyph,
    falling=PRESSURE_TREND_CUES["fall"].ascii_glyph,
    steady=PRESSURE_TREND_CUES["steady"].ascii_glyph,
    sep="|",
    ellipsis="...",
    alert="!",
    rule="-",
    crumb=">",
)

SETS = {"unicode": UNICODE, "ascii": ASCII}


def glyphs_for(name: str) -> UiGlyphs:
    """The set for a `[map] glyph_set` value; an unknown name gets unicode."""
    return SETS.get(name, UNICODE)
