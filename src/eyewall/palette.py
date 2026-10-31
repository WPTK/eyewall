"""Colors and categories for storms, watches and warnings, invest risk and buoy winds.

Category order follows the Saffir-Simpson scale. The hex values are tuned for dark terminals; watch and warning colors
follow the conventional NHC reading (tropical storm watch yellow, warning blue, hurricane watch pink, warning red).
"""

from __future__ import annotations

from enum import StrEnum


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


CATEGORY_COLORS: dict[Category, str] = {
    Category.TD: "#4aa3ff",
    Category.TS: "#3ddc84",
    Category.H1: "#ffe94a",
    Category.H2: "#ffa63d",
    Category.H3: "#ff4d4d",
    Category.H4: "#ff4fd8",
    Category.H5: "#b36bff",
}


class WatchWarning(StrEnum):
    """Coastal watch and warning kinds. The first four values are NHC's TCWW codes; the surge values are internal."""

    TROPICAL_STORM_WATCH = "TWA"
    TROPICAL_STORM_WARNING = "TWR"
    HURRICANE_WATCH = "HWA"
    HURRICANE_WARNING = "HWR"
    SURGE_WATCH = "SURGE_WATCH"
    SURGE_WARNING = "SURGE_WARNING"


WATCH_WARNING_COLORS: dict[WatchWarning, str] = {
    WatchWarning.TROPICAL_STORM_WATCH: "#ffe94a",
    WatchWarning.TROPICAL_STORM_WARNING: "#4aa3ff",
    WatchWarning.HURRICANE_WATCH: "#ff8fcf",
    WatchWarning.HURRICANE_WARNING: "#ff4d4d",
    WatchWarning.SURGE_WATCH: "#c8a8ff",
    WatchWarning.SURGE_WARNING: "#9b4dff",
}

# NHC's outlook risk labels for the 2-day and 7-day formation chance.
RISK_COLORS: dict[str, str] = {"low": "#ffe94a", "medium": "#ffa63d", "high": "#ff4d4d"}

NEUTRAL = "#9aa4b2"


def risk_color(risk: str | None) -> str:
    """Color for an outlook risk label such as Low, Medium or High. Unknown labels are neutral."""
    return RISK_COLORS.get((risk or "").strip().lower(), NEUTRAL)


def category_color(wind_kt: float | None) -> str:
    """Color for a wind speed in knots through its storm category. Neutral when the wind is unknown."""
    category = category_for_knots(wind_kt)
    return NEUTRAL if category is None else CATEGORY_COLORS[category]


def wind_band_color(wind_kt: float | None) -> str | None:
    """Color for a buoy or station wind against NHC's 34, 50 and 64 knot thresholds. None below 34 kt."""
    if wind_kt is None or wind_kt < 34:
        return None
    if wind_kt < 50:
        return "#ffe94a"
    if wind_kt < 64:
        return "#ffa63d"
    return "#ff4d4d"
