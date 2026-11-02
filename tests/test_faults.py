"""One broken NOAA host at a time, under the real source, parsers and screens (`tests/fault_support.py`).

Each data panel is run against four fault modes: the request times out, the host answers 500, answers 200 with half a
JSON document, or answers 200 with nothing. What a person sees is then checked, not the code path:

* the panel says in words that the data is missing, and the top bar says a feed is failing, within `WITHIN` seconds;
* the Feeds dialog (`D`) says when the next try is, and `r` asks the host again;
* nothing on screen, in a toast or in the Feeds dialog carries exception text or a web address.

A panel that fails a check today is a strict `xfail` named after its issue (`XFAIL`), so fixing it fails the run until
the entry is removed. `alerts` (api.weather.gov) is polled only during a US threat, which no saved storm has;
`test_feed_failures.py` covers it below the screen. The cold-start tests give every host a slow answer and check that
the view changes with no key pressed.
"""

from __future__ import annotations

import asyncio
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.fault_support import COOPS, MODES, NDBC, NHC, STAR, TGFTP, Wire, quick_retries, wire_app
from tests.ui_support import screen_text, settle

WITHIN = 20.0  # seconds from the start of the app to the panel saying so
LEAK = re.compile(r"Error|Exception|Traceback|https?://")


@dataclass(frozen=True)
class Panel:
    name: str
    host: str
    keys: tuple[str, ...]  # from Home to the panel
    storm: bool  # the saved storm is current (a storm world) or the quiet day
    says: str  # what the panel shows when its data could not be had


PANELS = (
    Panel("storms", NHC, (), False, "Storm data unavailable"),
    Panel("outlook", TGFTP, ("t",), False, "Could not fetch the tropical weather outlook"),
    Panel("buoys", NDBC, ("b",), False, "Buoy data unavailable"),
    Panel("tides", COOPS, ("b",), False, "Tide data unavailable"),
    Panel("pictures", STAR, ("g",), True, "Pictures unavailable"),
)

# (panel, mode or "*", check) -> issue: checks that fail today.
XFAIL: dict[tuple[str, str, str], str] = {
    ("tides", "*", "says"): "#170",  # gauge rows wait forever and never say why
    ("pictures", "*", "says"): "#166",  # the Pictures screen is blank with no message
    ("outlook", "empty", "says"): "#171",  # an empty 200 reads as "no outlook"
    ("outlook", "empty", "header"): "#171",
    ("outlook", "empty", "feeds"): "#171",
    **{
        (panel.name, mode, "retry"): "#164" for panel in PANELS for mode in ("timeout", "http-500", "bad-json", "empty")
    },
    **{
        (panel, mode, check): "#171"
        for panel in ("pictures",)
        for mode in ("bad-json", "empty")
        for check in ("header", "feeds", "retry")
    },
}


def issue_for(panel: str, mode: str, check: str) -> str | None:
    return XFAIL.get((panel, mode, check)) or XFAIL.get((panel, "*", check))


@dataclass
class Seen:
    header: str = ""
    panel: str = ""
    feeds: str = ""
    toasts: str = ""
    seconds: float = 0.0
    asked: int = 0  # requests to the host before `r`
    asked_after: int = 0  # and after


def _notes(app) -> str:  # type: ignore[no-untyped-def]
    return "\n".join(str(getattr(n, "message", n)) for n in getattr(app, "_notifications", ()))


async def _observe(panel: Panel, mode: str | None) -> Seen:
    seen = Seen()
    with tempfile.TemporaryDirectory() as tmp:
        wire = Wire({panel.host: mode} if mode else {}, storm=panel.storm)
        started = time.monotonic()
        async with wire_app(wire, Path(tmp), (120, 30), storm=panel.storm) as (app, pilot):
            await asyncio.wait_for(app.first_poll.wait(), WITHIN)
            await settle(pilot)
            for key in panel.keys:
                await pilot.press(key)
                await settle(pilot)
            seen.seconds = time.monotonic() - started
            lines = screen_text(app).splitlines()
            seen.header, seen.panel = lines[0], "\n".join(lines)
            seen.toasts = _notes(app)
            await pilot.press("D")
            await settle(pilot)
            seen.feeds = screen_text(app)
            await pilot.press("escape")
            await settle(pilot)
            seen.asked = wire.count(panel.host)
            await pilot.press("r")
            await settle(pilot)
            await pilot.pause(0.5)
            seen.asked_after = wire.count(panel.host)
    return seen


