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
    if windows and (env.get("WT_SESSION") or env.get("TERM_PROGRAM")):  # before any TERM guess: ssh sets TERM too
        return "truecolor"
    if env.get("COLORTERM", "").lower() in ("truecolor", "24bit"):
        return "truecolor"
    if "256color" in term or "direct" in term:
        return "256"
    if windows and not term:
        return "256"
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
    """Tell Textual what `caps` decided: its colour system (left on auto for 16 colours), NO_COLOR for none."""
    from textual import constants

    if caps.color in ("truecolor", "256"):
        setattr(constants, "COLOR_SYSTEM", caps.rich_color_system)  # noqa: B010 (Final in the stubs)
    elif caps.color == "none":
        setattr(constants, "COLOR_SYSTEM", None)  # noqa: B010
        os.environ["NO_COLOR"] = os.environ.get("NO_COLOR") or "1"


def terminal_stream() -> TextIO | None:
    """The stream Textual draws on, if it is a terminal: stderr on POSIX, stdout on Windows (the other as fallback)."""
    order = (sys.__stdout__, sys.__stderr__) if sys.platform == "win32" else (sys.__stderr__, sys.__stdout__)
    for stream in order:
        try:
            if stream is not None and stream.isatty():
                return stream
        except (OSError, ValueError):
            continue
    return None


def restore(stream: TextIO | None = None) -> None:
    """After an abnormal exit write `RESTORE_SEQUENCE` to the terminal (never a file or pipe).

    It only turns terminal modes off; it does not save or restore termios or Windows console modes.
    """
    out = stream if stream is not None else terminal_stream()
    if out is None:
        return
    try:
        out.write(RESTORE_SEQUENCE)
        out.flush()
    except (OSError, ValueError):
        pass
