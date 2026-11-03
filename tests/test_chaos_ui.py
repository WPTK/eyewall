"""A random user at a random terminal size while the feeds change under the app (issue #148, audit #183).

A hypothesis state machine drives the headless app with real key presses, resizes and clicks, and swaps the feed among
no storms, one, a three-basin outbreak, a post-tropical remnant with nothing in it and a dead network. After every step
the app must be running, must not have reported a failure, must not be on an error screen, and focus must be on a widget
that can be seen.

The default run is short enough for every CI job. `EYEWALL_FUZZ=long` (the tag-time run) is about ten times longer.
Defects the run found are pinned in `test_chaos_known_ui.py` as strict xfails, one per issue: when the fix merges the
xfail passes, strict mode fails the test, and the mark is deleted with the fix.
"""

from __future__ import annotations

import asyncio
import os
import webbrowser
from collections.abc import Awaitable
from contextlib import suppress
from typing import Any
from unittest import mock

from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule
from textual.widget import Widget

from eyewall.app import EyewallApp
from eyewall.ui import nav
from tests.chaos_support import STATES, MutableSource
from tests.ui_support import scripted_app

LONG = os.environ.get("EYEWALL_FUZZ") == "long"
SIZES = ((60, 16), (80, 24), (120, 40), (200, 60), (59, 15))
MINIMUM = (60, 16)
EXTRA_KEYS = {"tab", "shift+tab", "up", "down", "left", "right", "enter", "escape", "space", "pageup", "pagedown"}
# q and R leave the app on purpose; ctrl+s writes the config file.
KEYS = sorted(({key for entry in nav.KEYS for key in entry.key_list} | EXTRA_KEYS) - {"q", "R", "ctrl+s"})
# Issue #182: these two are focused and then hidden. Their ids are skipped by the focus check until the fix merges.
KNOWN_HIDDEN_FOCUS = {"buoys-list", "station-readings"}


def run[T](loop: asyncio.AbstractEventLoop, awaitable: Awaitable[T], app: EyewallApp | None = None) -> T:
    """Run one step to completion. `pilot.pause()` renders inline, so the step runs with the app's context variables set
    (`active_app`), as they are inside the app's own tasks; without them a render landing in the step raises LookupError."""

    async def step() -> T:
        if app is None:
            return await awaitable
        with app._context():
            return await awaitable

    return loop.run_until_complete(asyncio.wait_for(step(), 60))


def shown(widget: Widget) -> bool:
    node: Widget | None = widget
    while node is not None:
        if not node.display:
            return False
        node = node.parent  # type: ignore[assignment]
    return True


class UserAtTheTerminal(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.loop = asyncio.new_event_loop()
        self.source = MutableSource()
        self.app: EyewallApp = scripted_app(self.source)
        self.reported: list[str] = []
        original = self.app._report_failure
        self.app._report_failure = lambda where: (self.reported.append(where), original(where))  # type: ignore[method-assign]
        self.patches = [
            mock.patch.object(EyewallApp, "_save", lambda self, new: True),
            mock.patch.object(webbrowser, "open", lambda *a, **k: True),
        ]
        for patch in self.patches:
            patch.start()
        self.size = (120, 40)
        self.context = self.app.run_test(size=self.size)
        self.pilot = run(self.loop, self.context.__aenter__())
        run(self.loop, self.pilot.pause(), self.app)
        run(self.loop, self.app.first_poll.wait(), self.app)

    def teardown(self) -> None:
        with suppress(Exception):
            run(self.loop, self.context.__aexit__(None, None, None))
        for patch in self.patches:
            patch.stop()
        self.loop.close()

    @property
    def small(self) -> bool:
        return self.size[0] < MINIMUM[0] or self.size[1] < MINIMUM[1]

    # Issue #179: a screen above the main one cannot survive the terminal shrinking and growing again. So the terminal
    # shrinks below the minimum only from the main screen, and no key or click reaches the app while it is too small.
    @precondition(lambda self: not self.small)
    @rule(key=st.sampled_from(KEYS))
    def press(self, key: str) -> None:
        run(self.loop, self.pilot.press(key), self.app)

    @rule(size=st.sampled_from(SIZES))
    def resize(self, size: tuple[int, int]) -> None:
        shrinking = size[0] < MINIMUM[0] or size[1] < MINIMUM[1]
        if shrinking and len(self.app.screen_stack) > 2:
            return
        self.size = size
        run(self.loop, self.pilot.resize_terminal(*size), self.app)

    @rule(state=st.sampled_from(STATES))
    def swap_feed(self, state: str) -> None:
        self.source.set_state(state)

        async def poll() -> None:
            async with self.app._tick_lock:
                self.app.poller.refresh()
                await self.app.poller.tick()

        run(self.loop, poll(), self.app)

    @precondition(lambda self: not self.small)
    @rule(x=st.integers(0, 199), y=st.integers(0, 58))
    def click(self, x: int, y: int) -> None:
        width, height = self.size
        run(self.loop, self.pilot.click(offset=(x % width, y % (height - 1))), self.app)  # not the footer: q, R exit

    @invariant()
    def the_app_is_alive_and_has_not_reported_a_failure(self) -> None:
        run(self.loop, self.pilot.pause(0.02), self.app)
        assert self.app.is_running, "the app stopped"
        assert self.app._exception is None, repr(self.app._exception)
        assert not self.reported, self.reported
        assert "Error" not in type(self.app.screen).__name__

    @invariant()
    def at_most_one_too_small_notice(self) -> None:
        stacked = [s for s in self.app.screen_stack if type(s).__name__ == "TooSmallScreen"]
        assert len(stacked) <= 1, stacked

    @invariant()
    def focus_is_on_something_visible(self) -> None:
        focused = self.app.focused
        if focused is None or getattr(focused, "id", None) in KNOWN_HIDDEN_FOCUS:
            return
        assert focused.is_attached and shown(focused), f"focus on a hidden {focused!r}"


UserAtTheTerminal.TestCase.settings = settings(
    max_examples=40 if LONG else 4,
    stateful_step_count=80 if LONG else 20,
    deadline=None,
    suppress_health_check=list(HealthCheck),
    derandomize=not LONG,  # the CI run is the same every time; the tag-time run explores
)
TestUserAtTheTerminal: Any = UserAtTheTerminal.TestCase
