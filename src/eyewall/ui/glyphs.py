"""Symbols for the interface in two sets: unicode, and plain ASCII for the legacy Windows console.

The map has its own set (`render.canvas.Glyphs`); this one covers the chrome around it: freshness dots, the replay
transport, tendency arrows and the chips beside watches and warnings.
"""

from __future__ import annotations

from dataclasses import dataclass


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


UNICODE = UiGlyphs(
    fresh="●",
    stale="◐",
    error="✕",
    loading="○",
    play="▶",
    pause="⏸",
    chip="■",
    rising="↑",
    falling="↓",
    steady="→",
    sep="·",
    ellipsis="…",
    alert="!",
    rule="─",
)

ASCII = UiGlyphs(
    fresh="*",
    stale="~",
    error="x",
    loading="o",
    play=">",
    pause="||",
    chip="#",
    rising="^",
    falling="v",
    steady="=",
    sep="|",
    ellipsis="...",
    alert="!",
    rule="-",
)

SETS = {"unicode": UNICODE, "ascii": ASCII}


def glyphs_for(name: str) -> UiGlyphs:
    """The set for a `[map] glyph_set` value; an unknown name gets unicode."""
    return SETS.get(name, UNICODE)
