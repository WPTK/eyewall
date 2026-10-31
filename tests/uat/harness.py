"""The UAT harness: drive the real app with Textual's Pilot, check every step and save a screenshot of it.

A `Journey` wraps one app run at one terminal size. `shot()` waits for the screen to settle, runs the checks that apply
to every screen (no error toast, no logged error, nothing clipped, a one-row footer that ends in `? help`) and writes the
screen to an SVG named `<scenario>-<WxH>-<NN>-<step>.svg`. Nothing here reads the wall clock: the replay is paused and
time only moves when a test calls the poller itself.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from rich.cells import cell_len
from textual.pilot import Pilot
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import TabbedContent, Tabs

from eyewall.app import EyewallApp
from eyewall.ui.screens.small import TooSmallScreen
from tests.ui_support import press, screen_text, settle

SIZES = [(80, 24), (120, 30)]  # the floor and the main size; most scenarios run at both
EXTRA_SIZES = [(100, 50), (200, 50), (280, 70)]  # tall-narrow and large terminals, for the every-screen sweep
STATUS_IDS = ("#status", "#detail-status", "#buoy-status", "#graphics-status", "#outlook-status", "#watch-status")
SCROLLING = ("auto", "scroll")


def size_id(size: tuple[int, int]) -> str:
    return f"{size[0]}x{size[1]}"


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def status_widgets(screen: Screen[object]) -> list[Widget]:
    return [w for sel in STATUS_IDS for w in screen.query(sel)]


def _scrolls(widget: Widget, stop: Widget) -> bool:
    """True when the widget sits inside something that scrolls, so being cut off there is expected."""
    for ancestor in widget.ancestors_with_self:
        if ancestor is stop:
            return False
        if ancestor is not widget and (
            isinstance(ancestor, Tabs)  # a tab strip wider than the terminal scrolls to the active tab
            or ancestor.styles.overflow_y in SCROLLING
            or ancestor.styles.overflow_x in SCROLLING
        ):
            return True
    return False


def clipped_widgets(screen: Screen[object]) -> list[str]:
    """Visible widgets that do not fit where the layout put them: cut off by their parent or by the screen edge.

    Content inside a scrolling container is left out, since a scroll view is meant to hide part of what it holds.
    """
    problems: list[str] = []
    bounds = screen.region
    for widget, (region, clip) in screen._compositor.visible_widgets.items():
        if widget is screen or not region or _scrolls(widget, screen):
            continue
        full = widget.region
        if not full or full.width == 0 or full.height == 0:
            continue
        if not clip.contains_region(full) or not bounds.contains_region(full):
            problems.append(f"{widget!r} region={full} visible={region.intersection(clip)} screen={bounds}")
    return problems


@dataclass
class Journey:
    app: EyewallApp
    pilot: Pilot[None]
    scenario: str
    size: tuple[int, int]
    out: Path
    caplog: object
    shots: list[Path] = field(default_factory=list)
    expect_small: bool = False

    # ---- driving --------------------------------------------------------------------------------------------

    async def keys(self, *keys: str) -> None:
        await press(self.pilot, *keys)

    async def settle(self) -> None:
        await settle(self.pilot)

    async def resize(self, width: int, height: int) -> None:
        self.size = (width, height)
        await self.pilot.resize_terminal(width, height)
        await self.settle()

    # ---- looking --------------------------------------------------------------------------------------------

    @property
    def screen(self) -> Screen[object]:
        return self.app.screen

    def text(self) -> str:
        return screen_text(self.app)

    def bottom(self) -> str:
        return self.text().splitlines()[-1]

    def notifications(self) -> list[tuple[str, str]]:
        return [(n.severity, n.message) for n in self.app._notifications]

    def toasts(self) -> str:
        return " | ".join(message for _, message in self.notifications())

    # ---- checks ---------------------------------------------------------------------------------------------

    def check(self, *, footer: bool = True) -> None:
        errors = [message for severity, message in self.notifications() if severity == "error"]
        assert not errors, f"error toasts: {errors}"
        logged = [r for r in self.caplog.records if r.levelno >= logging.ERROR]  # type: ignore[attr-defined]
        assert not logged, f"errors in the app log: {[r.getMessage() for r in logged]}"
        if isinstance(self.screen, TooSmallScreen) and not self.expect_small:
            raise AssertionError(f"the 'too small' screen is showing at {self.size}")
        assert not clipped_widgets(self.screen), "clipped or overflowing widgets:\n" + "\n".join(
            clipped_widgets(self.screen)
        )
        if footer:
            self.check_footer()

    def check_footer(self) -> None:
        """Where a screen has a status row: it is one row high, fits the width and ends with `? help`."""
        widgets = status_widgets(self.screen)
        if not widgets:
            return
        for widget in widgets:
            assert widget.region.height == 1, f"{widget!r} is {widget.region.height} rows high"
            assert widget.region.width == self.size[0], f"{widget!r} is {widget.region.width} wide"
        row = self.bottom().rstrip()
        assert cell_len(row) <= self.size[0], f"footer wider than the terminal: {row!r}"
        assert row.endswith("? help"), f"footer does not end in '? help': {row!r}"
        assert "\n" not in row

    def tab(self) -> str:
        tabs = self.screen.query_one(TabbedContent)
        return (tabs.active or "").removeprefix("tab-")

    async def shot(self, step: str, *, footer: bool = True, check: bool = True) -> Path:
        """Settle, check the screen and write the screenshot; returns the SVG path."""
        await self.settle()
        if check:
            self.check(footer=footer)
        path = self.out / f"{self.scenario}-{size_id(self.size)}-{len(self.shots) + 1:02d}-{slug(step)}.svg"
        path.write_text(self.app.export_screenshot(title=f"{self.scenario} {step}"), encoding="utf-8", newline="\n")
        self.shots.append(path)
        return path

    # ---- assertions with the screen text in the message -----------------------------------------------------

    def see(self, *needles: str) -> None:
        text = self.text()
        missing = [n for n in needles if n not in text]
        assert not missing, f"not on screen: {missing}\n{text}"

    def not_see(self, *needles: str) -> None:
        text = self.text()
        found = [n for n in needles if n in text]
        assert not found, f"unexpectedly on screen: {found}\n{text}"

    def footer_has(self, *keys: str) -> None:
        row = self.bottom()
        missing = [k for k in keys if k not in row]
        assert not missing, f"footer lacks {missing}: {row!r}"


def all_texts(items: Iterable[object]) -> str:
    return "\n".join(str(item) for item in items)
