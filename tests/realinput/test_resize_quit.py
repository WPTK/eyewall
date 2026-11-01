"""Sizes, live resizes and a clean exit, on the built exe."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import psutil
import pytest

from .app import App
from .walk import home, start_replay, ticks


@pytest.fixture
def app(artifact: Path) -> Iterator[App]:
    a = start_replay(artifact)
    yield a
    a.close()


def test_live_resizes_recover(app: App, checks) -> None:  # type: ignore[no-untyped-def]
    app.key("enter", "b", "enter")
    crumb = app.crumb()
    checks("resize: starts on a station page", crumb[-1].startswith("Buoy"), app.dump())
    for cols, rows in ((100, 30), (200, 50), (60, 20), (80, 24), (59, 15), (120, 30), (280, 70), (120, 30)):
        app.resize(cols, rows)
        text = app.text()
        if cols < 60 or rows < 16:
            checks(
                f"resize {cols}x{rows}: says what size it needs",
                bool(re.search(r"60|too small|small", text, re.I)) and app.alive(),
                app.dump(),
            )
            continue
        checks(f"resize {cols}x{rows}: same page", app.crumb() == crumb, f"{app.crumb()}\n{app.dump()}")
        foot = app.lines()[rows - 1]
        checks(f"resize {cols}x{rows}: footer on the last row with ? and ^p", "?" in foot and "^p" in foot, foot)
        checks(
            f"resize {cols}x{rows}: nothing is drawn past the edge",
            all(len(ln) <= cols for ln in app.lines()),
            "line longer than the screen",
        )
        checks(f"resize {cols}x{rows}: no contradictions", not app.violations, "\n".join(app.violations))
    # a short terminal: Tab shows the next chart
    app.resize(60, 20)
    first = app.text()
    app.key("tab")
    checks(
        "Station at 60x20: Tab shows the next chart",
        app.text() != first and re.search(r"2 of 3", app.text()) is not None,
        app.dump(),
    )
    app.resize(120, 30)
    home(app)
    # Home map redraws to the new size
    for cols, rows in ((100, 30), (200, 50), (120, 30)):
        app.resize(cols, rows)
        marks = [y for y, ln in enumerate(app.lines()) if "◉" in ln]
        checks(
            f"Home {cols}x{rows}: map and storm mark are drawn",
            bool(marks) and "storm" in app.lines()[rows - 4 : rows].__str__(),
            app.dump(),
        )
        checks(
            f"Home {cols}x{rows}: side panel appears when wide enough",
            (cols >= 100) == ("NAMED STORMS" in app.text()),
            app.dump(),
        )
    ticks(app, 2.0)
    checks("resize walk: no contradictions after ticks", not app.violations, "\n".join(app.violations))
    checks.done()


def _mode_state(raw: bytes) -> dict[str, str]:
    state: dict[str, str] = {}
    for m in re.finditer(rb"\x1b\[\?([\d;]+)([hl])", raw):
        for mode in m.group(1).decode().split(";"):
            state[mode] = m.group(2).decode()
    return state


def test_q_quits_cleanly(artifact: Path, checks) -> None:  # type: ignore[no-untyped-def]
    app = start_replay(artifact, pause=False)
    try:
        pid = app.pid
        family = [pid, *[c.pid for c in psutil.Process(pid).children(recursive=True)]]
        app.key("enter")
        app.key("q")
        checks("q on a second screen does not quit", app.alive(), app.dump())
        home(app)
        raw_before = bytes(app._term._raw)
        modes = _mode_state(raw_before)
        checks(
            "terminal modes: the app turned on mouse reporting and the alt screen",
            {"1006", "1049"} <= {m for m, s in modes.items() if s == "h"},
            str(modes),
        )
        app.key("q", settle=False)
        code = app.wait_exit(20)
        checks("q on Home exits with code 0", code == 0, f"exit code {code}")
        app.settle(1.0)
        left_on = sorted(m for m, s in _mode_state(bytes(app._term._raw)).items() if s == "h")
        checks("exit leaves no terminal mode on (mouse, alt screen, focus, paste)", not left_on, f"still on: {left_on}")
        alive = [p for p in family if psutil.pid_exists(p) and psutil.Process(p).status() != psutil.STATUS_ZOMBIE]
        checks("exit leaves no process behind", not alive, f"still running: {alive}")
    finally:
        app.close()
    checks.done()


def test_footer_q_cell_quits(artifact: Path, checks) -> None:  # type: ignore[no-untyped-def]
    app = start_replay(artifact)
    try:
        cell = next((c for c in app.footer() if c.key == "q"), None)
        checks("footer has the q quit cell on Home", cell is not None, app.dump())
        if cell:
            app.click(cell.mid, cell.y, settle=False)
            code = app.wait_exit(20)
            checks("clicking 'q quit' exits with code 0", code == 0, f"exit code {code}")
    finally:
        app.close()
    checks.done()
