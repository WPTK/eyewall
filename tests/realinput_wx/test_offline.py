"""Quiet-day / offline run on the built exe: live mode (no flags) with the network cut by the fault proxy, then restored."""

from __future__ import annotations

import re
import time
from pathlib import Path

from .app import App
from .walk import home


def _failing(app: App) -> int:
    m = re.search(r"(\d+) feeds? failing", app.header_status() + " " + app.lines()[0])
    return int(m.group(1)) if m else 0


def test_offline_start_walk_and_recovery(artifact: Path, fake_noaa, internet, checks) -> None:  # type: ignore[no-untyped-def]
    fake = fake_noaa(default="real")  # tunnels to the real NOAA once unblocked, so the recovery is the real one
    fake.blocked = True  # the network is cut: every CONNECT answers 503
    app = App(artifact, [], 120, 30, fake=fake)
    try:
        app.wait_text("Home", 90)
        app.wait_for(lambda a: _failing(a) >= 1 or "offline" in a.lines()[0], 120, "the first fetch to fail")
        app.settle(2.0)
        text = app.text()
        checks(
            "offline start: Home shows, no traceback", app.crumb() == ["Home"] and "Traceback" not in text, app.dump()
        )
        checks(
            "offline start: says plainly that data is unavailable",
            bool(re.search(r"unavailable|offline|could not", text, re.I)),
            app.dump(),
        )
        head = app.lines()[0]
        checks("offline start: the top bar reports failing feeds", _failing(app) >= 1 or "offline" in head, head)
        checks("offline start: top bar does not claim the data is ok", not re.search(r"data ok|● ", head), head)
        counted = _failing(app)  # a dialog blanks the top bar, so count first
        app.key("D")
        failing_rows = [ln for ln in app.lines() if "✕" in ln]
        checks(
            "offline: the Feeds dialog lists as many failing feeds as the top bar counts",
            len(failing_rows) == counted,
            f"{len(failing_rows)} rows vs top bar {counted}\n{app.dump()}",
        )
        home(app)
        for keys, expect, label in (
            (["b"], lambda a: a.crumb()[-1] == "Buoys and gauges", "Buoys"),
            (["t"], lambda a: a.crumb()[-1].startswith("NHC text"), "NHC text"),
            (["O"], lambda a: a.crumb()[-1].startswith("NHC text"), "Outlook"),
            (["A"], lambda a: a.crumb()[-1] == "Alerts", "Alerts"),
            (["S"], lambda a: "Poll intervals" in a.text(), "Settings"),
            (["?"], lambda a: "previous or next storm" in a.text(), "Help"),
            (["g"], lambda a: a.alive(), "Pictures key with no storm"),
            (["M"], lambda a: a.alive(), "Full map"),
            (["1"], lambda a: a.alive(), "basin 1"),
            (["a"], lambda a: a.alive(), "basin a"),
            (["u"], lambda a: a.alive(), "units"),
            (["u", "u", "u"], lambda a: a.alive(), "units back"),
        ):
            home(app)
            app.key(*keys)
            checks(f"offline: key {'+'.join(keys)} ({label})", expect(app), app.dump())
        home(app)
        # one click on a footer cell while offline
        cell = next((c for c in app.footer() if c.key == "t"), None)
        if cell:
            app.click(cell.mid, cell.y)
            checks("offline: click footer 't' opens the text", app.crumb()[-1].startswith("NHC text"), app.dump())
        home(app)
        checks("offline: no contradictions", not app.violations, "\n".join(app.violations))
        # back online
        before = len(fake.log)
        fake.blocked = False
        app.key("r")
        end = time.monotonic() + 75
        while time.monotonic() < end and _failing(app):
            time.sleep(1)
        checks(
            "recovery: after the network returns and r is pressed, no feed is failing within 75 s",
            _failing(app) == 0,
            f"{len(fake.log) - before} requests went out after unblocking; top bar: {app.lines()[0]!r}",
        )
        app.key("D")
        checks("recovery: Feeds dialog shows no failing feed", not any("✕" in ln for ln in app.lines()), app.dump())
        home(app)
        checks("recovery: no contradictions", not app.violations, "\n".join(app.violations))
        app.key("q", settle=False)
        checks("offline run: q exits with code 0", app.wait_exit(15) == 0, "did not exit with 0")
    finally:
        app.close()
    checks.done()
