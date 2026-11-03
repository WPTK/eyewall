"""WCAG contrast of every text style the app draws, on a dark and on a light terminal.

The screens are rendered (not read from the palette), so a style counts only if it reaches the screen. For each
distinct style (foreground, background, dim) the ratio `(L1 + 0.05) / (L2 + 0.05)` of the two relative luminances is
computed with the sRGB formula of WCAG 2.1. Where a style has no background colour, the terminal's own shows through:
black on the dark profile, white on the light one. Text with letters or digits must reach 4.5:1; glyph-only runs (box
lines, braille map dots, marks) are decorative and need 3:1. `dim` text is blended halfway into the background first.

The command palette and search overlays are left out: a modal dims the screen under it on purpose.

Every style must reach its limit on both profiles. The map, charts and picture gallery paint the app's own background, so
the terminal's never shows through and the two profiles agree. The only exception is in `EXEMPT`, with its reason.
"""

from __future__ import annotations

import asyncio

import pytest

from eyewall import palette
from tests.uat.inventory.registry import World
from tests.uat.inventory.worlds import SCREEN_NAMES, launch

SCREENS = tuple(n for n in SCREEN_NAMES if n not in ("palette", "search"))
PROFILES = {"dark": (0, 0, 0), "light": (255, 255, 255)}
TEXT, DECORATIVE = 4.5, 3.0
IMAGE_CELLS = set("▀▄█ ")  # half and full blocks: how a picture is drawn without graphics support
RGB = tuple[int, int, int]
Style = tuple[RGB | None, RGB | None, bool, str]  # foreground, background, dim, kind ("text", "glyph" or "edge")

# The half-block edges of a layer checkbox are decoration: the box's state is its X and the row's highlight. Scoped to the
# layers screen and those two glyphs, so the same colours anywhere else are still held to the limit.
EDGE_SCREEN, EDGE_GLYPHS = "layers", set("▐▌")
STATES = ("demo", "quiet", "stale", "busy", "error")


def luminance(rgb: RGB) -> float:
    def channel(v: int) -> float:
        c = v / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def ratio(a: RGB, b: RGB) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def blend(fg: RGB, bg: RGB) -> RGB:
    return (round((fg[0] + bg[0]) / 2), round((fg[1] + bg[1]) / 2), round((fg[2] + bg[2]) / 2))


def contrast(style: Style, profile: str) -> float:
    fg, bg, dim, _ = style
    assert fg is not None
    behind = bg or PROFILES[profile]
    return ratio(blend(fg, behind) if dim else fg, behind)


def limit(style: Style) -> float:
    return {"text": TEXT, "glyph": DECORATIVE}.get(style[3], 0.0)


def _rgb(colour) -> RGB:  # type: ignore[no-untyped-def]
    t = colour.get_truecolor()
    return (t.red, t.green, t.blue)


async def _collect() -> dict[Style, str]:
    styles: dict[Style, str] = {}
    for state in STATES:
        async with launch(World(state, (120, 40))) as w:
            for name in SCREENS:
                screen = await w.goto(name)
                for strip in screen._compositor.render_strips():
                    for seg in strip:
                        st = seg.style
                        text = seg.text.strip()
                        if not text or st is None:
                            continue
                        if set(text) <= IMAGE_CELLS:  # picture pixels (half-cell fallback), not text
                            continue
                        kind = "text" if any(ch.isalnum() for ch in text) else "glyph"
                        if name == EDGE_SCREEN and set(text) <= EDGE_GLYPHS:
                            kind = "edge"
                        fg = _rgb(st.color) if st.color else _hex(palette.FOREGROUND)  # unset: the theme's text colour
                        key: Style = (fg, _rgb(st.bgcolor) if st.bgcolor else None, bool(st.dim), kind)
                        styles.setdefault(key, f"{state}:{name} {text[:16]!r}")
    return styles


_STYLES: dict[Style, str] = {}


def styles() -> dict[Style, str]:
    if not _STYLES:
        _STYLES.update(asyncio.run(_collect()))
    return _STYLES


def failing(profile: str) -> dict[Style, float]:
    return {s: c for s in styles() if (c := contrast(s, profile)) < limit(s)}


def describe(profile: str, found: dict[Style, float]) -> list[str]:
    return [
        f"{profile} {s[0]} on {s[1] or 'terminal'}{' dim' if s[2] else ''}: {c:.2f}:1 < {limit(s)} ({styles()[s]})"
        for s, c in sorted(found.items(), key=lambda kv: kv[1])
    ]


@pytest.fixture(autouse=True)
def _colour(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)


@pytest.mark.timeout(900)
@pytest.mark.parametrize("profile", sorted(PROFILES))
def test_no_new_low_contrast_style(profile: str) -> None:
    new = failing(profile)
    assert not new, "\n".join(describe(profile, new))


