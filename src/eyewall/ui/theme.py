"""The Textual theme. Every color in it comes from `eyewall.palette`."""

from __future__ import annotations

from textual.theme import Theme

from eyewall.palette import (
    ACCENT,
    BACKGROUND,
    BAD,
    FOREGROUND,
    GOOD,
    HEADING,
    INFO,
    PANEL,
    SURFACE,
    WARN,
)

THEME_NAME = "eyewall"

EYEWALL_THEME = Theme(
    name=THEME_NAME,
    primary=INFO,
    secondary=HEADING,
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
