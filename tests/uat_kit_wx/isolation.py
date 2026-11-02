"""Keep a UAT run out of the real user profile, and prove it did.

``isolated_env`` builds the environment of one launch: every location the app (or platformdirs, or the PyInstaller
bootloader) could write to is a directory inside the run's own scratch root. ``assert_isolated`` is called before the
launch and fails when any of those variables points anywhere else. ``RealFolders`` hashes the real folders of the user
running the suite (names, sizes, mtimes, content sha256) before and after the session; the session fails if they differ.
Test-only.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from pathlib import Path

# Every variable that decides where a program writes, and where it goes below the scratch root.
ISOLATED = {
    "HOME": "home",
    "USERPROFILE": "home",
    "APPDATA": "home/AppData/Roaming",
    "LOCALAPPDATA": "home/AppData/Local",
    "WIN_PD_OVERRIDE_APPDATA": "home/AppData/Roaming",  # platformdirs on Windows ignores APPDATA; this is what it reads
    "WIN_PD_OVERRIDE_LOCAL_APPDATA": "home/AppData/Local",
    "XDG_CONFIG_HOME": "home/.config",
    "XDG_CACHE_HOME": "home/.cache",
    "XDG_DATA_HOME": "home/.local/share",
    "XDG_STATE_HOME": "home/.local/state",
    "TEMP": "tmp",
    "TMP": "tmp",
    "TMPDIR": "tmp",
}


def isolated_env(root: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    """The isolation variables for a launch rooted at ``root`` (the directories are created), plus ``extra``."""
    env = {}
    for name, rel in ISOLATED.items():
        path = Path(root) / rel
        path.mkdir(parents=True, exist_ok=True)
        env[name] = str(path)
    env.update(extra or {})
    return env


def assert_isolated(env: dict[str, str], root: Path) -> None:
    """Fail unless every isolation variable in ``env`` is set and lies inside ``root``."""
    base = Path(root).resolve()
    for name in ISOLATED:
        value = env.get(name)
        assert value, f"isolation: {name} is not set for this launch"
        assert Path(value).resolve().is_relative_to(base), f"isolation: {name}={value} is outside the run root {base}"


def real_folders() -> list[Path]:
    """The folders of the user running the suite that eyewall could write to (whether or not they exist yet)."""
    home = Path(os.path.expanduser("~"))
    out = [home / ".config" / "eyewall", home / ".cache" / "eyewall", home / ".local" / "state" / "eyewall"]
    out.append(home / ".local" / "share" / "eyewall")
    for var in ("LOCALAPPDATA", "APPDATA"):
        if os.environ.get(var):
            out.append(Path(os.environ[var]) / "eyewall")
    return out


def snapshot(folders: list[Path]) -> dict[str, tuple[int, int, str]]:
    """{path: (size, mtime_ns, sha256)} for every file under ``folders``; directories appear with size -1."""
    snap: dict[str, tuple[int, int, str]] = {}
    for folder in folders:
        if not folder.exists():
            continue
        for p in _walk(folder):
            st = p.stat()
            if p.is_dir():
                snap[str(p)] = (-1, st.st_mtime_ns, "")
            else:
                try:
                    digest = hashlib.sha256(p.read_bytes()).hexdigest()
                except OSError as exc:  # unreadable still counts as a state; a change in the error shows as a diff
                    digest = f"unreadable:{type(exc).__name__}"
                snap[str(p)] = (st.st_size, st.st_mtime_ns, digest)
    return snap


def _walk(folder: Path) -> Iterator[Path]:
    yield folder
    yield from sorted(folder.rglob("*"))


def diff(before: dict[str, tuple[int, int, str]], after: dict[str, tuple[int, int, str]]) -> list[str]:
    """Human-readable differences between two snapshots (empty when identical)."""
    out = [f"added: {p}" for p in sorted(after.keys() - before.keys())]
    out += [f"removed: {p}" for p in sorted(before.keys() - after.keys())]
    out += [f"changed: {p}" for p in sorted(before.keys() & after.keys()) if before[p] != after[p]]
    return out


class RealFolders:
    """Snapshot at construction, ``check()`` at the end of the session."""

    def __init__(self, folders: list[Path] | None = None) -> None:
        self.folders = real_folders() if folders is None else folders
        self.before = snapshot(self.folders)

    def check(self) -> list[str]:
        return diff(self.before, snapshot(self.folders))


def guard_real_folders() -> Iterator[None]:
    """Body of a session fixture: fails the session when anything under the real folders changed while it ran."""
    guard = RealFolders()
    yield
    changed = guard.check()
    assert not changed, "the run changed the real user folders:\n" + "\n".join(changed[:20])
