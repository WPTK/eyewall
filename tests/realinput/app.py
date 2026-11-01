"""The eyewall adapter over the vendored ``tests/uat_kit`` terminal: launching the built exe, reading the screen for sense.

Only this module knows how eyewall lays out its screen (crumb in row 0, footer in the last row, ``reverse`` video on
the marked map glyph). Swapping the driver means changing ``App._term`` and the few ``self._term`` calls here.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

from tests.uat_kit import Terminal

# Strings that mean a screen is broken, whatever it is showing.
BAD_TEXT = ("Traceback", "Exception", "NameError", "KeyError", "AttributeError", "TypeError", "ValueError")
MAP_GLYPHS = {"storm": "◉", "buoy": "●", "gauge": "▲"}
CRUMB_SEP = " › "


@dataclass(frozen=True)
class FooterCell:
    key: str
    label: str
    x: int  # first column of the key
    y: int
    end: int  # one past the last column of the label

    @property
    def mid(self) -> int:
        return (self.x + self.end - 1) // 2


def parse_footer(line: str, y: int) -> list[FooterCell]:
    """Cells of the footer row: ``key label`` items separated by two or more spaces."""
    cells = []
    for m in re.finditer(r"(?<!\S)(\S+) (\S.*?)(?=\s{2,}|$)", line.rstrip()):
        cells.append(FooterCell(m.group(1), m.group(2), m.start(), y, m.end()))
    return cells


def parse_crumb(line: str) -> list[tuple[str, int]]:
    """Segments of the breadcrumb in row 0 as (text, start column). The crumb ends at the first run of 3+ spaces."""
    head = re.split(r"\s{3,}", line.strip("\x00"), maxsplit=1)[0] if line.strip() else ""
    out, pos = [], 0
    for part in head.split(CRUMB_SEP):
        start = line.find(part, pos)
        out.append((part.strip(), start))
        pos = start + len(part)
    return out


def parse_help(lines: list[str], section: str = "") -> tuple[list[tuple[str, str, str]], str]:
    """Key rows on one page of the help dialog as (section, key cell, sentence), and the section the page ends in.

    A section title is a line with one run of text; a key row has the keys, a gap of three or more spaces, then the
    sentence. Pages overlap when scrolled, so callers de-duplicate."""
    rows: list[tuple[str, str, str]] = []
    for raw in lines:
        m = re.match(r"^\s*│  (\S.*?)\s*(?:│|▌.*)?$", raw)
        if not m:
            continue
        body = m.group(1)
        km = re.match(r"^(\S(?:.*?\S)?) {3,}(\S.*?)$", body)
        if km:
            rows.append((section, km.group(1), km.group(2)))
        elif body.strip() and not body.startswith("Esc closes"):
            section = body.strip()
    return rows, section


def help_tokens(keys: str) -> list[str]:
    """Split a help key cell (``j  k  Enter``, ``+/-``, ``[ ]``) into single keys."""
    toks: list[str] = []
    for tok in keys.split("  "):
        tok = tok.strip()
        if not tok:
            continue
        if tok == "+/-":
            toks += ["+", "-"]
        elif tok == "[ ]":
            toks += ["[", "]"]
        elif tok == "left/right":
            toks += ["Left", "Right"]
        elif tok == "< >":
            toks += ["<", ">"]
        else:
            toks += [t for t in tok.split(" ") if t]
    return toks


# Keys the kit's table lacks: sent as the raw character a terminal sends.
RAW_KEYS = {"backspace": "\x7f", "ctrl+p": "\x10", "ctrl+s": "\x13", "pageup": "\x1b[5~", "pagedown": "\x1b[6~"}


class App:
    """The exe on a pseudo-console. ``violations`` collects every contradiction ``sense`` finds after an action."""

    def __init__(
        self,
        exe: Path,
        args: list[str],
        cols: int = 120,
        rows: int = 30,
        *,
        proxy: str | None = None,
        extra_env: dict[str, str] | None = None,
        cwd: Path | None = None,
        sense: bool = True,
        state_root: Path | None = None,
    ) -> None:
        env = {
            "HOME": "{dir}/home",
            "USERPROFILE": "{dir}/home",
            "TEMP": "{dir}/tmp",
            "TMP": "{dir}/tmp",
            "XDG_STATE_HOME": "{dir}/xdg-state",
            "BROWSER": "cmd /c exit 0 #%s",  # `o` in Pictures must not open a real browser
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "NO_COLOR": "",
        }
        if state_root is not None:  # one home shared by several runs (upgrade and uninstall scenarios)
            for sub in ("home", "appdata", "localappdata", "xdg-config", "xdg-data", "xdg-cache", "xdg-state", "tmp"):
                (state_root / sub).mkdir(parents=True, exist_ok=True)
            env.update(
                HOME=str(state_root / "home"),
                USERPROFILE=str(state_root / "home"),
                APPDATA=str(state_root / "appdata"),
                LOCALAPPDATA=str(state_root / "localappdata"),
                XDG_CONFIG_HOME=str(state_root / "xdg-config"),
                XDG_DATA_HOME=str(state_root / "xdg-data"),
                XDG_CACHE_HOME=str(state_root / "xdg-cache"),
                XDG_STATE_HOME=str(state_root / "xdg-state"),
                TEMP=str(state_root / "tmp"),
                TMP=str(state_root / "tmp"),
            )
        if proxy:
            env.update(HTTP_PROXY=proxy, HTTPS_PROXY=proxy, ALL_PROXY=proxy, http_proxy=proxy, https_proxy=proxy)
        env.update(extra_env or {})
        self.args = args
        self.exe = exe
        self._term = Terminal(
            [str(exe), *args],
            cols,
            rows,
            env=env,
            env_remove=("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME", "NO_COLOR"),
            cwd=cwd,
        )
        for d in ("home", "tmp", "xdg-state"):
            (self._term.dir / d).mkdir(parents=True, exist_ok=True)
        self.dir: Path = self._term.dir
        self.pid: int = self._term.pid
        self.violations: list[str] = []
        self.do_sense = sense
        self.log: list[str] = []

    # -- plumbing -------------------------------------------------------------------------------------------------
    def close(self) -> None:
        self._term.close()

    def __enter__(self) -> App:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def cols(self) -> int:
        return int(self._term.cols)

    @property
    def rows(self) -> int:
        return int(self._term.rows)

    def alive(self) -> bool:
        return bool(self._term.alive())

    def wait_exit(self, timeout: float = 15.0) -> int | None:
        return self._term.wait_exit(timeout)

    # -- reading --------------------------------------------------------------------------------------------------
    def lines(self) -> list[str]:
        return list(self._term.screen().lines)

    def text(self) -> str:
        return "\n".join(self.lines())

    def dump(self) -> str:
        return "\n".join(f"{i:02d}|{ln}" for i, ln in enumerate(self.lines()))

    def style(self, x: int, y: int) -> tuple[str, str, bool, bool]:
        """(fg, bg, bold, reverse) of one cell, read from the emulator behind the kit."""
        with self._term._lock:
            c = self._term._screen.buffer[y][x]
            return str(c.fg), str(c.bg), bool(c.bold), bool(c.reverse)

    def reverse_cells(self, glyphs: str) -> list[tuple[int, int]]:
        """Cells showing one of ``glyphs`` in reverse video (the marked map symbol)."""
        out = []
        with self._term._lock:
            for y, line in enumerate(self._term._screen.display):
                for x, ch in enumerate(line):
                    if ch in glyphs and self._term._screen.buffer[y][x].reverse:
                        out.append((x, y))
        return out

    def row_bg(self, y: int) -> str:
        """Most common background on a row: a highlighted list row differs from the rows around it."""
        counts: dict[str, int] = {}
        with self._term._lock:
            for x in range(self.cols):
                bg = str(self._term._screen.buffer[y][x].bg)
                counts[bg] = counts.get(bg, 0) + 1
        return max(counts, key=lambda k: counts[k])

    def row_has_reverse_or_bg(self, y: int, base_bg: str) -> bool:
        return self.row_bg(y) != base_bg

    def crumb(self) -> list[str]:
        return [t for t, _ in parse_crumb(self.lines()[0])]

    def crumb_cells(self) -> list[tuple[str, int]]:
        return parse_crumb(self.lines()[0])

    def footer(self) -> list[FooterCell]:
        return parse_footer(self.lines()[self.rows - 1], self.rows - 1)

    def header_status(self) -> str:
        line = self.lines()[0]
        parts = re.split(r"\s{3,}", line.strip(), maxsplit=1)
        return parts[1].strip() if len(parts) > 1 else ""

    def has_dialog(self) -> bool:
        """A boxed dialog, or the menu / find overlay (a bar of ▔ across the top of its list)."""
        return "╭" in self.text() or any(ln.startswith("▔▔▔▔▔▔") for ln in self.lines())

    def find(self, needle: str) -> tuple[int, int] | None:
        return self._term.screen().find(needle)

    def find_all(self, needle: str) -> list[tuple[int, int]]:
        out = []
        for y, ln in enumerate(self.lines()):
            start = 0
            while (i := ln.find(needle, start)) >= 0:
                out.append((i, y))
                start = i + 1
        return out

    def map_width(self) -> int:
        """Columns of the map: left of the vertical rule that borders the side panel (full width when none)."""
        for ln in self.lines()[3:12]:
            if "│" in ln:
                return ln.index("│")
        return self.cols

    # -- waiting --------------------------------------------------------------------------------------------------
    def wait_text(self, needle: str, timeout: float = 20.0) -> None:
        self._term.wait_for_text(needle, timeout)

    def wait_for(self, pred, timeout: float = 20.0, what: str = "") -> None:  # type: ignore[no-untyped-def]
        self._term.wait_for(lambda s: pred(self), timeout, what)

    def settle(self, quiet: float = 0.9, timeout: float = 8.0) -> None:
        """Wait until the screen text has not changed for ``quiet`` seconds (the app redraws in more than one step)."""
        end = time.monotonic() + timeout
        last = self.lines()
        stamp = time.monotonic()
        while time.monotonic() < end:
            time.sleep(0.05)
            now = self.lines()
            if now != last:
                last, stamp = now, time.monotonic()
            elif time.monotonic() - stamp >= quiet:
                return

    # -- acting ---------------------------------------------------------------------------------------------------
    def key(self, *names: str, settle: bool = True) -> None:
        for n in names:
            self.log.append(f"key {n}")
            self._term.send_keys(RAW_KEYS.get(n.lower(), n))
            if settle:
                self.settle()
        self._sense()

    def click(self, x: int, y: int, settle: bool = True) -> None:
        self.log.append(f"click {x},{y}")
        self._term.click(x, y)
        if settle:
            self.settle()
        self._sense()

    def click_text(self, needle: str) -> tuple[int, int]:
        found = self.find(needle)
        if found is None:
            raise AssertionError(f"{needle!r} is not on screen:\n{self.dump()}")
        x, y = found[0] + len(needle) // 2, found[1]
        self.click(x, y)
        return x, y

    def hover(self, x: int, y: int) -> None:
        self._term.mouse("move", x, y)
        self.settle(0.25)
        self._sense()

    def wheel(self, x: int, y: int, up: bool) -> None:
        self._term.mouse("wheel_up" if up else "wheel_down", x, y)
        self.settle(0.25)
        self._sense()

    def resize(self, cols: int, rows: int) -> None:
        self.log.append(f"resize {cols}x{rows}")
        self._term.resize(cols, rows)
        time.sleep(0.4)
        self.settle(0.6)
        self._sense()

    # -- sense ----------------------------------------------------------------------------------------------------
    def _sense(self) -> None:
        if self.do_sense:
            for v in sense_violations(self.lines(), self.cols, self.rows):
                self.violations.append(f"{v} [after {self.log[-1] if self.log else 'start'}]")


def sense_violations(lines: list[str], cols: int, rows: int) -> list[str]:
    """Rules a person applies by looking: things on one screen that must agree, or must not appear."""
    text = "\n".join(lines)
    out: list[str] = []
    for bad in BAD_TEXT:
        if bad in text:
            out.append(f"error text {bad!r} on screen")
    if len(lines) != rows:
        out.append(f"screen has {len(lines)} rows, expected {rows}")
    if not text.strip():
        out.append("blank screen")
        return out
    head = lines[0]
    # the status slot cannot say two opposite things
    if "▶ replay" in head and "paused" in head:
        out.append("header says both playing and paused")
    if "live" in head.lower() and "replay" in head.lower():
        out.append("header says both live and replay")
    if re.search(r"\boffline\b", head, re.I) and re.search(r"\bfresh\b|\ball feeds ok\b|\blive\b", head, re.I):
        out.append("header says offline and fresh/live together")
    m = re.search(r"(\d+) feeds? failing", head)
    if m and "feed failing" in head and m.group(1) != "1":
        out.append("header grammar: 'feed failing' with a count other than 1")
    if "feeds failing" in head and (m and m.group(1) == "1"):
        out.append("header grammar: '1 feeds failing'")
    m = re.search(r"\b(1) alerts\b", head)
    if m:
        out.append("header grammar: '1 alerts'")
    # the footer: one row, the pinned keys, and back/quit taking turns (compact form at narrow widths: "? ^p esc")
    if cols >= 60 and rows >= 16:
        foot = lines[rows - 1]
        toks = foot.split()
        if foot.strip():
            if "?" not in toks or "^p" not in toks:
                out.append("footer lacks the pinned '?' and '^p' cells")
            crumb = parse_crumb(head)
            is_home = len(crumb) == 1 and crumb[0][0] == "Home"
            quit_shown = "q quit" in foot or (toks[-1:] == ["q"])
            if quit_shown and not is_home and "╭" not in text:
                out.append("footer offers quit away from the first screen")
            cells = parse_footer(foot, rows - 1)
            if len({c.key for c in cells}) != len(cells):
                out.append("footer repeats a key")
    return out
