"""Crash log and `--diagnose`: what to attach to a bug report, without secrets or more of the home path than needed."""

from __future__ import annotations

import asyncio
import platform
import traceback
from datetime import datetime
from pathlib import Path

from platformdirs import user_log_dir

from eyewall import __version__
from eyewall.config import Config
from eyewall.state.alerts import default_state_dir
from eyewall.terminal import Capabilities

ISSUES_URL = "https://github.com/WPTK/eyewall/issues"
KEEP_LOGS = 10


def log_dir() -> Path:
    return Path(user_log_dir("eyewall", appauthor=False))


def scrub(text: str) -> str:
    """Replace the home directory (and the user name in it) with `~`."""
    home = str(Path.home())
    for variant in {home, home.replace("\\", "/")}:
        if variant and variant not in ("/", "\\"):
            text = text.replace(variant, "~")
    return text


def tilde(path: Path) -> str:
    return scrub(str(path))


def header(caps: Capabilities) -> list[str]:
    return [
        f"eyewall {__version__}",
        f"python {platform.python_version()} ({platform.python_implementation()})",
        f"os {platform.system()} {platform.release()} {platform.machine()}",
        f"terminal TERM={caps.term or '-'} COLORTERM={caps.colorterm or '-'} {caps.columns}x{caps.lines}",
        f"capabilities color={caps.color} unicode={caps.unicode} mouse={caps.mouse} encoding={caps.encoding}",
    ]


def write_crash_log(exc: BaseException, caps: Capabilities, *, now: datetime | None = None) -> Path | None:
    """Save the traceback under the user log directory and return the file; None when it cannot be written."""
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    body = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    text = "\n".join([*header(caps), "", scrub(body)])
    try:
        directory = log_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"crash-{stamp}.log"
        path.write_text(text, encoding="utf-8")
        for old in sorted(directory.glob("crash-*.log"))[:-KEEP_LOGS]:
            old.unlink(missing_ok=True)
    except OSError:
        return None
    return path


def crash_message(exc: BaseException, path: Path | None) -> str:
    where = f"details are in {tilde(path)}" if path else "the crash log could not be written"
    return (
        f"eyewall: unexpected error: {type(exc).__name__}: {scrub(str(exc))}\n"
        f"eyewall: {where}\n"
        f"eyewall: please report it, with that file, at {ISSUES_URL}"
    )


def diagnose_lines(caps: Capabilities, config: Config, config_path: Path | None) -> list[str]:
    """The report. Feed reachability is one poll through the same runner `--summary` uses."""
    from eyewall.headless import run_live

    lines = header(caps)
    lines.append(f"config {tilde(config_path) if config_path else '(none: --no-config)'}")
    lines.append(f"data {tilde(default_state_dir())}")
    lines.append(f"crash logs {tilde(log_dir())}")
    try:
        result = asyncio.run(run_live(config, None, None))
        failed = sorted(result.failed_feeds)
        detail = f" ({', '.join(failed)})" if failed else ""
        lines.append(f"feeds {result.feeds_ok} ok, {result.feeds_failed} failed{detail}")
    except Exception as exc:  # the report must still print
        lines.append(f"feeds could not be polled: {type(exc).__name__}: {scrub(str(exc))}")
    return lines
