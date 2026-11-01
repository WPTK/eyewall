"""A bounded random walk: keys and clicks in a random order over the app states. After every step there is no exception,
no traceback text, no leaked markup and no control character on the screen. Deterministic in CI (derandomized, fixed step
count); EYEWALL_UAT_NIGHTLY=1 (nightly and tag runs) walks more states with more steps."""

from __future__ import annotations

import asyncio
import os

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.uat.inventory import helpers
from tests.uat.inventory.registry import World
from tests.uat.inventory.rules import CONTROL, MARKUP, RAW
from tests.uat.inventory.worlds import launch

pytestmark = pytest.mark.uat
NIGHTLY = os.environ.get("EYEWALL_UAT_NIGHTLY") == "1"
STEPS = 600 if NIGHTLY else 200
STATES = ("demo", "quiet", "offline", "stale", "busy", "error") if NIGHTLY else ("demo", "offline")
# no ctrl+p, q (quits) and no y/o (clipboard, browser)
KEYS = [
    "j", "k", "enter", "escape", "b", "t", "g", "p", "O", "M", "l", "n", "N", "f", "c", "plus", "minus", "left", "right",
    "up", "down", "tab", "s", "h", "r", "i", "u", "1", "2", "3", "a", "A", "D", "S", "m", "slash", "question_mark", "space",
    "left_square_bracket", "right_square_bracket", "less_than_sign", "greater_than_sign", "backspace", "R",
]  # fmt: skip


async def walk(state: str, draws: list[int]) -> None:
    async with launch(World(state, (120, 30))) as w:
        app = w.app
        app.exit = lambda *a, **k: None  # type: ignore[method-assign]
        trail: list[str] = []
        for n in draws:
            if n % 5 == 0:
                x, y = (n // 5) % w.screen.size.width, (n // 7) % w.screen.size.height
                trail.append(f"click({x},{y})")
                await w.pilot.click(offset=(x, y))
            else:
                key = KEYS[n % len(KEYS)]
                trail.append(key)
                await w.pilot.press(key)
            await w.pilot.pause(0.02)
            text = w.text()
            where = f"{state} step {len(trail)} after {trail[-6:]} on {helpers.top_name(w)}"
            for rule, pattern in (("raw text", RAW), ("markup", MARKUP), ("control character", CONTROL)):
                found = pattern.search(text)
                assert not found, f"{rule} {found.group(0)!r} ({where})"  # type: ignore[union-attr]
            assert not [x for x in app._notifications if x.severity == "error"], f"error toast ({where})"


@pytest.mark.parametrize("state", STATES)
def test_random_walk(state: str) -> None:
    @settings(
        max_examples=1 if not NIGHTLY else 5,
        derandomize=True,
        deadline=None,
        database=None,
        suppress_health_check=list(HealthCheck),
    )
    @given(st.lists(st.integers(min_value=0, max_value=10_000), min_size=STEPS, max_size=STEPS))
    def run(draws: list[int]) -> None:
        asyncio.run(walk(state, draws))

    run()
