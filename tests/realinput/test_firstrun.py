"""First run of the wheel the README's `pip install` route builds, in a fresh venv on every Python 3.12+ on this machine.

The README routes are: a standalone binary (covered by every other scenario), `pipx install git+https://...` and a clone
with `pip install -e .`. pipx builds the same wheel from the repository, so the wheel is installed here without a
repo, a venv of ours or a config: only the wheel and an empty directory.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from .app import App
from .conftest import COLLECTOR

REPO = Path(__file__).resolve().parents[2]


def installed_pythons() -> list[tuple[str, Path]]:
    """(version, path) for every Python 3.12 or newer the Windows launcher knows."""
    out = subprocess.run(["py", "-0p"], capture_output=True, text=True, check=False).stdout
    found = []
    for m in re.finditer(r"-V:(\d+\.\d+)\S*\s+\*?\s*(\S.*python\.exe)", out):
        v = tuple(int(p) for p in m.group(1).split("."))
        if v >= (3, 12):
            found.append((m.group(1), Path(m.group(2).strip())))
    return found


@pytest.fixture(scope="module")
def wheel() -> Iterator[Path]:
    out = Path(tempfile.mkdtemp(prefix="ew-wheel-"))
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(out), str(REPO)], check=True, capture_output=True
    )
    yield next(out.glob("eyewall-*.whl"))
    shutil.rmtree(out, ignore_errors=True)


def _run(
    cmd: list[str], cwd: Path, env: dict[str, str] | None = None, timeout: int = 180
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env, encoding="utf-8", errors="replace"
    )


def test_wheel_installs_and_runs_on_every_python(wheel: Path, checks, note) -> None:  # type: ignore[no-untyped-def]
    pythons = installed_pythons()
    note("pythons", ", ".join(f"{v} ({p})" for v, p in pythons))
    checks("README range: at least one Python 3.12+ is installed", bool(pythons), "py -0p lists none")
    versions = {v for v, _ in pythons}
    for missing in ("3.12", "3.13"):
        if missing not in versions:
            checks.skip(f"Python {missing}", "not installed on this machine")
    for version, python in pythons:
        work = Path(tempfile.mkdtemp(prefix=f"ew-first-{version}-"))
        try:
            venv = work / "venv"
            r = _run([str(python), "-m", "venv", str(venv)], work)
            checks(f"py{version}: venv created", r.returncode == 0, r.stderr[-300:])
            py = venv / "Scripts" / "python.exe"
            r = _run([str(py), "-m", "pip", "install", "--quiet", str(wheel)], work, timeout=600)
            checks(f"py{version}: pip install of the wheel", r.returncode == 0, (r.stdout + r.stderr)[-500:])
            if r.returncode:
                continue
            exe = venv / "Scripts" / "eyewall.exe"
            r = _run([str(exe), "--version"], work)
            checks(
                f"py{version}: eyewall --version",
                r.returncode == 0 and re.match(r"eyewall \d+\.\d+\.\d+", r.stdout) is not None,
                r.stdout + r.stderr,
            )
            r = _run([str(exe), "--demo", "--summary"], work)
            checks(
                f"py{version}: eyewall --demo --summary prints sentences",
                r.returncode == 0 and "Erin" in r.stdout,
                (r.stdout + r.stderr)[-400:],
            )
            r = _run([str(exe), "--selftest"], work)
            checks(
                f"py{version}: eyewall --selftest",
                r.returncode == 0 and "selftest ok" in r.stdout,
                (r.stdout + r.stderr)[-400:],
            )
            r = _run(
                [
                    str(py),
                    "-I",
                    "-c",
                    "import importlib.resources as r, eyewall; p=r.files('eyewall'); print((p/'demo'/'erin2025').is_dir(), (p/'mapdata').is_dir())",
                ],
                work,
            )
            checks(
                f"py{version}: package data (demo recording, map data) is inside the wheel",
                r.stdout.split() == ["True", "True"],
                r.stdout + r.stderr,
            )
            app = App(exe, ["--demo"], 120, 30, cwd=work)
            try:
                app.wait_text("Erin", 90)
                app.settle(1.5)
                checks(
                    f"py{version}: short ConPTY launch shows the map",
                    app.crumb() == ["Home"] and "◉" in app.text(),
                    app.dump(),
                )
                app.key("q", settle=False)
                checks(f"py{version}: q exits with code 0", app.wait_exit(20) == 0, "no clean exit")
            finally:
                app.close()
        finally:
            shutil.rmtree(work, ignore_errors=True)
    COLLECTOR.notes["first_run_pythons"] = ", ".join(sorted(versions))
    checks.done()
