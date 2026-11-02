"""WCAG contrast of every text style the app draws, on a dark and on a light terminal.

The screens are rendered (not read from the palette), so a style counts only if it reaches the screen. For each
distinct style (foreground, background, dim) the ratio `(L1 + 0.05) / (L2 + 0.05)` of the two relative luminances is
computed with the sRGB formula of WCAG 2.1. Where a style has no background colour, the terminal's own shows through:
black on the dark profile, white on the light one. Text with letters or digits must reach 4.5:1; glyph-only runs (box
lines, braille map dots, marks) are decorative and need 3:1. `dim` text is blended halfway into the background first.

The command palette and search overlays are left out: a modal dims the screen under it on purpose.

A style below its limit that exists today is listed in `KNOWN` against its issue (`LIGHT_ISSUE` for the whole light
profile without a background). `test_no_new_low_contrast_style` fails for any other, and `test_a_known_style_still_fails`
fails when a listed one no longer does, so the entry gets removed
with the fix (a strict xfail in two halves, since the set of styles is found by rendering, not written down).
"""

from __future__ import annotations

import asyncio

import pytest

from tests.uat.inventory.registry import World
from tests.uat.inventory.worlds import SCREEN_NAMES, launch

SCREENS = tuple(n for n in SCREEN_NAMES if n not in ("palette", "search"))
PROFILES = {"dark": (0, 0, 0), "light": (255, 255, 255)}
TEXT, DECORATIVE = 4.5, 3.0
RGB = tuple[int, int, int]
Style = tuple[RGB | None, RGB | None, bool, str]  # foreground, background, dim, kind ("text" or "glyph")

# (foreground, background) -> issue; a background of None is the terminal's own. Explicit backgrounds are the same on
# both profiles, so one entry covers both.
KNOWN: dict[tuple[RGB, RGB | None], str] = {
    ((125, 138, 153), (55, 65, 78)): "#172",  # secondary text in the selected buoy row
    ((125, 138, 153), (28, 36, 46)): "#172",
    ((154, 164, 178), (58, 70, 88)): "#172",  # place names on the map
    ((155, 77, 255), (13, 17, 23)): "#172",  # Storm Surge Warning in the legend
    ((12, 20, 30), (18, 26, 36)): "#173",  # rules, tracks and dim map layers
    ((18, 26, 36), (28, 36, 46)): "#173",
    ((12, 20, 30), (23, 33, 45)): "#173",
    ((34, 39, 45), (13, 17, 23)): "#173",
    ((74, 86, 104), (58, 70, 88)): "#173",
    ((43, 53, 68), None): "#173",
    ((110, 127, 148), (58, 70, 88)): "#173",
    ((46, 94, 145), (18, 26, 36)): "#173",
    ((43, 90, 139), (13, 17, 23)): "#173",
}
# Any style drawn without a background of its own on the light profile: the colours were picked for dark terminals.
LIGHT_ISSUE: str = "#174"


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
                        kind = "text" if any(ch.isalnum() for ch in text) else "glyph"
                        key: Style = (_rgb(st.color), _rgb(st.bgcolor) if st.bgcolor else None, bool(st.dim), kind)
                        styles.setdefault(key, f"{state}:{name} {text[:16]!r}")
    return styles


_STYLES: dict[Style, str] = {}


def styles() -> dict[Style, str]:
    if not _STYLES:
        _STYLES.update(asyncio.run(_collect()))
    return _STYLES


def issue_of(profile: str, style: Style) -> str | None:
    fg, bg = style[0], style[1]
    assert fg is not None
    if profile == "light" and bg is None:
        return LIGHT_ISSUE
    return KNOWN.get((fg, bg))


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
    new = {s: c for s, c in failing(profile).items() if issue_of(profile, s) is None}
    assert not new, "\n".join(describe(profile, new))


@pytest.mark.timeout(300)
def test_a_known_style_still_fails() -> None:
    low = {(s[0], s[1]) for profile in PROFILES for s in failing(profile)}
    fixed = [f"{key} ({issue}) now passes: remove it from KNOWN" for key, issue in KNOWN.items() if key not in low]
    if not any(s[1] is None for s in failing("light")):
        fixed.append(f"no style without a background fails on light: remove LIGHT_ISSUE ({LIGHT_ISSUE})")
    assert not fixed, fixed


def test_the_ratio_matches_the_wcag_examples() -> None:
    assert ratio((0, 0, 0), (255, 255, 255)) == pytest.approx(21.0)
    assert ratio((119, 119, 119), (255, 255, 255)) == pytest.approx(4.48, abs=0.01)  # #777 on white: just short of AA
    assert ratio((255, 255, 255), (255, 255, 255)) == pytest.approx(1.0)
