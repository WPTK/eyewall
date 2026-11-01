"""Negative and boundary cases, one or more per workflow: too small a terminal, no search hit, a dead network that comes
back, NO_COLOR."""

from __future__ import annotations

import os

import pytest
from textual.widgets import Input

from eyewall.app import EyewallApp
from eyewall.config import Config
from tests.uat.inventory.registry import World
from tests.uat.inventory.rules import MARKUP, RAW
from tests.uat.inventory.worlds import launch
from tests.ui_support import EDT, ScriptedSource, screen_text, settle

pytestmark = pytest.mark.uat


async def test_too_small_terminal() -> None:
    app = EyewallApp(Config(), ScriptedSource(), local_tz=EDT)
    async with app.run_test(size=(50, 12)) as pilot:
        await pilot.pause(0.5)
        await settle(pilot)
        text = screen_text(app)
    assert "60" in text and "16" in text, f"the too-small message does not say the size needed:\n{text}"
    assert not RAW.search(text) and not MARKUP.search(text), text


async def test_search_no_match() -> None:
    async with launch(World("demo", (120, 30))) as w:
        await w.goto("main")
        await w.pilot.press("slash")
        await w.pilot.pause(0.3)
        w.screen.query_one(Input).value = "zzzzqqqq"
        await w.pilot.pause(0.6)
        await w.pilot.press("enter")
        await w.settle()
        assert not RAW.search(w.text()), w.text()
        assert not [n for n in w.app._notifications if n.severity == "error"]


async def test_offline_recovers() -> None:
    """A broken poll shows a failing state, and when the feeds answer again the screens go back to normal."""
    async with launch(World("error", (120, 30))) as w:
        before = w.app.health().word
        assert "fail" in before or "late" in before or "offline" in before, before
        clock = w.app.poller.clock
        w.app.source.fail = None  # type: ignore[attr-defined]
        clock.offset += 3600.0  # type: ignore[attr-defined]  # past the back-off, which is by design
        await w.press("r")
        for _ in range(60):
            await w.pilot.pause(0.2)
            if w.app.health().word == "data ok":
                break
        assert w.app.health().word == "data ok", f"still {w.app.health().word!r} after the feeds came back"


async def test_no_color_and_ascii() -> None:
    old = os.environ.get("NO_COLOR")
    os.environ["NO_COLOR"] = "1"
    try:
        app = EyewallApp(Config(), ScriptedSource(), local_tz=EDT)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.5)
            await settle(pilot)
            text = screen_text(app)
        assert text.strip() and not RAW.search(text), text
    finally:
        if old is None:
            os.environ.pop("NO_COLOR", None)
        else:
            os.environ["NO_COLOR"] = old
