"""What the terminal can show, decided once at startup, and putting it back the way it was found.

`detect()` reads the environment into one `Capabilities`; `cli.main` computes it once and everything else (the colour
system Textual uses, the glyph set, `--diagnose`) follows from that object rather than looking at the environment
again. `RESTORE_SEQUENCE` is what a crash or Ctrl-C needs to emit so the shell is not left in mouse tracking mode, on
the alternate screen, or without a cursor.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, TextIO

ColorDepth = Literal["truecolor", "256", "16", "none"]

# The colour system names Rich (and so Textual) takes; None means no colour.
_RICH_SYSTEM: dict[ColorDepth, str | None] = {"truecolor": "truecolor", "256": "256", "16": "standard", "none": None}

# Mouse tracking off (all modes and encodings), bracketed paste off, focus reporting off, kitty keyboard flags popped,
# cursor shown, alternate screen left, attributes reset.
RESTORE_SEQUENCE = (
    "\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1005l\x1b[?1006l\x1b[?1015l"
    "\x1b[?2004l\x1b[?1004l\x1b[<u\x1b[?25h\x1b[?1049l\x1b[0m"
)


@dataclass(frozen=True, slots=True)
class Capabilities:
    color: ColorDepth
    unicode: bool  # the locale and terminal can show braille and box drawing
    mouse: bool
    term: str
    colorterm: str
    encoding: str
    columns: int
    lines: int

    @property
    def rich_color_system(self) -> str | None:
        return _RICH_SYSTEM[self.color]


def _color(env: Mapping[str, str], windows: bool) -> ColorDepth:
    term = env.get("TERM", "").lower()
    if env.get("NO_COLOR") or term == "dumb":
        return "none"
    if env.get("COLORTERM", "").lower() in ("truecolor", "24bit"):
        return "truecolor"
    if "256color" in term or "direct" in term:
        return "256"
    if windows and not term:
        return "truecolor" if env.get("WT_SESSION") or env.get("TERM_PROGRAM") else "256"
    return "16"


def _unicode(env: Mapping[str, str], encoding: str, windows: bool) -> bool:
    term = env.get("TERM", "").lower()
    if term in ("dumb", "linux"):  # the Linux console has no braille
        return False
    if "utf" not in encoding.lower().replace("_", "-"):
        return False
    if windows:  # the legacy console host takes UTF-8 but draws braille as boxes
        return bool(env.get("WT_SESSION") or env.get("TERM_PROGRAM") or env.get("ConEmuPID") or term)
    locale = next((env[k] for k in ("LC_ALL", "LC_CTYPE", "LANG") if env.get(k)), "")
    return not locale or "utf" in locale.lower().replace("_", "-")


def detect(
    environ: Mapping[str, str] | None = None,
    *,
    encoding: str | None = None,
    size: tuple[int, int] | None = None,
    windows: bool | None = None,
) -> Capabilities:
    env = os.environ if environ is None else environ
    is_windows = sys.platform == "win32" if windows is None else windows
    if encoding is None:
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
    if size is None:
        try:
            cols, rows = os.get_terminal_size(sys.__stdout__.fileno())  # type: ignore[union-attr]
        except (OSError, ValueError, AttributeError):
            cols, rows = 0, 0
    else:
        cols, rows = size
    term = env.get("TERM", "")
    return Capabilities(
        color=_color(env, is_windows),
        unicode=_unicode(env, encoding, is_windows),
        mouse=term.lower() != "dumb",
        term=term,
        colorterm=env.get("COLORTERM", ""),
        encoding=encoding,
        columns=cols,
        lines=rows,
    )


def apply(caps: Capabilities) -> None:
    """Tell Textual what `caps` decided: its colour system, and NO_COLOR for a terminal with none."""
    from textual import constants

    setattr(constants, "COLOR_SYSTEM", caps.rich_color_system or "auto")  # noqa: B010 (Final in the stubs)
    if caps.color == "none":
        os.environ["NO_COLOR"] = os.environ.get("NO_COLOR") or "1"


def restore(stream: TextIO | None = None) -> None:
    """Write `RESTORE_SEQUENCE` to a terminal (never a file or pipe); harmless when the app already restored it."""
    out = stream if stream is not None else sys.__stdout__
    try:
        if out is None or not out.isatty():
            return
        out.write(RESTORE_SEQUENCE)
        out.flush()
    except (OSError, ValueError):
        pass
