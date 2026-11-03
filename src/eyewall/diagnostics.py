"""Crash log and `--diagnose`: what to attach to a bug report, without secrets or more of the home path than needed."""

from __future__ import annotations

import asyncio
import contextlib
import getpass
import os
import platform
import re
import traceback
from datetime import datetime
from pathlib import Path

from platformdirs import user_log_dir

from eyewall import __version__
from eyewall.config import Config, LoadResult
from eyewall.headless import HeadlessResult
from eyewall.state.alerts import default_state_dir
from eyewall.terminal import Capabilities

ISSUES_URL = "https://github.com/WPTK/eyewall/issues"
KEEP_LOGS = 10
FEED_TIMEOUT = 30.0  # seconds for the one feed poll of --diagnose


def log_dir() -> Path:
    return Path(user_log_dir("eyewall", appauthor=False))


def scrub(text: str) -> str:
    """Replace the home directory (any case on Windows, either slash) with `~` and the user name with `<user>`."""
    flags = re.IGNORECASE if os.name == "nt" else 0
    homes = {str(Path.home()), os.path.expanduser("~")}
    homes |= {h.replace("\\", "/") for h in homes}
    for home in sorted(homes, key=len, reverse=True):
        if home and home not in ("/", "\\", "~"):
            text = re.sub(re.escape(home), "~", text, flags=flags)
    with contextlib.suppress(Exception):
        user = getpass.getuser()
        if len(user) >= 3:
            text = re.sub(rf"(?<!\w){re.escape(user)}(?!\w)", "<user>", text, flags=flags)
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
    directory = log_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"crash-{stamp}.log"
        path.write_text(text, encoding="utf-8")
    except OSError:
        return None
    with contextlib.suppress(OSError):  # a log that will not prune is still a written log
        for old in sorted(directory.glob("crash-*.log"))[:-KEEP_LOGS]:
            old.unlink(missing_ok=True)
    return path


def crash_message(exc: BaseException, path: Path | None) -> str:
    where = f"details are in {tilde(path)}" if path else "the crash log could not be written"
    return (
        f"eyewall: unexpected error: {type(exc).__name__}: {scrub(str(exc))}\n"
        f"eyewall: {where}\n"
        f"eyewall: please report it, with that file, at {ISSUES_URL}"
    )


def diagnose_lines(
    caps: Capabilities, config: Config, config_path: Path | None, loaded: LoadResult, state_dir: Path | None = None
) -> list[str]:
    """The report. Feed reachability is one poll through the same runner `--summary` uses."""
    from eyewall.headless import run_live

    lines = header(caps)
    lines.append(f"config {tilde(config_path) if config_path else '(none: --no-config)'}")
    if loaded.broken:
        lines.append("config file could not be read; the defaults are in use")
    lines.extend(f"config warning: {scrub(w)}" for w in loaded.warnings)
    lines.append(f"data {tilde(state_dir or default_state_dir())}")
    lines.append(f"crash logs {tilde(log_dir())}")

    async def poll() -> HeadlessResult:
        return await asyncio.wait_for(run_live(config, state_dir, None), FEED_TIMEOUT)

    try:
        result = asyncio.run(poll())
        failed = sorted(result.failed_feeds)
        detail = f" ({', '.join(failed)})" if failed else ""
        lines.append(f"feeds {result.feeds_ok} ok, {result.feeds_failed} failed{detail}")
    except TimeoutError:
        lines.append(f"feeds did not answer within {FEED_TIMEOUT:g} s")
    except Exception as exc:  # the report must still print
        lines.append(f"feeds could not be polled: {type(exc).__name__}: {scrub(str(exc))}")
    return lines
