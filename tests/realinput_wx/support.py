"""Helpers shared by the real-terminal tests."""

from __future__ import annotations

from typing import Any

from tests.uat_kit_wx.ew_driver import Run

NHC = "www.nhc.noaa.gov"
STAR = "cdn.star.nesdis.noaa.gov"


class Precondition(RuntimeError):
    """The scene a test needs did not come up. Not an AssertionError, so a strict xfail cannot swallow it."""


def require(condition: Any, message: str) -> None:
    if not condition:
        raise Precondition(message)


def body(r: Run) -> str:
    """The screen below the top bar: the header carries a clock and a data age that move on their own."""
    return "\n".join(r.lines()[1:])


def demo_paused(exe: Any, cols: int = 120, rows: int = 30) -> Run:
    """A ``--demo`` launch at the Home screen with the replay clock paused, so the map cannot move by itself."""
    r = Run("wx", exe, ["--demo"], cols, rows)
    require(r.wait_text("Erin", 60), "the demo did not reach Home with Erin:\n" + r.dump())
    r.settle(1.0)
    r.key("space")
    return r