def _contrast_of(fg: str, bg: str | None = None) -> list[float]:
    """The ratios of every rendered style with this foreground (and background, when given), on both profiles."""
    want_fg = _hex(fg)
    return [
        contrast(s, profile)
        for s in styles()
        for profile in PROFILES
        if s[0] == want_fg and (bg is None or s[1] == _hex(bg))
    ]


def _hex(value: str) -> RGB:
    return (int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16))


@pytest.mark.timeout(900)
def test_172_secondary_text_place_names_and_surge_legend() -> None:
    # Secondary text (selected and other buoy rows), place names on land, and the Storm Surge Warning legend entry.
    for colour in (palette.DIM, palette.MAP_LABEL, palette.WATCH_WARNING_COLORS[palette.WatchWarning.SURGE_WARNING]):
        ratios = _contrast_of(colour)
        assert ratios, f"{colour} is no longer drawn: update this test"
        assert min(ratios) >= TEXT, (colour, min(ratios))
    # The selected buoy row is a lighter background than the app's: DIM is drawn there too.
    assert any(s[1] not in (None, _hex(palette.BACKGROUND)) for s in styles() if s[0] == _hex(palette.DIM))
    assert ratio(_hex(palette.MAP_LABEL), _hex(palette.LAND)) >= TEXT  # place names over land


@pytest.mark.timeout(900)
def test_173_rules_tracks_and_map_lines_reach_3_to_1() -> None:
    for colour in (palette.STATE_LINE, palette.BORDER, palette.CHART_GRID):
        ratios = _contrast_of(colour)
        assert ratios, f"{colour} is no longer drawn: update this test"
        assert min(ratios) >= DECORATIVE, (colour, min(ratios))
    for profile in PROFILES:
        low = [s for s in styles() if s[3] == "glyph" and contrast(s, profile) < DECORATIVE]
        assert low == [], profile


@pytest.mark.timeout(900)
def test_174_nothing_depends_on_the_terminal_background() -> None:
    bare = [s for s in styles() if s[1] is None]
    assert not bare, [f"{s[0]} {styles()[s]}" for s in bare]
    assert {s: contrast(s, "dark") for s in styles()} == {s: contrast(s, "light") for s in styles()}


def test_the_ratio_matches_the_wcag_examples() -> None:
    assert ratio((0, 0, 0), (255, 255, 255)) == pytest.approx(21.0)
    assert ratio((119, 119, 119), (255, 255, 255)) == pytest.approx(4.48, abs=0.01)  # #777 on white: just short of AA
    assert ratio((255, 255, 255), (255, 255, 255)) == pytest.approx(1.0)


# Each palette colour against every background it is drawn on, at the limit its use needs (text 4.5, a mark 3).
SURFACES = {"background": palette.BACKGROUND, "surface": palette.SURFACE, "panel": palette.PANEL}
TEXT_COLOURS = {
    "FOREGROUND": palette.FOREGROUND,
    "DIM": palette.DIM,
    "HEADING": palette.HEADING,
    "NEUTRAL": palette.NEUTRAL,
    "GOOD": palette.GOOD,
    "WARN": palette.WARN,
    "BAD": palette.BAD,
    "INFO": palette.INFO,
    "STALE": palette.STALE,  # a stale station's id label
    "MAP_LABEL": palette.MAP_LABEL,
    **{f"{k.value}": c for k, c in palette.WATCH_WARNING_COLORS.items()},
    **{f"{k.value}": c for k, c in palette.CATEGORY_COLORS.items()},
    **{f"risk {k}": c for k, c in palette.RISK_COLORS.items()},
    **{f"freshness {k}": cue.color for k, cue in palette.FRESHNESS_CUES.items()},
}
MAP_BACKGROUNDS = {"background": palette.BACKGROUND, "land": palette.LAND}
MARK_COLOURS = {
    "STALE": palette.STALE,
    "STATE_LINE": palette.STATE_LINE,
    "BORDER": palette.BORDER,
    "COAST": palette.COAST,
    "FIELD_EDGE": palette.FIELD_EDGE,
    "BUOY": palette.BUOY,
    "TIDE_GAUGE": palette.TIDE_GAUGE,
}


@pytest.mark.parametrize("surface", sorted(SURFACES))
@pytest.mark.parametrize("name", sorted(TEXT_COLOURS))
def test_text_colour_reaches_4_5_on_every_surface(name: str, surface: str) -> None:
    assert ratio(_hex(TEXT_COLOURS[name]), _hex(SURFACES[surface])) >= TEXT


@pytest.mark.parametrize("surface", sorted(MAP_BACKGROUNDS))
@pytest.mark.parametrize("name", sorted(MARK_COLOURS))
def test_mark_colour_reaches_3_on_the_map(name: str, surface: str) -> None:
    assert ratio(_hex(MARK_COLOURS[name]), _hex(MAP_BACKGROUNDS[surface])) >= DECORATIVE


@pytest.mark.parametrize("name", ["CHART_GRID"])
def test_chart_furniture_reaches_3_on_the_background(name: str) -> None:
    assert ratio(_hex(getattr(palette, name)), _hex(palette.BACKGROUND)) >= DECORATIVE
