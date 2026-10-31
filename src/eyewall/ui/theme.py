"""Colors for the interface. Meaning-carrying colors (categories, watches, risk) come from `eyewall.palette`."""

from __future__ import annotations

from textual.theme import Theme

from eyewall.poll import FreshnessState

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

THEME_NAME = "eyewall"

EYEWALL_THEME = Theme(
    name=THEME_NAME,
    primary=INFO,
    secondary="#8fd3ff",
    accent=ACCENT,
    foreground=FOREGROUND,
    background=BACKGROUND,
    surface=SURFACE,
    panel=PANEL,
    success=GOOD,
    warning=WARN,
    error=BAD,
    dark=True,
)

FRESHNESS_COLORS: dict[FreshnessState, str] = {
    FreshnessState.FRESH: GOOD,
    FreshnessState.STALE: WARN,
    FreshnessState.ERROR: BAD,
    FreshnessState.LOADING: DIM,
}
