"""One boundary case per workflow, and the terminal environment matrix, on the built exe."""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

import pytest

from .app import App
from .walk import home, start_replay


def run_exe(
    exe: Path, args: list[str], cwd: Path, extra: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    import os

    env = {k: v for k, v in os.environ.items() if k.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT"}}
    for k in (
        "HOME",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "TEMP",
        "TMP",
        "XDG_STATE_HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
    ):
        env[k] = str(cwd / k.lower())
        (cwd / k.lower()).mkdir(exist_ok=True)
    env.update(PYTHONUTF8="1", HTTP_PROXY="http://127.0.0.1:9", HTTPS_PROXY="http://127.0.0.1:9", **(extra or {}))
    return subprocess.run(
        [str(exe), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        encoding="utf-8",
        errors="replace",
    )


def test_bad_inputs_fail_in_words_not_tracebacks(artifact: Path, checks) -> None:  # type: ignore[no-untyped-def]
    work = Path(tempfile.mkdtemp(prefix="ew-bound-"))
    bad_toml = work / "bad.toml"
    bad_toml.write_text("this is = = not toml [", encoding="utf-8")
    a_file = work / "afile"
    a_file.write_text("x", encoding="utf-8")
    cases = [
        ("--replay with a path that does not exist", ["--replay", str(work / "nope"), "--summary"]),
        ("--config with a file that is not TOML", ["--config", str(bad_toml), "--demo", "--summary"]),
        ("--config with a path that does not exist", ["--config", str(work / "missing.toml"), "--demo", "--summary"]),
        (
            "--state-dir that is a file, not a directory",
            ["--demo", "--headless", "--until", "+1h", "--state-dir", str(a_file)],
        ),
        ("--until with nonsense", ["--demo", "--headless", "--until", "soon"]),
        ("--basin with an unknown basin", ["--basin", "XX", "--demo", "--summary"]),
        ("offline --summary (network refused)", ["--summary"]),
    ]
    for label, args in cases:
        r = run_exe(artifact, args, work)
        out = r.stdout + r.stderr
        checks(f"{label}: no traceback", "Traceback" not in out, out[-500:])
        checks(
            f"{label}: says something and exits non-zero or handles it",
            (r.returncode != 0 and bool(out.strip())) or r.returncode == 0,
            f"exit {r.returncode}: {out[-300:]}",
        )
    r = run_exe(artifact, ["--summary"], work)
    checks(
        "offline --summary: exits 1 and names the missing data, not a quiet day",
        r.returncode == 1 and re.search(r"unavailable|could not", r.stdout + r.stderr, re.I) is not None,
        f"exit {r.returncode}: {(r.stdout + r.stderr)[-300:]}",
    )
    r = run_exe(artifact, ["--version"], work)
    checks(
        "--version: prints a version and exits 0",
        r.returncode == 0 and re.match(r"eyewall \d+\.\d+\.\d+", r.stdout) is not None,
        r.stdout + r.stderr,
    )
    checks.done()


def test_tiny_terminal_says_the_size(artifact: Path, checks) -> None:  # type: ignore[no-untyped-def]
    for cols, rows in ((59, 16), (60, 15), (40, 10)):
        app = App(artifact, ["--demo"], cols, rows)
        try:
            app.wait_for(lambda a: any(a.lines()), 90, "any output")
            app.settle(2.0)
            checks(
                f"{cols}x{rows}: a message names the size needed",
                re.search(r"60.{0,6}16|too small|larger", app.text(), re.I) is not None
                and "Traceback" not in app.text(),
                app.dump(),
            )
            app.resize(120, 30)
            app.wait_text("Erin", 30)
            checks(f"{cols}x{rows}: growing to 120x30 shows the map", app.crumb() == ["Home"], app.dump())
        finally:
            app.close()
    checks.done()


def test_terminal_environment_matrix(artifact: Path, checks) -> None:  # type: ignore[no-untyped-def]
    cells = {
        "NO_COLOR=1": {"NO_COLOR": "1"},
        "COLORTERM unset, TERM=xterm (16 colours)": {"TERM": "xterm", "COLORTERM": ""},
        "TERM=xterm-256color, COLORTERM unset": {"TERM": "xterm-256color", "COLORTERM": ""},
        "LANG=C": {"LANG": "C", "LC_ALL": "C"},
        "LANG=C.UTF-8": {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
    }
    for label, env in cells.items():
        app = App(artifact, ["--demo"], 120, 30, extra_env=env)
        try:
            app.wait_text("Erin", 90)
            app.settle(1.5)
            checks(f"{label}: starts and draws the map", app.crumb() == ["Home"] and "◉" in app.text(), app.dump())
            app.key("enter", "escape")
            checks(f"{label}: keys work", app.crumb() == ["Home"] and app.alive(), app.dump())
            raw = bytes(app._term._raw)
            if label.startswith("NO_COLOR"):
                colour = len(re.findall(rb"\x1b\[[0-9;]*(?:38;2|48;2|38;5|48;5|3[1-7]|4[0-7])[0-9;]*m", raw))
                checks("NO_COLOR=1: no colour codes are sent", colour == 0, f"{colour} colour sequences in the output")
            if label.startswith("COLORTERM unset, TERM=xterm "):
                checks("16 colours: no 24-bit colour is sent", b"38;2;" not in raw, "truecolor sequences found")
        finally:
            app.close()
    app = App(artifact, ["--demo", "--glyphs", "ascii"], 120, 30)
    try:
        app.wait_text("Erin", 90)
        app.settle(1.5)
        braille = [ln for ln in app.lines() if re.search("[⠀-⣿]", ln)]
        checks("--glyphs ascii: no braille cell is drawn", not braille, "\n".join(braille[:3]))
    finally:
        app.close()
    checks.done()


def test_config_roundtrip_in_an_empty_home(artifact: Path, checks) -> None:  # type: ignore[no-untyped-def]
    app = start_replay(artifact)
    try:
        app.key("S")
        checks("empty home: settings open with defaults", "Poll intervals" in app.text(), app.dump())
        app.key("ctrl+s")
        checks("empty home: ctrl+s saves and closes", not app.has_dialog() and app.alive(), app.dump())
        home(app)
        files = sorted(str(p.relative_to(app.dir)) for p in app.dir.rglob("*") if p.is_file() and "tmp" not in p.parts)
        checks(
            "empty home: the app wrote its files under the config dirs only",
            all(
                f.split("\\")[0]
                in {"appdata", "localappdata", "home", "xdg-config", "xdg-data", "xdg-cache", "xdg-state"}
                for f in files
            ),
            str(files),
        )
    finally:
        app.close()
    checks.done()


@pytest.mark.parametrize("size", [(100, 30), (200, 50)])
def test_other_sizes_reach_screens(artifact: Path, checks, size: tuple[int, int]) -> None:  # type: ignore[no-untyped-def]
    cols, rows = size
    app = start_replay(artifact, cols, rows)
    try:
        for name, keys, ok in (
            ("Storm", ["enter"], lambda a: a.crumb() == ["Home", "Erin"]),
            ("Buoys", ["b"], lambda a: a.crumb()[-1] == "Buoys and gauges"),
            ("Station", ["b", "enter"], lambda a: a.crumb()[-1].startswith("Buoy ")),
            ("Text", ["t"], lambda a: a.crumb()[-1].startswith("NHC text")),
            ("Help", ["?"], lambda a: "previous or next storm" in a.text()),
        ):
            home(app)
            app.key(*keys)
            checks(f"{cols}x{rows}: keyboard reaches {name}", ok(app), app.dump())
            for c in app.footer():
                if c.key in {"q", "o", "y"}:
                    continue
            home(app)
        # click every footer cell on Home at this size: each must leave the app alive and sensible
        for c in app.footer():
            if c.key == "q":
                continue
            home(app)
            app.click(c.mid, c.y)
            checks(
                f"{cols}x{rows}: Home footer click '{c.key} {c.label}' does something",
                app.crumb() != [""] and app.alive(),
                app.dump(),
            )
        home(app)
        checks(f"{cols}x{rows}: no contradictions", not app.violations, "\n".join(app.violations))
    finally:
        app.close()
    checks.done()
