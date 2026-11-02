"""Every screen at six terminal sizes, empty states included, checked from the rendered layout rather than by eye.

For each (state, size) one app is launched and every screen in `SCREEN_NAMES` is opened in turn. A screen must show:

* no numeric column that collapsed to an ellipsis (a lone `…`, or digits cut with `…`),
* no clipped widget or border title (`clipped_widgets`, plus a border title wider than its box),
* no large reserved-but-empty widget (a leaf widget of 200+ cells and 6+ rows that draws nothing).

The states are the quiet day with its empty outlook, a start with no network (`offline`), and the Erin
replay at a hurricane (`demo`). A check that fails today is a strict `xfail` keyed to its issue (`XFAIL`).
"""

from __future__ import annotations

import re
from collections import defaultdict

import pytest
from rich.cells import cell_len
from textual.screen import Screen

from tests.uat.harness import clipped_widgets
from tests.uat.inventory.registry import World
from tests.uat.inventory.worlds import SCREEN_NAMES, W, launch

SIZES = ((80, 24), (100, 30), (120, 30), (120, 40), (200, 50), (280, 70))
STATES = ("quiet", "offline", "demo")
COLLAPSED = re.compile(r"(?:(?<=\s)|^)…(?=\s|$)|\d[.,]?\d*…")  # a cell that is only "…", or a number cut short
BIG = 200  # cells
TALL = 6  # rows

# (state, screen, check) -> issue: findings that exist today ("*" for any state).
XFAIL: dict[tuple[str, str, str], str] = {
    ("quiet", "graphics", "empty"): "#166",  # the Pictures screen reserves a list and a viewer and says nothing
    ("offline", "graphics", "empty"): "#166",
}


def strips(screen: Screen[object]) -> list[str]:
    return [strip.text for strip in screen._compositor.render_strips()]


def collapsed_numbers(lines: list[str]) -> list[str]:
    return [line.strip() for line in lines if COLLAPSED.search(line)]


def long_titles(screen: Screen[object]) -> list[str]:
    out = []
    for widget in screen.query("*"):
        title = getattr(widget, "border_title", None)
        if title and widget.region.width and cell_len(str(title)) + 4 > widget.region.width:
            out.append(f"{widget!r} title {title!r} in {widget.region.width} cells")
    return out


def reserved_but_empty(screen: Screen[object]) -> list[str]:
    lines = strips(screen)
    out = []
    for widget, (region, _clip) in screen._compositor.visible_widgets.items():
        if widget is screen or widget.children or not region:
            continue
        if region.width * region.height < BIG or region.height < TALL:
            continue
        rows = lines[region.y : region.y + region.height]
        if not any(row[region.x : region.x + region.width].strip() for row in rows):
            out.append(f"{widget!r} {region.width}x{region.height} draws nothing")
    return out


async def findings(w: W, name: str) -> dict[str, list[str]]:
    screen = await w.goto(name)
    return {
        "numbers": collapsed_numbers(strips(screen)),
        "clipped": clipped_widgets(screen) + long_titles(screen),
        "empty": reserved_but_empty(screen),
    }


_SEEN: dict[tuple[str, tuple[int, int]], dict[str, dict[str, list[str]]]] = {}


async def sweep(state: str, size: tuple[int, int]) -> dict[str, dict[str, list[str]]]:
    key = (state, size)
    if key not in _SEEN:
        out: dict[str, dict[str, list[str]]] = defaultdict(dict)
        async with launch(World(state, size)) as w:
            for name in SCREEN_NAMES:
                out[name] = await findings(w, name)
        _SEEN[key] = dict(out)
    return _SEEN[key]


def marks(state: str, name: str, check: str) -> list[pytest.MarkDecorator]:
    issue = XFAIL.get((state, name, check)) or XFAIL.get(("*", name, check))
    return [pytest.mark.xfail(strict=True, raises=AssertionError, reason=issue)] if issue else []


def params(check: str) -> list:
    return [
        pytest.param(state, name, id=f"{state}-{name}", marks=marks(state, name, check))
        for state in STATES
        for name in SCREEN_NAMES
    ]


async def all_sizes(state: str, name: str, check: str) -> list[str]:
    bad = []
    for size in SIZES:
        got = (await sweep(state, size))[name][check]
        bad += [f"{size[0]}x{size[1]}: {item}" for item in got]
    return bad


@pytest.fixture(autouse=True)
def _colour(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)


@pytest.mark.timeout(300)
@pytest.mark.parametrize(("state", "name"), params("numbers"))
async def test_no_numeric_column_collapses_to_an_ellipsis(state: str, name: str) -> None:
    assert not (bad := await all_sizes(state, name, "numbers")), bad[:4]


@pytest.mark.timeout(300)
@pytest.mark.parametrize(("state", "name"), params("clipped"))
async def test_no_title_or_widget_is_clipped(state: str, name: str) -> None:
    assert not (bad := await all_sizes(state, name, "clipped")), bad[:4]


@pytest.mark.timeout(300)
@pytest.mark.parametrize(("state", "name"), params("empty"))
async def test_no_large_widget_is_reserved_and_left_empty(state: str, name: str) -> None:
    assert not (bad := await all_sizes(state, name, "empty")), bad[:4]
