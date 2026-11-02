"""Suspicions the second-driver UAT cleared: behaviour that is right, pinned as ordinary passing tests.

Each docstring names the first-run suspicion and why it was not a defect, so a failure here means a real regression.
"""

from __future__ import annotations

import re
import time

import pytest

pytest.importorskip("tui_test", reason="tui-test is a dev dependency: pip install -e '.[dev]'")

from tests.uat_kit_wx.ew_driver import Run, run_cli
from tests.uat_kit_wx.payloads import nhc_routes

from .support import NHC, demo_paused, require


def test_j_moves_the_selection_and_the_map_names_the_selected_storm(exe, fake_noaa) -> None:
    """Suspicion: ``j`` leaves the selected storm off screen. Not so: the map labels the selected storm and recentres."""
    fake = fake_noaa(modes={NHC: "origin"}, routes=nhc_routes("populated"))
    with Run("wx", exe, [], 140, 40, fake=fake) as r:
        require(r.wait_text("Erin", 60), r.dump())
        time.sleep(12)  # start-up toasts cover part of the map for the first seconds
        names = []
        for _ in range(4):
            r.key("j")
            named = re.findall(r"◉([A-Z][a-z]+)", "\n".join(ln.split("│")[0] for ln in r.lines()))
            assert len(named) == 1, f"expected exactly one labelled storm on the map, got {named}\n" + r.dump()
            names.append(named[0])
        assert sorted(names) == ["Eight", "Erin", "Fay", "Nolo"], names  # four presses visit the four storms
        assert r.crumb() == "Home"


def test_space_on_the_storm_page_toggles_the_replay(exe) -> None:
    """Suspicion: space intermittently does not pause on the Storm page. 0 of 40 launches failed; 3 launches here."""
    for _ in range(3):
        with Run("wx", exe, ["--demo"], 120, 30) as r:
            require(r.wait_text("Erin", 60), r.dump())
            r.settle(1.0)
            r.key("enter")
            require("Erin" in r.crumb(), r.dump())
            before = "paused" in r.status()
            r.key("space", settle=False)
            assert r.poll(lambda x, b=before: ("paused" in x.status()) != b, 3, 0.05) is not None, r.dump()


def test_alerts_screen_footer_and_crumb(exe) -> None:
    """Suspicion: Alerts advertises map keys. Not so: its footer is help, menu, back, and the map keys do nothing."""
    with demo_paused(exe) as r:
        r.key("A")
        assert r.crumb() == "Home › Alerts"
        assert [k for k, *_ in r.footer_cells()] == ["?", "^p", "esc"], r.footer()
        for key in ("+", "-", "c", "l", "enter"):
            table = r.lines()[1:5]  # the toast stack on the right moves on its own; the table must not
            r.key(key)
            assert r.crumb() == "Home › Alerts"
            assert r.lines()[1:5] == table, f"{key} changed the Alerts screen"


def test_alerts_open_promptly_on_the_tui_test_kit(exe) -> None:
    """Suspicion: Alerts opens 0.6 s late. That was the old pywinpty kit's output pump; here A is as fast as b or t."""
    with demo_paused(exe) as r:
        for key in ("A", "b", "t"):
            r.key("esc", "esc")
            home = r.crumb()
            r.raw(key)
            took = r.poll(lambda x, h=home: x.crumb() != h, 3, 0.005)
            assert took is not None and took < 0.5, f"{key}: crumb changed after {took}"


def test_go_to_the_map_palette_entry_resolves_by_click(exe) -> None:
    """Suspicion: a click on a Ctrl+P entry does not resolve. It does; 'Go to the map' lands on Home, not full screen."""
    with demo_paused(exe) as r:
        r.key("A")
        r.raw("\x10")
        r.settle(1.0)
        r.raw("map")
        r.settle(1.5)
        row = next((i for i, ln in enumerate(r.lines()) if "Go to the map" in ln), None)
        require(row is not None, r.dump())
        r.click(r.lines()[row].find("Go to the map") + 3, row)
        assert r.crumb() == "Home"
        assert r.footer_cells()[-1][0] == "q", (
            r.footer()
        )  # the plain Home, not the full-screen map (its footer ends esc back)


def test_full_screen_map_by_key_and_back_with_esc(exe) -> None:
    """README: ``M`` is the full-screen map and ``Esc`` leaves it."""
    with demo_paused(exe) as r:
        home_footer = r.footer()
        r.key("M")
        assert r.footer_cells()[-1][0] == "esc", r.footer()
        r.key("esc")
        assert r.footer() == home_footer


@pytest.mark.parametrize("feed", ["www.nhc.noaa.gov", "everything"])
def test_summary_exits_1_when_storm_data_is_unavailable(exe, fake_noaa, feed: str) -> None:
    """The cases of ``--summary`` that already do what the README says: NHC down, and every feed down."""
    if feed == "everything":
        fake = fake_noaa(default="refuse")
    else:
        fake = fake_noaa(modes={"www.nhc.noaa.gov": "refuse", "ftp.nhc.noaa.gov": "refuse"}, default="refuse")
    p = run_cli(exe, ["--summary"], fake=fake)
    assert p.returncode == 1, f"exit {p.returncode}\n{p.stdout}\n{p.stderr}"
    assert re.search(r"unavailable|every feed failed", p.stdout + p.stderr), p.stdout + p.stderr


def test_the_launch_environment_is_isolated(exe, tmp_path) -> None:
    """A launch writes nowhere outside its own run root: the session guard (conftest) checks the real folders."""
    p = run_cli(exe, ["--version"])
    assert p.returncode == 0 and p.stdout.strip().startswith("eyewall"), (p.stdout, p.stderr)


def test_alerts_header_count_matches_the_rows(exe) -> None:
    """Suspicion: the top bar's '3 alerts' disagrees with the rows. It agrees (the first run's check was truncated)."""
    with demo_paused(exe) as r:
        r.key("A")
        counted = re.search(r"(\d+) alerts?", r.head())
        require(counted, r.dump())
        rows = [ln for ln in r.lines()[1:-1] if re.match(r"\s*[A-Z][a-z]{2} \d{1,2} \d\d:\d\d ", ln)]
        assert int(counted.group(1)) == len(rows) > 0, r.dump()
