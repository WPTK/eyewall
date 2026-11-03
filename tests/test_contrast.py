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
Style = tuple[RGB | None, RGB | None, bool, str]  # foreground, background, dim, kind ("text" or "glyph")

# (foreground, background) -> why it is not information. Explicit backgrounds are the same on both profiles.
EXEMPT: dict[tuple[RGB, RGB | None], str] = {
    # The left edge of a layer checkbox on the highlighted row: the box's state is its X and the row's highlight.
    ((18, 26, 36), (28, 36, 46)): "checkbox edge",
}


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
    return TEXT if style[3] == "text" else DECORATIVE


def _rgb(colour) -> RGB:  # type: ignore[no-untyped-def]
    t = colour.get_truecolor()
    return (t.red, t.green, t.blue)


async def _collect() -> dict[Style, str]:
    styles: dict[Style, str] = {}
    for state in ("demo", "quiet"):
        async with launch(World(state, (120, 40))) as w:
            for name in SCREENS:
                screen = await w.goto(name)
                for strip in screen._compositor.render_strips():
                    for seg in strip:
                        st = seg.style
                        text = seg.text.strip()
                        if not text or st is None or st.color is None:
                            continue
                        if set(text) <= IMAGE_CELLS:  # picture pixels (half-cell fallback), not text
                            continue
                        kind = "text" if any(ch.isalnum() for ch in text) else "glyph"
                        key: Style = (_rgb(st.color), _rgb(st.bgcolor) if st.bgcolor else None, bool(st.dim), kind)
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


@pytest.mark.timeout(300)
@pytest.mark.parametrize("profile", sorted(PROFILES))
def test_no_new_low_contrast_style(profile: str) -> None:
    new = {s: c for s, c in failing(profile).items() if (s[0], s[1]) not in EXEMPT}
    assert not new, "\n".join(describe(profile, new))


@pytest.mark.timeout(300)
def test_an_exemption_is_still_needed() -> None:
    low = {(s[0], s[1]) for profile in PROFILES for s in failing(profile)}
    stale = [f"{key} ({why}) now passes: remove it from EXEMPT" for key, why in EXEMPT.items() if key not in low]
    assert not stale, stale


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


@pytest.mark.timeout(300)
def test_172_secondary_text_place_names_and_surge_legend() -> None:
    # Secondary text (selected and other buoy rows), place names on land, and the Storm Surge Warning legend entry.
    for colour in (palette.DIM, palette.MAP_LABEL, palette.WATCH_WARNING_COLORS[palette.WatchWarning.SURGE_WARNING]):
        ratios = _contrast_of(colour)
        assert ratios, f"{colour} is no longer drawn: update this test"
        assert min(ratios) >= TEXT, (colour, min(ratios))
    assert ratio(_hex(palette.DIM), (55, 65, 78)) >= TEXT  # the selected buoy row
    assert ratio(_hex(palette.MAP_LABEL), _hex(palette.LAND)) >= TEXT  # place names over land


@pytest.mark.timeout(300)
def test_173_rules_tracks_and_map_lines_reach_3_to_1() -> None:
    for colour in (palette.STATE_LINE, palette.BORDER, palette.CHART_GRID):
        ratios = _contrast_of(colour)
        assert ratios, f"{colour} is no longer drawn: update this test"
        assert min(ratios) >= DECORATIVE, (colour, min(ratios))
    glyphs = [(s, c) for s, c in ((s, contrast(s, "dark")) for s in styles()) if s[3] == "glyph"]
    assert [s for s, c in glyphs if c < DECORATIVE and (s[0], s[1]) not in EXEMPT] == []


@pytest.mark.timeout(300)
def test_174_nothing_depends_on_the_terminal_background() -> None:
    bare = [s for s in styles() if s[1] is None]
    assert not bare, [f"{s[0]} {styles()[s]}" for s in bare]
    assert {s: contrast(s, "dark") for s in styles()} == {s: contrast(s, "light") for s in styles()}


def test_the_ratio_matches_the_wcag_examples() -> None:
    assert ratio((0, 0, 0), (255, 255, 255)) == pytest.approx(21.0)
    assert ratio((119, 119, 119), (255, 255, 255)) == pytest.approx(4.48, abs=0.01)  # #777 on white: just short of AA
    assert ratio((255, 255, 255), (255, 255, 255)) == pytest.approx(1.0)
