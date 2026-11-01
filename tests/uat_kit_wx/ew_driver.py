"""The second eyewall adapter: runs the exe (or ``python -m eyewall``) on either terminal kit and reads the screen.

``driver="wx"`` is the tui-test kit vendored here (``tests/uat_kit_wx``); ``driver="old"`` is the pywinpty/pyte kit in
``tests/uat_kit``. Both expose the same surface (Terminal, send_keys, send_raw, click, screen, wait_exit), so a scenario
is written once and run on both. Traps handled here: the exit code is a method on one kit and an attribute on the other;
NO_COLOR is cleared; PYTHONUTF8=1; cells are 0-based.
"""

from __future__ import annotations

import re
import shutil
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

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
        self._exedir: Path | None = None
        if isinstance(exe, list):
            prefix = [str(p) for p in exe]
        else:
            self._exedir = Path(tempfile.mkdtemp(prefix="ew-exe-"))
            shutil.copy2(exe, self._exedir / exe.name)
            prefix = [str(self._exedir / exe.name)]
        e = {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "HOME": "{dir}/home", "USERPROFILE": "{dir}/home"}
        if fake is not None:
            e.update(fake.env())
        e.update(env or {})
        argv = [*prefix, "--no-config", *args]
        if not no_state_dir:
            argv += ["--state-dir", "{dir}/state"]
        self.t0 = time.monotonic()
        self.t = terminal_class(driver)(
            argv, cols, rows, env=e, env_remove=("NO_COLOR", "VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME")
        )
        (self.t.dir / "home").mkdir(exist_ok=True)
        (self.t.dir / "state").mkdir(exist_ok=True)

    # -- plumbing
    def close(self) -> None:
        self.t.close()
        if self._exedir:
            shutil.rmtree(self._exedir, ignore_errors=True)

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