_CACHE: dict[tuple[str, str | None], Seen] = {}


def seen(panel: Panel, mode: str | None) -> Seen:
    """One run per (panel, mode), shared by every check of it."""
    key = (panel.name, mode)
    if key not in _CACHE:
        _CACHE[key] = asyncio.run(_observe(panel, mode))
    return _CACHE[key]


@pytest.fixture(autouse=True)
def _fast(monkeypatch):  # type: ignore[no-untyped-def]
    quick_retries(monkeypatch)


def cases(check: str) -> list:
    out = []
    for panel in PANELS:
        for mode in MODES:
            issue = issue_for(panel.name, mode, check)
            marks = [pytest.mark.xfail(strict=True, raises=AssertionError, reason=issue)] if issue else []
            out.append(pytest.param(panel, mode, id=f"{panel.name}-{mode}", marks=marks))
    return out


@pytest.mark.parametrize(("panel", "mode"), cases("says"))
def test_the_panel_says_the_data_is_missing(panel: Panel, mode: str) -> None:
    assert panel.says in seen(panel, mode).panel, f"no '{panel.says}' on the {panel.name} screen"


@pytest.mark.parametrize(("panel", "mode"), cases("header"))
def test_the_top_bar_says_a_feed_is_failing_within_seconds(panel: Panel, mode: str) -> None:
    got = seen(panel, mode)
    assert "failing" in got.header, f"top bar: {got.header.strip()[-40:]!r}"
    assert got.seconds <= WITHIN, f"{got.seconds:.1f} s"


@pytest.mark.parametrize(("panel", "mode"), cases("feeds"))
def test_the_feeds_dialog_says_when_the_next_try_is(panel: Panel, mode: str) -> None:
    assert "retrying in" in seen(panel, mode).feeds, "the Feeds dialog does not say when it tries again"


@pytest.mark.parametrize(("panel", "mode"), cases("retry"))
def test_r_asks_the_failing_host_again(panel: Panel, mode: str) -> None:
    got = seen(panel, mode)
    assert got.asked_after > got.asked, f"r made no request to {panel.host} ({got.asked} before and after)"


@pytest.mark.parametrize(("panel", "mode"), cases("leak"))
def test_no_exception_text_or_web_address_reaches_the_screen(panel: Panel, mode: str) -> None:
    got, healthy = seen(panel, mode), seen(panel, None)
    base = set((healthy.panel + "\n" + healthy.feeds).splitlines())
    shown = [
        line
        for line in (got.panel + "\n" + got.feeds + "\n" + got.toasts).splitlines()
        if line not in base and LEAK.search(line)
    ]
    assert not shown, f"{shown[:3]}"


@pytest.mark.parametrize("panel", PANELS, ids=lambda p: p.name)
def test_a_healthy_run_has_no_failing_feed(panel: Panel) -> None:
    got = seen(panel, None)
    assert "failing" not in got.header, got.header


# ---- a slow first answer -----------------------------------------------------------------------------------------


async def _cold_start(delay: float) -> tuple[str, str, float]:
    with tempfile.TemporaryDirectory() as tmp:
        wire = Wire(delay=delay)
        async with wire_app(wire, Path(tmp), (120, 30)) as (app, pilot):
            first = screen_text(app).splitlines()[1]
            started = time.monotonic()
            while not app.first_poll.is_set() and time.monotonic() - started < delay + WITHIN:
                await pilot.pause(0.25)  # no key is pressed: the view must change by itself
            await settle(pilot)
            return first, screen_text(app).splitlines()[1], time.monotonic() - started


@pytest.mark.parametrize("delay", [5.0, 20.0])
def test_a_slow_first_answer_updates_the_view_with_no_key_pressed(delay: float) -> None:
    first, later, took = asyncio.run(_cold_start(delay))
    assert "Checking for storms" in first
    assert "Checking for storms" not in later, f"still checking after {took:.1f} s"
    assert took < delay + WITHIN
