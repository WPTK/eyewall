"""Moves shared by the walkthroughs: start the replay, get home, tell whether two screens are the same."""

from __future__ import annotations

import re
import time
from pathlib import Path

from .app import App

REPLAY_ARGS = ["--demo"]


def start_replay(
    exe: Path, cols: int = 120, rows: int = 30, *, pause: bool = True, args: list[str] | None = None
) -> App:
    app = App(exe, args if args is not None else REPLAY_ARGS, cols, rows)
    app.wait_text("Erin", 120)
    app.settle(1.0)
    if pause:
        set_paused(app, True)
    return app


def is_paused(app: App) -> bool:
    return "paused" in app.header_status()


def set_paused(app: App, paused: bool) -> None:
    if is_paused(app) != paused:
        app.key("space")
    app.wait_for(lambda a: is_paused(a) == paused, 10, f"replay {'paused' if paused else 'playing'}")


def header_clock(app: App) -> str:
    m = re.search(r"\b\w{3} \d{1,2} \w{3} \d\d:\d\dZ", app.header_status())
    return m.group(0) if m else ""


def ticks(app: App, seconds: float = 3.0) -> tuple[str, str]:
    """Let the replay run so the app refreshes at least twice (storms poll every 5 virtual minutes, 300x), then pause."""
    before = header_clock(app)
    set_paused(app, False)
    time.sleep(seconds)
    set_paused(app, True)
    return before, header_clock(app)


def home(app: App) -> None:
    """Back to the first screen with no dialog open, by Esc (what a person does)."""
    for _ in range(10):
        if app.crumb() == ["Home"] and not app.has_dialog():
            return
        app.key("escape")
    raise AssertionError("could not get back to Home with Esc\n" + app.dump())


def cleaned(app: App) -> list[str]:
    """The screen without the toast column and the clock, so two states can be compared."""
    out = []
    for i, ln in enumerate(app.lines()):
        if i == 0:
            ln = re.split(r"\s{3,}", ln, maxsplit=1)[0]  # the crumb; the clock and status are not content
        elif i < app.rows - 1:
            ln = ln[:57]  # toasts sit right of column 58 and come and go on their own
        out.append(ln.rstrip())
    return out


def sig(app: App) -> str:
    return "\n".join(cleaned(app))
