"""The second eyewall adapter: runs the exe (or ``python -m eyewall``) on either terminal kit and reads the screen.

``driver="wx"`` is the tui-test kit vendored here (``tests/uat_kit_wx``); ``driver="old"`` is the pywinpty/pyte kit in
``tests/uat_kit``. Both expose the same surface (Terminal, send_keys, send_raw, click, screen, wait_exit), so a scenario
is written once and run on both. Traps handled here: the exit code is a method on one kit and an attribute on the other;
NO_COLOR is cleared; PYTHONUTF8=1; cells are 0-based.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .isolation import assert_isolated, isolated_env

ESC = "\x1b"
RAW = {
    "space": " ",
    "enter": "\r",
    "esc": ESC,
    "tab": "\t",
    "up": f"{ESC}[A",
    "down": f"{ESC}[B",
    "left": f"{ESC}[D",
    "right": f"{ESC}[C",
}


def terminal_class(driver: str) -> Any:
    if driver == "wx":
        from tests.uat_kit_wx import Terminal
    elif driver == "old":
        from tests.uat_kit import Terminal
    else:
        raise ValueError(driver)
    return Terminal


def sgr(kind: str, col: int, row: int) -> str:
    """One SGR (1006) mouse report at 0-based cell (col, row); the protocol counts from 1."""
    code, final = {"move": (35, "M"), "press": (0, "M"), "release": (0, "m"), "up": (64, "M"), "down": (65, "M")}[kind]
    return f"{ESC}[<{code};{col + 1};{row + 1}{final}"


class Run:
    """One launch. ``exe`` may be a path (copied into a fresh empty temp dir) or an argv prefix list."""

    def __init__(
        self,
        driver: str,
        exe: Path | list[str],
        args: list[str],
        cols: int = 120,
        rows: int = 30,
        *,
        fake: Any = None,
        env: dict[str, str] | None = None,
        no_state_dir: bool = False,
    ) -> None:
        self.driver, self.cols, self.rows = driver, cols, rows
        self.root = Path(tempfile.mkdtemp(prefix="ew-run-"))  # everything this launch can write lives below here
        if isinstance(exe, list):
            prefix = [str(p) for p in exe]
        else:
            (self.root / "exe").mkdir()
            shutil.copy2(exe, self.root / "exe" / exe.name)  # a fresh empty directory: nothing next to it can help
            prefix = [str(self.root / "exe" / exe.name)]
        e = {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "WSLENV": ""}
        if fake is not None:
            e.update(fake.env())
        e.update(env or {})
        e.update(isolated_env(self.root))  # last: a caller cannot point a launch at the real profile
        assert_isolated(e, self.root)  # asserted before every launch
        argv = [*prefix, "--no-config", *args]
        if not no_state_dir:
            argv += ["--state-dir", str(self.root / "state")]
            (self.root / "state").mkdir()
        self.t0 = time.monotonic()
        self.t = terminal_class(driver)(
            argv, cols, rows, env=e, env_remove=("NO_COLOR", "VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME")
        )

    # -- plumbing
    def close(self) -> None:
        self.t.close()
        shutil.rmtree(self.root, ignore_errors=True)

    def __enter__(self) -> Run:
        return self

    def __exit__(self, *a: object) -> None:
        self.close()

    @property
    def pid(self) -> int | None:
        return getattr(self.t, "pid", None)

    def alive(self) -> bool:
        return bool(self.t.alive())

    def exit_code(self) -> int | None:
        ec = self.t.exit_code
        return ec() if callable(ec) else ec

    def wait_exit(self, timeout: float = 15) -> int | None:
        self.t.wait_exit(timeout)
        return self.exit_code()

    # -- reading
    def lines(self) -> list[str]:
        return list(self.t.screen().lines)

    def text(self) -> str:
        return "\n".join(self.lines())

    def dump(self) -> str:
        return "\n".join(f"{i:02d}|{ln}" for i, ln in enumerate(self.lines()))

    def head(self) -> str:
        return self.lines()[0]

    def crumb(self) -> str:
        return re.split(r"\s{3,}", self.head().strip(), maxsplit=1)[0]

    def status(self) -> str:
        parts = re.split(r"\s{3,}", self.head().strip(), maxsplit=1)
        return parts[1].strip() if len(parts) > 1 else ""

    def footer(self) -> str:
        return self.lines()[self.rows - 1]

    def footer_cells(self) -> list[tuple[str, str, int, int]]:
        """(key, label, first col, one past last col) of each footer cell: ``key label`` separated by 2+ spaces."""
        out = []
        for m in re.finditer(r"(?<!\S)(\S+) (\S.*?)(?=\s{2,}|$)", self.footer().rstrip()):
            out.append((m.group(1), m.group(2), m.start(), m.end()))
        return out

    def inverse_marks(self, glyphs: str) -> list[tuple[int, int, str]]:
        """Cells showing one of ``glyphs`` in reverse video: the marked map symbol."""
        out = []
        if self.driver == "wx":
            cells = self.t._run(self.t._t.cells(0, 0, self.cols, self.rows))
            for c in cells:
                if c.char in glyphs and c.inverse:
                    out.append((c.x, c.y, c.char))
        else:
            with self.t._lock:
                for y, line in enumerate(self.t._screen.display):
                    for x, ch in enumerate(line):
                        if ch in glyphs and self.t._screen.buffer[y][x].reverse:
                            out.append((x, y, ch))
        return out

    # -- waiting
    def poll(self, pred: Callable[[Run], bool], timeout: float, step: float = 0.01) -> float | None:
        """Seconds until ``pred(self)`` holds, or None on timeout."""
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            if pred(self):
                return round(time.monotonic() - t0, 3)
            time.sleep(step)
        return None

    def wait_text(self, needle: str, timeout: float = 30) -> bool:
        return self.poll(lambda r: needle in r.text(), timeout, 0.05) is not None

    def settle(self, quiet: float = 0.8, timeout: float = 10) -> None:
        self.t.settle(quiet, timeout)

    # -- acting
    def key(self, *names: str, settle: bool = True, gap: float = 0.08) -> None:
        for n in names:
            self.t.send_raw(RAW.get(n.lower(), n))
            time.sleep(gap)
        if settle:
            self.settle()

    def raw(self, data: str) -> None:
        self.t.send_raw(data)

    def click(self, x: int, y: int, settle: bool = True) -> None:
        self.t.click(x, y)
        if settle:
            self.settle()

    def click_raw_sgr(self, x: int, y: int) -> None:
        """Hand-built bytes: motion in, press, release, 20 ms apart. Independent of either kit's click()."""
        for kind, c in (("move", max(x - 3, 0)), ("move", x), ("press", x), ("release", x)):
            self.t.send_raw(sgr(kind, c, y))
            time.sleep(0.02)
        self.settle()


def run_cli(exe: Path, args: list[str], *, fake: Any = None, timeout: float = 180) -> subprocess.CompletedProcess[str]:
    """A non-interactive run (``--summary``, ``--version``): the exe copied into a fresh directory and the same isolated
    environment as ``Run``. Its cache lives under the run's own profile, so a shared cache cannot hide a failed feed."""
    root = Path(tempfile.mkdtemp(prefix="ew-cli-"))
    try:
        (root / "exe").mkdir()
        shutil.copy2(exe, root / "exe" / exe.name)
        drop = ("NO_COLOR", "SSL_CERT_FILE", "VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME")
        env = {k: v for k, v in os.environ.items() if k not in drop and "PROXY" not in k.upper()}
        env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        if fake is not None:
            env.update(fake.env())
        env.update(isolated_env(root))
        assert_isolated(env, root)
        (root / "state").mkdir()
        return subprocess.run(
            [str(root / "exe" / exe.name), *args, "--no-config", "--state-dir", str(root / "state")],
            env=env,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)
