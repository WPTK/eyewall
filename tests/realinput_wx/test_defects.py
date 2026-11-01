"""Defects found by the second-driver UAT, each pinned by a strict xfail keyed by its issue number.

Every test asserts what the README promises. On the published v0.9.0 exe it fails (XFAIL); the day the defect is fixed
it passes, strict xfail turns that into a failure, and the marker comes off. A scene that does not come up raises
``Precondition`` (not an AssertionError), so a broken harness can never pass for an expected failure.
"""

from __future__ import annotations

import re

import pytest

pytest.importorskip("tui_test", reason="tui-test is a dev dependency: pip install -e '.[dev]'")

from tests.uat_kit_wx.ew_driver import Run, run_cli
from tests.uat_kit_wx.payloads import active_storm_routes, nhc_routes

from .support import NHC, STAR, body, demo_paused, require


def xfail(issue: int) -> pytest.MarkDecorator:
    return pytest.mark.xfail(strict=True, raises=AssertionError, reason=f"#{issue}")


@xfail(164)
def test_r_after_the_network_returns_recovers_the_feeds(exe, fake_noaa) -> None:
    """README: ``r`` refreshes every feed now. Offline, then online, then ``r``: the storms must come back."""
    fake = fake_noaa(modes={NHC: "origin"}, routes=nhc_routes("populated"))
    fake.blocked = True  # every CONNECT answers 503: the network is cut
    with Run("wx", exe, [], 120, 30, fake=fake) as r:
        require(r.wait_text("Home", 60), r.dump())
        require(r.poll(lambda x: "failing" in x.head(), 60, 0.2) is not None, "never went offline:\n" + r.dump())
        require("Storm data unavailable" in r.text(), r.dump())
        fake.blocked = False
        n = len(fake.hits(NHC))
        r.key("r", settle=False)
        recovered = r.poll(lambda x: "Erin" in x.text(), 45, 0.5)
        assert recovered is not None, (
            f"45 s after r the storms are still unavailable; {len(fake.hits(NHC)) - n} new requests reached NHC\n"
            + r.dump()
        )


@xfail(165)
def test_quiet_day_home_enter_does_what_the_footer_says(exe, fake_noaa) -> None:
    """A footer label is shown only when the key does something. Quiet day, nothing marked: ``enter open``."""
    fake = fake_noaa(modes={NHC: "origin"}, routes=nhc_routes("empty"))
    with Run("wx", exe, [], 120, 30, fake=fake) as r:
        require(r.wait_text("Home", 60), r.dump())
        r.settle(3.0)
        cell = next((c for c in r.footer_cells() if c[0].lower() == "enter"), None)
        if cell is None:
            return  # not advertised: nothing to check (this is also the fixed state)
        before = body(r)
        r.key("enter")
        assert body(r) != before or " › " in r.crumb(), (
            "the footer says enter open, and Enter does nothing:\n" + r.dump()
        )
        before = body(r)
        r.click_raw_sgr((cell[2] + cell[3] - 1) // 2, r.rows - 1)
        assert body(r) != before or " › " in r.crumb(), "a click on the footer's enter cell does nothing:\n" + r.dump()


def _pictures_screen_explains_itself(r: Run) -> None:
    area = [ln[:70].strip() for ln in r.lines()[2 : r.rows - 1]]  # left of the toast column
    advertised = {k for k, *_ in r.footer_cells()} & {"o", "y"}
    assert any(area), "the Pictures screen is blank: no list, no picture, no sentence saying why\n" + r.dump()
    assert not advertised, f"the footer advertises {sorted(advertised)} with nothing to open or copy\n" + r.dump()


@xfail(166)
def test_pictures_in_demo_is_not_blank(exe) -> None:
    """``--demo`` has no pictures. README's first-run path says press ``g``: say why it is empty, advertise no dead keys."""
    with demo_paused(exe) as r:
        r.key("enter")
        r.key("g")
        require(r.crumb().endswith("Pictures"), r.dump())
        _pictures_screen_explains_itself(r)


@xfail(166)
def test_pictures_for_an_active_storm_nothing_lists_is_not_blank(exe, fake_noaa) -> None:
    """The same defect on the live path: an active storm that NESDIS lists no pictures for (the usual case early on)."""
    routes = active_storm_routes(satellite=False)
    fake = fake_noaa(modes={NHC: "origin", STAR: "origin"}, routes=routes)
    with Run("wx", exe, [], 140, 40, fake=fake) as r:
        require(r.wait_text("Erin", 60), r.dump())
        r.settle(3.0)
        r.key("enter")
        r.key("g")
        r.settle(5.0)
        require(r.crumb().endswith("Pictures"), r.dump())
        _pictures_screen_explains_itself(r)


# --summary: the README says that when a feed could not be fetched it says which data is unavailable and exits with 1.
SUMMARY_CASES = {
    "tide gauges": "api.tidesandcurrents.noaa.gov",
    "buoys": "www.ndbc.noaa.gov",
    "text products": "tgftp.nws.noaa.gov",
    "alerts": "api.weather.gov",
    "satellite": STAR,
}


@pytest.mark.parametrize("feed", list(SUMMARY_CASES))
@xfail(167)
def test_summary_exits_1_when_a_feed_could_not_be_fetched(exe, fake_noaa, internet, feed: str) -> None:
    fake = fake_noaa(modes={NHC: "origin", SUMMARY_CASES[feed]: "refuse"}, routes=nhc_routes("populated"))
    p = run_cli(exe, ["--summary"], fake=fake)
    require(re.search(r"Erin", p.stdout), f"the summary did not run: exit {p.returncode}\n{p.stdout}\n{p.stderr}")
    assert p.returncode == 1, f"{feed} refused: exit {p.returncode}, stdout says:\n{p.stdout}"
    assert re.search(r"unavailable|could not|failed", p.stdout + p.stderr, re.I), f"{feed} refused and nothing says so"
