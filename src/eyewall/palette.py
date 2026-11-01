"""Every color and every non-color cue the interface uses. This is the only module that holds a hex literal.

Each meaningful state (category, watch or warning kind, outlook risk, freshness, alert severity, tide difference,
pressure trend) is a `Cue`: a color plus a word, a short word, a Unicode and an ASCII glyph, a line pattern for the map
and an emphasis. Colour never carries a meaning alone, so with `NO_COLOR` set the words, glyphs, patterns and emphasis
still tell the states apart. Today the interface reads the color and emphasis of every cue, the pattern of the
watch and warning cues (map lines and key), the short word of those cues (map key) and the glyphs of the freshness and
pressure trend cues. The `word` and `short` fields elsewhere, the risk cues and the remaining glyphs are plumbing for
the later redesign PRs that name states in words; the guard tests keep them complete until then.

Category order follows the Saffir-Simpson scale. The hex values are tuned for dark terminals; watch and warning colors
follow the conventional NHC reading (tropical storm watch yellow, warning blue, hurricane watch pink, warning red).
One wind scale: a wind of X knots is `category_color(X)` everywhere (panel label, ring, track, buoy number), and it is
neutral below 34 knots.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

# Line patterns as (dots on, dots off); None is solid. Each map element that needs telling apart without colour gets
# its own: rings by strength, watch and warning lines by kind.
Pattern = tuple[int, int] | None
SOLID: Pattern = None
DASHED: Pattern = (6, 3)
DOTTED: Pattern = (1, 3)
SPARSE: Pattern = (1, 7)  # widely spaced dots, apart from DOTTED
FORECAST_DASH: Pattern = (4, 2)  # the forecast track; kept apart from the 50 kt ring's DASHED

# A sample stroke of each pattern for the map key, as (Unicode, ASCII).
PATTERN_SAMPLES: dict[Pattern, tuple[str, str]] = {
    SOLID: ("───", "---"),
    DASHED: ("╌╌╌", "- -"),
    DOTTED: ("┈┈┈", "..."),
    SPARSE: ("┈ ┈ ┈", ". . ."),
}

# Chrome.
BACKGROUND = "#0d1117"
SURFACE = "#121a24"
PANEL = "#17212d"
FOREGROUND = "#e6edf5"
DIM = "#7d8a99"
ACCENT = "#ffa63d"
GOOD = "#3ddc84"
WARN = "#ffe94a"
BAD = "#ff4d4d"
INFO = "#4aa3ff"
HEADING = "#8fd3ff"
NEUTRAL = "#9aa4b2"

# Map tones that carry no meaning of their own.
LAND = "#3a4658"
COAST = "#9fb3c8"
BORDER = "#6e7f94"
STATE_LINE = "#4a5668"
CONE_FILL = "#66758a"
CONE_EDGE = "#e6edf5"
MAP_LABEL = "#c9d3de"
BUOY = "#8fd3ff"
TIDE_GAUGE = "#5eead4"
STALE = "#566273"
CURSOR = "#ffffff"

# Chart furniture and series.
CHART_AXIS = "#8b98a9"
CHART_GRID = "#2b3544"
CHART_TEXT = "#c9d3de"
PRESSURE_SERIES = INFO
WIND_SERIES = GOOD
GUST_SERIES = ACCENT
WAVE_SERIES = HEADING


@dataclass(frozen=True, slots=True)
class Cue:
    """One meaningful state in every form it can take. `emphasis` is a rich style word such as 'bold'."""

    color: str
    word: str
    short: str
    glyph: str = ""
    ascii_glyph: str = ""
    pattern: Pattern = SOLID
    emphasis: str = ""

    def style(self) -> str:
        """The rich style string: emphasis first, then the color."""
        return f"{self.emphasis} {self.color}".strip()


class Category(StrEnum):
    TD = "TD"
    TS = "TS"
    H1 = "H1"
    H2 = "H2"
    H3 = "H3"
    H4 = "H4"
    H5 = "H5"


# (minimum wind in knots, category), highest first.
_THRESHOLDS = (
    (137.0, Category.H5),
    (113.0, Category.H4),
    (96.0, Category.H3),
    (83.0, Category.H2),
    (64.0, Category.H1),
    (34.0, Category.TS),
)


def category_for_knots(wind_kt: float | None) -> Category | None:
    """Saffir-Simpson category for a maximum sustained wind in knots. None when the wind is unknown."""
    if wind_kt is None or wind_kt < 0:
        return None
    for floor, category in _THRESHOLDS:
        if wind_kt >= floor:
            return category
    return Category.TD


CATEGORY_CUES: dict[Category, Cue] = {
    Category.TD: Cue(NEUTRAL, "Tropical Depression", "TD"),
    Category.TS: Cue("#3ddc84", "Tropical Storm", "TS"),
    Category.H1: Cue("#ffe94a", "Hurricane Category 1", "Cat 1"),
    Category.H2: Cue("#ffa63d", "Hurricane Category 2", "Cat 2"),
    Category.H3: Cue("#ff4d4d", "Hurricane Category 3", "Cat 3"),
    Category.H4: Cue("#ff4fd8", "Hurricane Category 4", "Cat 4"),
    Category.H5: Cue("#b36bff", "Hurricane Category 5", "Cat 5"),
}
CATEGORY_COLORS: dict[Category, str] = {category: cue.color for category, cue in CATEGORY_CUES.items()}

# The wind radii rings, by the speed they enclose: each gets its own pattern, and the map key names them.
RING_KNOTS = (34, 50, 64)
RING_PATTERNS: dict[int, Pattern] = {34: DOTTED, 50: DASHED, 64: SOLID}
RING_PATTERN_NAMES: dict[int, str] = {34: "dotted", 50: "dashed", 64: "solid"}


class WatchWarning(StrEnum):
    """Coastal watch and warning kinds. The first four values are NHC's TCWW codes; the surge values are internal."""

    TROPICAL_STORM_WATCH = "TWA"
    TROPICAL_STORM_WARNING = "TWR"
    HURRICANE_WATCH = "HWA"
    HURRICANE_WARNING = "HWR"
    SURGE_WATCH = "SURGE_WATCH"
    SURGE_WARNING = "SURGE_WARNING"


