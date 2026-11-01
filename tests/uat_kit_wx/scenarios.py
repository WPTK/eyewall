"""Second-driver classification scenarios for the eyewall first-run suspicions.

usage: python -m tests.uat_kit_wx.scenarios SCENARIO [--driver wx|old|both] [--exe PATH] [--out DIR]

Takes the shared lock, launches the exe (copied to a fresh temp dir) behind a fake NOAA proxy where needed, and writes
screen dumps and a facts JSON to ``--out``. Test-only: nothing here changes application code.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .ew_driver import Run
from .fakenoaa import FakeNoaa
from .payloads import nhc_routes

REPO = Path(__file__).resolve().parents[2]
DEFAULT_EXE = Path(r"C:\Users\billp\uat-s2b\dl\eyewall-windows-x86_64.exe")
MAIN_PY = Path(r"C:\eyewall-wt\uat-kit-main\.venv\Scripts\python.exe")
LOCK = Path(r"C:\Users\billp\uat-shared\locks\gilead-heavy")
OUT = Path(r"C:\Users\billp\review-findings\uat-eyewall\evidence-1")


@contextmanager
def heavy_lock(purpose: str, wait: float = 1200) -> Iterator[None]:
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    end = time.monotonic() + wait
    while True:
        try:
            LOCK.mkdir()
            break
        except FileExistsError:
            if time.monotonic() > end:
                raise SystemExit("lock held for 20 minutes: gave up (never stolen)") from None
            time.sleep(10)
    try:
        (LOCK / "owner.json").write_text(
            json.dumps(
                {"app": "eyewall", "purpose": purpose, "pid": os.getpid(), "start": time.strftime("%Y-%m-%d %H:%M:%S")}
            )
        )
        yield
    finally:
        for f in LOCK.glob("*"):
            f.unlink(missing_ok=True)
        LOCK.rmdir()


def save(out: Path, name: str, text: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_text(text, encoding="utf-8")


def key_name(k: str) -> str:
    return {"[": "lbracket", "]": "rbracket", "space": "space"}.get(k, k)


# --------------------------------------------------------------------------------------------------------------------
def s1_offline(driver: str, exe: Path, out: Path) -> dict[str, Any]:
    """Live path (no flags) behind a blocked proxy; unblock; press r once; sample for 90 s."""
    facts: dict[str, Any] = {"driver": driver}
    tmp = Path(tempfile.mkdtemp(prefix="ew-s1-"))
    fake = FakeNoaa(tmp, default="real")
    fake.blocked = True
    try:
        with Run(driver, exe, [], 120, 30, fake=fake) as r:
            facts["pid"] = r.pid
            facts["home_seen"] = r.wait_text("Home", 60)
            r.poll(lambda x: "failing" in x.head() or "offline" in x.head().lower(), 60, 0.2)
            r.settle()
            facts["offline_header"] = r.head()
            save(out, f"s1-{driver}-1-offline.txt", r.dump())
            r.key("D")
            save(out, f"s1-{driver}-2-offline-D.txt", r.dump())
            r.key("esc")
            n_blocked = len(fake.log)
            fake.blocked = False
            t_unblock = time.monotonic()
            r.key("r", settle=False)
            samples = []
            while time.monotonic() - t_unblock < 90:
                time.sleep(3)
                samples.append((round(time.monotonic() - t_unblock), r.status(), len(fake.log) - n_blocked))
            facts["samples_after_r"] = samples
            save(out, f"s1-{driver}-3-after90s.txt", r.dump())
            r.key("D")
            save(out, f"s1-{driver}-4-after90s-D.txt", r.dump())
            r.key("esc")
            facts["requests_after_unblock"] = [
                (x["t"], x["host"], x.get("result")) for x in fake.log[n_blocked:] if x["kind"] == "connect"
            ][:40]
            r.key("q", settle=False)
            facts["exit"] = r.wait_exit(15)
    finally:
        fake.close()
    return facts


def s1b_repeat_r(driver: str, exe: Path, out: Path) -> dict[str, Any]:
    """Same, pressing r every 15 s after unblocking, for 90 s."""
    facts: dict[str, Any] = {"driver": driver}
    tmp = Path(tempfile.mkdtemp(prefix="ew-s1b-"))
    fake = FakeNoaa(tmp, default="real")
    fake.blocked = True
    try:
        with Run(driver, exe, [], 120, 30, fake=fake) as r:
            r.wait_text("Home", 60)
            r.poll(lambda x: "failing" in x.head(), 60, 0.2)
            r.settle()
            fake.blocked = False
            t0 = time.monotonic()
            samples = []
            for _ in range(6):
                r.key("r", settle=False)
                time.sleep(15)
                samples.append((round(time.monotonic() - t0), r.status()))
            facts["samples"] = samples
            r.key("D")
            save(out, f"s1b-{driver}-D.txt", r.dump())
            r.key("esc", "q", settle=False)
            facts["exit"] = r.wait_exit(15)
    finally:
        fake.close()
    return facts


def s1c_control(driver: str, exe: Path, out: Path, block_first: bool) -> dict[str, Any]:
    """Control for s1: never blocked (block_first False) or blocked 25 s then released with one r. Full connect log."""
    facts: dict[str, Any] = {"driver": driver, "block_first": block_first}
    fake = FakeNoaa(Path(tempfile.mkdtemp(prefix="ew-s1c-")), default="real")
    fake.blocked = block_first
    try:
        with Run(driver, exe, [], 120, 30, fake=fake) as r:
            r.wait_text("Home", 60)
            if block_first:
                time.sleep(25)
                fake.blocked = False
                r.key("r", settle=False)
            t_rel = fake._now()
            time.sleep(45)
            r.key("D")
            save(out, f"s1c-{driver}-{'blocked' if block_first else 'control'}-D.txt", r.dump())
            r.key("esc")
            facts["status"] = r.status()
            facts["release_at"] = t_rel
            facts["connects"] = [(x["t"], x["host"], x.get("result")) for x in fake.log if x["kind"] == "connect"]
            r.key("q", settle=False)
            facts["exit"] = r.wait_exit(15)
    finally:
        fake.close()
    return facts


def s2_latency(driver: str, exe: Path, out: Path) -> dict[str, Any]:
    """Time from the key bytes to (a) the crumb changing and (b) the last change of the screen within 2 s."""
    facts: dict[str, Any] = {"driver": driver}
    keys = {"A": "Alerts", "b": "Buoys", "t": "NHC text", "S": "Settings", "g": "Pictures"}
    with Run(driver, exe, ["--demo"], 120, 30) as r:
        r.wait_text("Erin", 60)
        r.settle(1.0)
        r.key("space")  # pause so the replay clock does not redraw during the measure
        for key, word in keys.items():
            rows = []
            for _ in range(8):
                r.key("esc", "esc")
                r.settle(0.8)
                home = r.crumb()
                r.raw(key)
                t0 = time.monotonic()
                first = last = None
                prev = r.text()
                while time.monotonic() - t0 < 2.0:
                    cur = r.text()
                    now = round(time.monotonic() - t0, 3)
                    if first is None and r.crumb() != home:
                        first = now
                    if cur != prev:
                        last, prev = now, cur
                    time.sleep(0.004)
                rows.append({"crumb_s": first, "last_change_s": last, "crumb": r.crumb()})
            facts[key] = {"word": word, "runs": rows}
        r.key("esc")
        save(out, f"s2-{driver}-last.txt", r.dump())
    return facts


def s3_pictures(driver: str, exe: Path, out: Path) -> dict[str, Any]:
    facts: dict[str, Any] = {"driver": driver}
    with Run(driver, exe, ["--demo"], 120, 30) as r:
        r.wait_text("Erin", 60)
        r.settle(1.0)
        r.key("space")
        r.key("enter")
        r.key("g")
        facts["demo_crumb"] = r.crumb()
        facts["demo_footer"] = r.footer()
        save(out, f"s3-{driver}-demo-g.txt", r.dump())
        base = r.text()
        for k in ("o", "y", "[", "]", "space"):
            r.key(k)
            facts[f"demo_key_{key_name(k)}_changed"] = r.text() != base
            save(out, f"s3-{driver}-demo-after-{key_name(k)}.txt", r.dump())
            base = r.text()
    # real storm path: NHC stood in by the populated.json origin; graphics landing page from a fixture; rest real
    tmp = Path(tempfile.mkdtemp(prefix="ew-s3-"))
    fake = FakeNoaa(tmp, default="real", modes={"www.nhc.noaa.gov": "origin"}, routes=nhc_routes("populated"))
    try:
        with Run(driver, exe, [], 140, 40, fake=fake) as r:
            r.wait_text("Erin", 60)
            r.settle(2.0)
            save(out, f"s3-{driver}-live-home.txt", r.dump())
            r.key("g")
            r.settle(3.0)
            facts["live_crumb"] = r.crumb()
            facts["live_footer"] = r.footer()
            save(out, f"s3-{driver}-live-g.txt", r.dump())
            base = r.text()
            for k in ("o", "y", "[", "]", "space"):
                r.key(k)
                facts[f"live_key_{key_name(k)}_changed"] = r.text() != base
                base = r.text()
            save(out, f"s3-{driver}-live-after-keys.txt", r.dump())
            facts["nhc_hits"] = [h["path"] for h in fake.hits("www.nhc.noaa.gov") if h.get("kind") == "origin"][:20]
    finally:
        fake.close()
    return facts


def s4_alerts_keys(driver: str, exe: Path, out: Path) -> dict[str, Any]:
    facts: dict[str, Any] = {"driver": driver}
    with Run(driver, exe, ["--demo"], 120, 30) as r:
        r.wait_text("Erin", 60)
        r.settle(1.0)
        r.key("space")
        r.key("A")
        facts["crumb"] = r.crumb()
        facts["footer"] = r.footer()
        facts["cells"] = [(k, lbl) for k, lbl, *_ in r.footer_cells()]
        save(out, f"s4-{driver}-alerts.txt", r.dump())
        for key in ("+", "-", "f", "c", "l"):
            before = r.text()
            r.key(key)
            after = r.text()
            facts[f"key_{key}"] = {"changed": before != after, "crumb": r.crumb(), "dialog": "╭" in after}
            if "╭" in after:
                save(out, f"s4-{driver}-alerts-key-{key_name(key)}.txt", r.dump())
                r.key("esc")
            if "Alerts" not in r.crumb():
                r.key("A")
        for key, _lbl, x0, x1 in r.footer_cells():
            if key in ("+/-", "f", "c", "l", "enter"):
                before = r.text()
                r.click((x0 + x1 - 1) // 2, r.rows - 1)
                facts[f"click_{key}"] = {"changed": before != r.text(), "crumb": r.crumb()}
                if "╭" in r.text():
                    r.key("esc")
                if "Alerts" not in r.crumb():
                    r.key("A")
        r.key("esc")
        for key in ("+", "f", "c"):  # control: the same keys on the map
            before = r.text()
            r.key(key)
            facts[f"home_key_{key}_changed"] = before != r.text()
        r.key("A")
        before = r.text()
        r.key("enter")
        facts["enter_on_alerts"] = {"changed": before != r.text(), "crumb": r.crumb()}
        save(out, f"s4-{driver}-alerts-enter.txt", r.dump())
    return facts


def s5_quiet(driver: str, exe: Path | list[str], out: Path, tag: str) -> dict[str, Any]:
    facts: dict[str, Any] = {"driver": driver, "build": tag}
    tmp = Path(tempfile.mkdtemp(prefix="ew-s5-"))
    fake = FakeNoaa(tmp, default="real", modes={"www.nhc.noaa.gov": "origin"}, routes=nhc_routes("empty"))
    try:
        with Run(driver, exe, [], 120, 30, fake=fake) as r:
            r.wait_text("Home", 60)
            r.settle(3.0)
            facts["footer"] = r.footer()
            facts["crumb"] = r.crumb()
            save(out, f"s5-{tag}-{driver}-home.txt", r.dump())
            facts["cells"] = [(k, lbl) for k, lbl, *_ in r.footer_cells()]
            before = r.text()
            r.key("enter")
            facts["enter_key"] = {"changed": before != r.text(), "crumb": r.crumb()}
            save(out, f"s5-{tag}-{driver}-after-enter.txt", r.dump())
            if " › " in r.crumb():
                r.key("esc")
            cell = next((c for c in r.footer_cells() if c[0].lower() == "enter"), None)
            facts["enter_cell"] = cell
            if cell:
                mid = (cell[2] + cell[3] - 1) // 2
                before = r.text()
                r.click(mid, r.rows - 1)
                facts["click_enter_cell"] = {"changed": before != r.text(), "crumb": r.crumb()}
                if " › " in r.crumb():
                    r.key("esc")
                before = r.text()
                r.click_raw_sgr(mid, r.rows - 1)
                facts["click_enter_cell_raw_sgr"] = {"changed": before != r.text(), "crumb": r.crumb()}
                if " › " in r.crumb():
                    r.key("esc")
            r.key("down")
            before = r.text()
            r.key("enter")
            facts["down_enter"] = {"changed": before != r.text(), "crumb": r.crumb()}
            save(out, f"s5-{tag}-{driver}-after-down-enter.txt", r.dump())
    finally:
        fake.close()
    return facts


def s6_j(driver: str, exe: Path | list[str], out: Path, tag: str) -> dict[str, Any]:
    facts: dict[str, Any] = {"driver": driver, "build": tag, "steps": []}
    tmp = Path(tempfile.mkdtemp(prefix="ew-s6-"))
    fake = FakeNoaa(tmp, default="real", modes={"www.nhc.noaa.gov": "origin"}, routes=nhc_routes("populated"))
    try:
        with Run(driver, exe, [], 140, 40, fake=fake) as r:
            r.wait_text("Erin", 60)
            r.settle(3.0)
            save(out, f"s6-{tag}-{driver}-0.txt", r.dump())
            facts["marks0"] = r.inverse_marks("◉●▲")
            for i in range(1, 6):
                r.key("j")
                facts["steps"].append(
                    {"press": i, "crumb": r.crumb(), "inverse_storm_marks": r.inverse_marks("◉"), "head": r.head()}
                )
                save(out, f"s6-{tag}-{driver}-{i}.txt", r.dump())
    finally:
        fake.close()
    return facts


def s7_space(driver: str, exe: Path, out: Path, n: int = 10, fast: bool = False) -> dict[str, Any]:
    facts: dict[str, Any] = {"driver": driver, "variant": "fast" if fast else "settled", "runs": []}
    for i in range(n):
        with Run(driver, exe, ["--demo"], 120, 30) as r:
            r.wait_text("Erin", 60)
            r.settle(1.0)
            r.key("enter", settle=False, gap=0.15 if fast else 0.08)  # the Storm page
            if not fast:
                r.settle(1.0)
            before = r.status()
            r.key("space", settle=False)
            ok = r.poll(lambda x, b=before: ("paused" in x.status()) != ("paused" in b), 3, 0.05)
            facts["runs"].append(
                {"i": i, "before": before, "after": r.status(), "changed_within_s": ok, "crumb": r.crumb()}
            )
            if i == 0:
                save(out, f"s7-{driver}-storm.txt", r.dump())
    facts["failures"] = sum(1 for x in facts["runs"] if x["changed_within_s"] is None)
    return facts


def _fresh_demo(driver: str, exe: Path, setup: str) -> Run:
    r = Run(driver, exe, ["--demo"], 120, 30)
    r.wait_text("Erin", 60)
    r.settle(1.0)
    r.key("space")  # paused: the replay clock cannot move the map
    if setup == "M":
        r.key("M")
    return r


def s9_footer_clicks(driver: str, exe: Path, out: Path) -> dict[str, Any]:
    """Footer cells '+/- zoom', 'f fit', 'c center' on Home and the full map: key vs click, one fresh launch each;
    the crumb 'Home' segment click on Alerts; the footer click that should open the full map."""
    facts: dict[str, Any] = {"driver": driver}
    for setup in ("home", "M"):
        for label, keys in (("+/-", ("+", "-")), ("f", ("f",)), ("c", ("c",))):
            res: dict[str, Any] = {}
            base = None
            for how in [*keys, "click", "click_left", "click_right", "click_raw_sgr"]:
                with _fresh_demo(driver, exe, setup) as r:
                    cell = next((c for c in r.footer_cells() if c[0] == label), None)
                    if base is None:
                        base = r.text()
                        res["footer"] = r.footer()
                        res["cell"] = cell
                    if cell is None:
                        res["error"] = "no such footer cell"
                        break
                    x0, x1 = cell[2], cell[3]
                    if how in ("+", "-", "f", "c"):
                        r.key(how)
                    elif how == "click":
                        r.click((x0 + x1 - 1) // 2, r.rows - 1)
                    elif how == "click_left":
                        r.click(x0, r.rows - 1)
                    elif how == "click_right":
                        r.click(x1 - 1, r.rows - 1)
                    else:
                        r.click_raw_sgr((x0 + x1 - 1) // 2, r.rows - 1)
                    res[how] = r.text()
            if "error" not in res:
                same = {
                    k: [o for o in res if o not in (k, "footer", "cell") and res[o] == res[k]]
                    for k in res
                    if k not in ("footer", "cell")
                }
                res = {
                    "footer": res["footer"],
                    "cell": res["cell"],
                    "unchanged_from_start": [k for k in same if res[k] == base],
                    "same_screen_as": same,
                }
            facts[f"{setup}:{label}"] = res
    # crumb Home click on Alerts
    with _fresh_demo(driver, exe, "home") as r:
        r.key("A")
        crumb_before = r.crumb()
        seg = r.head().find("Home")
        r.click(seg + 1, 0)
        facts["crumb_click_home_on_alerts"] = {"before": crumb_before, "after": r.crumb(), "head_after": r.head()}
        save(out, f"s9-{driver}-crumb-click.txt", r.dump())
        r.click_raw_sgr(seg + 1, 0)
        facts["crumb_click_home_on_alerts_raw_sgr"] = {"after": r.crumb()}
    # click the footer cell that opens the full map, from Home
    with _fresh_demo(driver, exe, "home") as r:
        cells = [(k, lbl) for k, lbl, *_ in r.footer_cells()]
        facts["home_footer_cells"] = cells
        m = next((c for c in r.footer_cells() if c[0] == "M"), None)
        if m:
            r.click((m[2] + m[3] - 1) // 2, r.rows - 1)
            facts["click_M_cell"] = {"crumb": r.crumb(), "footer": r.footer()}
            save(out, f"s9-{driver}-click-M.txt", r.dump())
    return facts


def s5b_enter_after_n(driver: str, exe: Path | list[str], out: Path, tag: str) -> dict[str, Any]:
    """Quiet-day Home: does Enter open anything when a station is marked (n first)? Header clock ignored."""
    facts: dict[str, Any] = {"driver": driver, "build": tag}
    tmp = Path(tempfile.mkdtemp(prefix="ew-s5b-"))
    fake = FakeNoaa(tmp, default="real", modes={"www.nhc.noaa.gov": "origin"}, routes=nhc_routes("empty"))

    def body(r: Run) -> str:
        return "XX".join(r.lines()[1:])

    try:
        with Run(driver, exe, [], 120, 30, fake=fake) as r:
            r.wait_text("Home", 60)
            r.settle(3.0)
            b0 = body(r)
            r.key("enter")
            facts["enter_no_mark"] = {"body_changed": body(r) != b0, "crumb": r.crumb()}
            r.click_raw_sgr(5, r.rows - 1)  # control: a click on the footer's first cell ('enter open' on main)
            for step in ("n", "n", "N"):
                r.key(step)
                facts[f"after_{step}"] = {"body_changed": body(r) != b0, "crumb": r.crumb()}
            save(out, f"s5b-{tag}-{driver}-after-n.txt", r.dump())
            before = body(r)
            r.key("enter")
            facts["enter_after_n"] = {"body_changed": body(r) != before, "crumb": r.crumb()}
            save(out, f"s5b-{tag}-{driver}-after-n-enter.txt", r.dump())
    finally:
        fake.close()
    return facts


def s9b_zoom_scale(driver: str, exe: Path, out: Path) -> dict[str, Any]:
    """Deterministic version of the footer-click check: compare the map scale line ('N deg/dot'), not whole screens."""
    import re

    def scale(r: Run) -> str:
        for ln in r.lines():
            m = re.search(r"([\d.]+) deg/dot", ln)
            if m:
                return m.group(1)
        return "?"

    facts: dict[str, Any] = {"driver": driver}
    for setup in ("home", "M"):
        res: dict[str, list[str]] = {}
        for how in ("base", "+", "-", "click", "click_left", "click_right", "raw"):
            vals = []
            for _ in range(3):
                with _fresh_demo(driver, exe, setup) as r:
                    cell = next(c for c in r.footer_cells() if c[0] == "+/-")
                    x0, x1 = cell[2], cell[3]
                    if how in ("+", "-"):
                        r.key(how)
                    elif how == "click":
                        r.click((x0 + x1 - 1) // 2, r.rows - 1)
                    elif how == "click_left":
                        r.click(x0, r.rows - 1)
                    elif how == "click_right":
                        r.click(x1 - 1, r.rows - 1)
                    elif how == "raw":
                        r.click_raw_sgr((x0 + x1 - 1) // 2, r.rows - 1)
                    vals.append(scale(r))
            res[how] = vals
        facts[setup] = res
    return facts


def run_summary(prefix: list[str], fake: FakeNoaa | None, label: str) -> dict[str, Any]:
    env = {k: v for k, v in os.environ.items() if "PROXY" not in k.upper() and k not in ("SSL_CERT_FILE", "NO_COLOR")}
    env["PYTHONUTF8"] = "1"
    state = Path(tempfile.mkdtemp(prefix="ew-sum-"))
    home = state / "home"  # the cache lives under the user's profile: a shared cache hides a failed feed
    (home / "AppData" / "Local").mkdir(parents=True)
    (home / "AppData" / "Roaming").mkdir(parents=True)
    env.update(
        HOME=str(home),
        USERPROFILE=str(home),
        LOCALAPPDATA=str(home / "AppData" / "Local"),
        APPDATA=str(home / "AppData" / "Roaming"),
        XDG_CACHE_HOME=str(home / "xdg-cache"),
        XDG_DATA_HOME=str(home / "xdg-data"),
        WIN_PD_OVERRIDE_LOCAL_APPDATA=str(home / "AppData" / "Local"),
        WIN_PD_OVERRIDE_APPDATA=str(home / "AppData" / "Roaming"),
    )
    if fake:
        env.update(fake.env())
    n = len(fake.log) if fake else 0
    t = time.monotonic()
    p = subprocess.run(
        [*prefix, "--summary", "--no-config", "--state-dir", str(state)],
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        encoding="utf-8",
        errors="replace",
        cwd=state,
    )
    return {
        "case": label,
        "exit": p.returncode,
        "secs": round(time.monotonic() - t, 1),
        "stdout": p.stdout,
        "stderr": p.stderr,
        "connects": sorted({(x["host"], x.get("result")) for x in fake.log[n:] if x["kind"] == "connect"})
        if fake
        else [],
        "cache_files_in_scratch": sum(1 for _ in home.rglob("*.json")),
        "origin_paths": [x["path"] for x in fake.log[n:] if x["kind"] == "origin"] if fake else [],
    }


def s8_summary(prefix: list[str], tag: str) -> dict[str, Any]:
    cases = {
        "storms-ok-nhc-origin-others-real": {},
        "nhc-down-entirely": {"www.nhc.noaa.gov": "refuse", "ftp.nhc.noaa.gov": "refuse"},
        "tides-only": {"api.tidesandcurrents.noaa.gov": "refuse"},
        "buoys-only": {"www.ndbc.noaa.gov": "refuse"},
        "text-products-tgftp-only": {"tgftp.nws.noaa.gov": "refuse"},
        "api-weather-gov-only": {"api.weather.gov": "refuse"},
        "satellite-only": {"cdn.star.nesdis.noaa.gov": "refuse"},
    }
    res = []
    for name, overrides in cases.items():
        modes = {"www.nhc.noaa.gov": "origin", **overrides}
        fake = FakeNoaa(
            Path(tempfile.mkdtemp(prefix="ew-s8-")), default="real", modes=modes, routes=nhc_routes("populated")
        )
        try:
            res.append(run_summary(prefix, fake, name))
        finally:
            fake.close()
    fake = FakeNoaa(Path(tempfile.mkdtemp(prefix="ew-s8-")), default="refuse")
    try:
        res.append(run_summary(prefix, fake, "all-hosts-502"))
    finally:
        fake.close()
    return {"build": tag, "cases": res}


def s10_full_map_by_mouse(driver: str, exe: Path, out: Path) -> dict[str, Any]:
    """Is there any mouse path to the full-screen map (the ``M`` key)? Palette entry, footer cell, breadcrumb."""
    facts: dict[str, Any] = {"driver": driver}
    with _fresh_demo(driver, exe, "home") as r:
        facts["home_footer_cells"] = [(k, lbl) for k, lbl, *_ in r.footer_cells()]
        base_scale = r.text()
        r.key("M")
        facts["M_key"] = {"crumb": r.crumb(), "footer": r.footer(), "changed": r.text() != base_scale}
        save(out, f"s10-{driver}-M-key.txt", r.dump())
        full_footer = r.footer()
        r.key("esc")
        facts["after_esc_footer_matches_home"] = r.footer() != full_footer
    for query in ("map", "full", "screen"):
        with _fresh_demo(driver, exe, "home") as r:
            r.raw("")
            r.settle(1.0)
            r.raw(query)
            r.settle(1.5)
            lines = [ln.strip() for ln in r.lines() if ln.strip()]
            facts[f"palette_{query}"] = lines[:14]
            save(out, f"s10-{driver}-palette-{query}.txt", r.dump())
    # click the palette entry 'Go to the map' (the only map entry), by mouse, and see which map results
    with _fresh_demo(driver, exe, "home") as r:
        r.raw("")
        r.settle(1.0)
        r.raw("map")
        r.settle(1.5)
        hit = next((i for i, ln in enumerate(r.lines()) if "Go to the map" in ln), None)
        facts["palette_row_for_go_to_the_map"] = hit
        if hit is not None:
            col = r.lines()[hit].find("Go to the map") + 3
            r.click(col, hit)
            r.settle(1.0)
            facts["after_palette_click"] = {"crumb": r.crumb(), "footer": r.footer(), "dialog_open": "╰" in r.text()}
            save(out, f"s10-{driver}-after-palette-click.txt", r.dump())
            if "╰" in r.text():  # still open: the click did not resolve; Enter does
                r.key("enter")
                facts["after_palette_enter"] = {"crumb": r.crumb(), "footer": r.footer()}
    return facts


def s11_alerts_count(driver: str, exe: Path, out: Path) -> dict[str, Any]:
    """Alerts screen: the top bar says 'N alerts'; count the rows."""
    import re

    facts: dict[str, Any] = {"driver": driver}
    with _fresh_demo(driver, exe, "home") as r:
        r.key("A")
        r.settle(1.0)
        head = r.head()
        m = re.search(r"(\d+) alerts?", head)
        rows = [ln for ln in r.lines()[1:-1] if re.match(r"\s*[A-Z][a-z]{2} \d{1,2} \d\d:\d\d ", ln)]
        facts.update(header=head, header_count=int(m.group(1)) if m else None, row_count=len(rows), rows=rows)
        save(out, f"s11-{driver}-alerts.txt", r.dump())
    return facts


# --------------------------------------------------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario")
    ap.add_argument("--driver", default="both")
    ap.add_argument("--exe", type=Path, default=DEFAULT_EXE)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--n", type=int, default=10)
    a = ap.parse_args()
    drivers = ["wx", "old"] if a.driver == "both" else [a.driver]
    results: list[Any] = []
    with heavy_lock(f"uat-kit second driver: {a.scenario}"):
        main_prefix = [str(MAIN_PY), "-m", "eyewall"]
        if a.scenario == "s8":
            results.append(s8_summary([str(a.exe)], "v0.9.0"))
            results.append(s8_summary(main_prefix, "main-2671fff"))
        for d in drivers if a.scenario != "s8" else []:
            sc = a.scenario
            if sc == "s1":
                results.append(s1_offline(d, a.exe, a.out))
            elif sc == "s1b":
                results.append(s1b_repeat_r(d, a.exe, a.out))
            elif sc == "s2":
                results.append(s2_latency(d, a.exe, a.out))
            elif sc == "s3":
                results.append(s3_pictures(d, a.exe, a.out))
            elif sc == "s4":
                results.append(s4_alerts_keys(d, a.exe, a.out))
            elif sc == "s5":
                results.append(s5_quiet(d, a.exe, a.out, "v0.9.0"))
                results.append(s5_quiet(d, main_prefix, a.out, "main-2671fff"))
            elif sc == "s6":
                results.append(s6_j(d, a.exe, a.out, "v0.9.0"))
                results.append(s6_j(d, main_prefix, a.out, "main-2671fff"))
            elif sc == "s5b":
                results.append(s5b_enter_after_n(d, a.exe, a.out, "v0.9.0"))
                results.append(s5b_enter_after_n(d, main_prefix, a.out, "main-2671fff"))
            elif sc == "s1c":
                results.append(s1c_control(d, a.exe, a.out, False))
                results.append(s1c_control(d, a.exe, a.out, True))
            elif sc == "s9b":
                results.append(s9b_zoom_scale(d, a.exe, a.out))
            elif sc == "s9":
                results.append(s9_footer_clicks(d, a.exe, a.out))
            elif sc == "s10":
                results.append(s10_full_map_by_mouse(d, a.exe, a.out))
            elif sc == "s11":
                results.append(s11_alerts_count(d, a.exe, a.out))
            elif sc == "s7":
                results.append(s7_space(d, a.exe, a.out, a.n))
            elif sc == "s7f":
                results.append(s7_space(d, a.exe, a.out, a.n, fast=True))
            else:
                raise SystemExit(f"unknown scenario {sc}")
    text = json.dumps(results, indent=1, ensure_ascii=False, default=str)
    save(a.out, f"facts-{a.scenario}-{a.driver}.json", text)
    print(text[:7000])


if __name__ == "__main__":
    main()
