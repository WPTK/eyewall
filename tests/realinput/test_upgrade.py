"""Upgrade and uninstall: the release exe, then the exe under test, on the same home; then remove it all.

The "old" exe is the published v0.9.0 asset. When the exe under test is that same asset the sequence still runs, so
the upgrade path is exercised on every release and checked against a different build once there is one.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .app import App
from .conftest import ASSET, COLLECTOR, RELEASE_TAG
from .walk import home, start_replay  # noqa: F401


def _tree(root: Path) -> dict[str, str]:
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()[:12]
    return out


def _real_profile_dirs() -> list[Path]:
    home_dir = Path(os.path.expanduser("~"))
    cands = [
        Path(os.environ.get("APPDATA", "")) / "eyewall",
        Path(os.environ.get("LOCALAPPDATA", "")) / "eyewall",
        Path(os.environ.get("LOCALAPPDATA", "")) / "eyewall" / "eyewall",
        home_dir / ".config" / "eyewall",
        home_dir / ".local" / "share" / "eyewall",
        home_dir / ".eyewall",
    ]
    return [c for c in cands if str(c) not in ("eyewall", ".")]


def test_upgrade_in_place_then_uninstall(artifact: Path, checks) -> None:  # type: ignore[no-untyped-def]
    work = Path(tempfile.mkdtemp(prefix="ew-upgrade-"))
    old_dir = Path(tempfile.mkdtemp(prefix="ew-old-"))
    try:
        subprocess.run(
            ["gh", "release", "download", RELEASE_TAG, "-R", "WPTK/eyewall", "-p", ASSET, "-D", str(old_dir)],
            check=True,
            capture_output=True,
        )
        old = old_dir / ASSET
        real_before = {str(p): p.exists() for p in _real_profile_dirs()}
        root = work / "state"
        # 1. the old exe creates its config and state
        app = App(old, ["--demo"], 120, 30, state_root=root, cwd=work)
        try:
            app.wait_text("Erin", 90)
            app.settle(1.0)
            app.key("u")  # change units so there is a setting to carry over
            app.key("S")
            app.key("ctrl+s")
            app.key("b", "f")  # follow a station: state the new build must keep
            home(app)
            app.key("q", settle=False)
            checks("old exe: exits 0", app.wait_exit(20) == 0, "old exe did not exit 0")
        finally:
            app.close()
        after_old = _tree(root)
        created = sorted(k for k in after_old if not k.startswith("tmp"))
        COLLECTOR.notes["files_created_by_the_app"] = "; ".join(created) or "(none)"
        checks("old exe: wrote something (config or state) in its home", bool(created), f"files: {sorted(after_old)}")
        # 2. the build under test on the same home
        app = App(artifact, ["--demo"], 120, 30, state_root=root, cwd=work)
        try:
            app.wait_text("Erin", 90)
            app.settle(1.5)
            checks(
                "new exe on the old home: starts without an error",
                app.crumb() == ["Home"] and not app.violations,
                app.dump(),
            )
            app.key("S")
            checks("new exe: settings open and read the old file", "Poll intervals" in app.text(), app.dump())
            app.key("escape")
            app.key("b")
            checks("new exe: Buoys screen opens with the old state", app.crumb()[-1] == "Buoys and gauges", app.dump())
            home(app)
            checks("new exe: no contradictions on the old home", not app.violations, "\n".join(app.violations))
            app.key("q", settle=False)
            checks("new exe: exits 0", app.wait_exit(20) == 0, "did not exit 0")
        finally:
            app.close()
        # 3. uninstall: delete the exe and what the app created; nothing else may remain, nothing outside may have changed
        exe_dir = artifact.parent
        leftover_outside = []
        real_after = {str(p): p.exists() for p in _real_profile_dirs()}
        for path, existed in real_after.items():
            if existed and not real_before.get(path):
                leftover_outside.append(path)
        checks(
            "uninstall: the app wrote nothing to the real profile (APPDATA, LOCALAPPDATA, ~/.config)",
            not leftover_outside,
            str(leftover_outside),
        )
        shutil.rmtree(root, ignore_errors=True)
        checks(
            "uninstall: deleting the home removes everything the app created",
            not root.exists(),
            str(_tree(root) if root.exists() else ""),
        )
        checks(
            "uninstall: the exe sits alone in its directory (no installer files)",
            sorted(p.name for p in exe_dir.iterdir()) == [artifact.name],
            str(list(exe_dir.iterdir())),
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(old_dir, ignore_errors=True)
    checks.done()