# A warning is solid, a watch dashed, a surge warning dotted and a surge watch sparsely dotted. Hurricane and tropical
# storm lines of the same kind differ by color and by the words in the key.
WATCH_WARNING_CUES: dict[WatchWarning, Cue] = {
    WatchWarning.TROPICAL_STORM_WATCH: Cue("#ffe94a", "Tropical Storm Watch", "TS watch", pattern=DASHED),
    WatchWarning.TROPICAL_STORM_WARNING: Cue("#4aa3ff", "Tropical Storm Warning", "TS warning"),
    WatchWarning.HURRICANE_WATCH: Cue("#ff8fcf", "Hurricane Watch", "Hurr watch", pattern=DASHED),
    WatchWarning.HURRICANE_WARNING: Cue("#ff4d4d", "Hurricane Warning", "Hurr warning"),
    WatchWarning.SURGE_WATCH: Cue("#c8a8ff", "Storm Surge Watch", "Surge watch", pattern=SPARSE),
    WatchWarning.SURGE_WARNING: Cue("#9b4dff", "Storm Surge Warning", "Surge warning", pattern=DOTTED),
}
WATCH_WARNING_COLORS: dict[WatchWarning, str] = {kind: cue.color for kind, cue in WATCH_WARNING_CUES.items()}

# NHC's outlook risk labels for the 2-day and 7-day formation chance. Only the colors are read today; the words are
# for a later redesign PR.
RISK_CUES: dict[str, Cue] = {
    "low": Cue("#ffe94a", "Low", "low"),
    "medium": Cue("#ffa63d", "Medium", "medium"),
    "high": Cue("#ff4d4d", "High", "high"),
}
RISK_COLORS: dict[str, str] = {risk: cue.color for risk, cue in RISK_CUES.items()}

# Freshness of a feed, keyed by `poll.FreshnessState` value.
FRESHNESS_CUES: dict[str, Cue] = {
    "fresh": Cue(GOOD, "ok", "ok", "●", "*"),
    "stale": Cue(WARN, "stale", "stale", "◐", "~"),
    "error": Cue(BAD, "failing", "fail", "✕", "x"),
    "loading": Cue(DIM, "loading", "load", "○", "o"),
}

# Alert severity, keyed by `models.events.Severity` value.
SEVERITY_CUES: dict[str, Cue] = {
    "info": Cue(HEADING, "Info", "info"),
    "notice": Cue(WARN, "Notice", "notice"),
    "warning": Cue(BAD, "Warning", "warn", "!", "!"),
}

# A three hour pressure change: falling by a hectopascal or more is flagged, by three or more is rapid.
PRESSURE_TREND_CUES: dict[str, Cue] = {
    "rapid fall": Cue(BAD, "falling fast", "fall fast", "↓", "v", emphasis="bold"),
    "fall": Cue(ACCENT, "falling", "falling", "↓", "v", emphasis="bold"),
    "steady": Cue(DIM, "steady", "steady", "→", "="),
    "rise": Cue(DIM, "rising", "rising", "↑", "^"),
}

# Tide gauge height above the predicted tide, in feet, largest first; at or below -1 ft is its own state.
TIDE_DIFFERENCE_CUES: tuple[tuple[float, Cue], ...] = (
    (4.0, Cue(BAD, "4 ft or more above", "+4 ft", emphasis="bold")),
    (2.0, Cue(ACCENT, "2 ft or more above", "+2 ft", emphasis="bold")),
    (1.0, Cue(WARN, "1 ft or more above", "+1 ft", emphasis="bold")),
)
TIDE_BELOW_CUE = Cue(HEADING, "1 ft or more below", "-1 ft")


def risk_cue(risk: str | None) -> Cue | None:
    """The cue for an outlook risk label such as Low, Medium or High; None for an unknown label."""
    return RISK_CUES.get((risk or "").strip().lower())


def risk_color(risk: str | None) -> str:
    """Color for an outlook risk label such as Low, Medium or High. Unknown labels are neutral."""
    cue = risk_cue(risk)
    return NEUTRAL if cue is None else cue.color


def category_color(wind_kt: float | None) -> str:
    """The one wind color scale: a wind of this many knots, for a mark, track, ring, number or label. Neutral below
    34 knots and when the wind is unknown."""
    category = category_for_knots(wind_kt)
    return NEUTRAL if category is None else CATEGORY_COLORS[category]


def storm_force(wind_kt: float | None) -> bool:
    """Whether a wind reaches tropical storm strength (34 knots), where the wind scale starts to color it."""
    return wind_kt is not None and wind_kt >= 34.0
