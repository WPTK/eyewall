"""The README's command line, run for real in a subprocess: each flag does what it says, and bad input is a clean error."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.uat
ROOT = Path(__file__).resolve().parents[2]


def run(*args: str, timeout: int = 90) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "NO_COLOR": "1"}
    return subprocess.run(
        [sys.executable, "-m", "eyewall", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        env=env,
        cwd=ROOT,
    )


def clean(out: subprocess.CompletedProcess[str]) -> None:
    assert "Traceback" not in out.stdout + out.stderr, out.stderr


def test_version() -> None:
    out = run("--version")
    assert out.returncode == 0 and out.stdout.startswith("eyewall 0."), out.stdout


def test_help_lists_flags() -> None:
    out = run("--help")
    for flag in ("--demo", "--replay", "--basin", "--summary", "--glyphs", "--headless", "--until", "--config", "--no-config", "--state-dir"):
        assert flag in out.stdout, flag


def test_demo_summary() -> None:
    out = run("--demo", "--summary")
    assert out.returncode == 0 and "Hurricane Erin" in out.stdout, out.stdout + out.stderr
    clean(out)


def test_basin_filter() -> None:
    out = run("--demo", "--basin", "EP", "--summary")
    assert out.returncode == 0
    assert "East Pacific" in out.stdout and "Erin" not in out.stdout, out.stdout


def test_bad_basin() -> None:
    out = run("--basin", "XX", "--summary")
    assert out.returncode == 2 and "invalid choice" in out.stderr
    clean(out)


def test_bad_glyphs() -> None:
    out = run("--glyphs", "emoji", "--summary", "--demo")
    assert out.returncode == 2
    clean(out)


def test_unknown_flag() -> None:
    out = run("--bogus")
    assert out.returncode == 2 and "usage" in out.stderr
    clean(out)


def test_glyphs_ascii() -> None:
    out = run("--demo", "--summary", "--glyphs", "ascii")
    assert out.returncode == 0 and all(not 0x2800 <= ord(c) <= 0x28FF for c in out.stdout), "braille in ascii mode"


def test_replay_missing_dir() -> None:
    out = run("--replay", str(ROOT / "nope-not-a-recording"), "--summary")
    assert out.returncode == 2 and "manifest" in out.stderr, out.stderr
    clean(out)


def test_headless_until() -> None:
    out = run("--demo", "--headless", "--until", "+1h")
    assert out.returncode == 0 and "Erin" in out.stdout and "event(s)" in out.stderr, out.stdout + out.stderr
    clean(out)


def test_headless_bad_until() -> None:
    out = run("--demo", "--headless", "--until", "whenever")
    assert out.returncode != 0
    clean(out)


def test_no_config() -> None:
    out = run("--no-config", "--demo", "--summary")
    assert out.returncode == 0 and "Erin" in out.stdout


def test_config_path(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text('[units]\npreset = "metric"\n', encoding="utf-8")
    out = run("--config", str(cfg), "--demo", "--summary")
    assert out.returncode == 0 and "Erin" in out.stdout, out.stderr
    clean(out)


def test_config_garbage(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text("this is [not toml", encoding="utf-8")
    out = run("--config", str(cfg), "--demo", "--summary")
    clean(out)  # a clean message or a fallback, never a traceback


def test_state_dir(tmp_path: Path) -> None:
    out = run("--demo", "--headless", "--until", "+1h", "--state-dir", str(tmp_path))
    assert out.returncode == 0 and any(tmp_path.iterdir()), "nothing was kept in the state dir"
