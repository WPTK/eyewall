"""Runs the registered checks, one app launch per check, and shares the results between test files.

Test files are spread over xdist workers (use `--dist loadfile`), so each group writes its results to a JSON file named
by the xdist run id; the completeness test reads whatever groups finished and runs the missing ones itself."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path

from tests.uat.inventory import checks_clicks, checks_keys, checks_misc, registry  # noqa: F401  (registers the checks)
from tests.uat.inventory.inventory import DYNAMIC
from tests.uat.inventory.worlds import launch

GROUPS: dict[str, tuple[str, ...]] = {
    "keys": ("keys_demo", "replay_from_quiet"),
    "clicks": ("clicks_demo", "clicks_small", "map_marks", "clicks_quiet"),
    "misc": ("palette_demo", "linkage"),
}


def _run_id() -> str:
    return os.environ.get("PYTEST_XDIST_TESTRUNUID") or f"pid{os.getppid()}"


def _file(group: str) -> Path:
    return Path(tempfile.gettempdir()) / f"eyewall-uat-{_run_id()}-{group}.json"


def save_dynamic(source: str) -> None:
    """Remember the dynamic inventory items this process has seen, for the completeness test (maybe another worker)."""
    path = Path(tempfile.gettempdir()) / f"eyewall-uat-{_run_id()}-dyn-{source}.json"
    path.write_text(json.dumps(sorted(DYNAMIC)), encoding="utf-8")


def saved_dynamic() -> set[str]:
    out: set[str] = set()
    for path in Path(tempfile.gettempdir()).glob(f"eyewall-uat-{_run_id()}-dyn-*.json"):
        out |= set(json.loads(path.read_text(encoding="utf-8")))
    return out | set(DYNAMIC)


WAIT_SECONDS = 400
_MEMORY: dict[str, dict[str, str | None]] = {}


async def run_group(group: str) -> dict[str, str | None]:
    """item id -> failure text or None, for every check in the group."""
    if group in _MEMORY:
        return _MEMORY[group]
    results: dict[str, str | None] = {}

    def rec(item: str, failure: str | None = None) -> None:
        if failure is None and results.get(item):
            return  # a failure on one screen is not erased by a pass on another
        results[item] = failure
        registry.RESULTS[item] = failure

    for key, (world, fn) in registry.CHECKS.items():
        if key.split("@")[0] not in GROUPS[group]:
            continue
        async with launch(world) as w:
            try:
                await fn(w, rec)
            except Exception as exc:
                rec(f"crash:{key}", f"{type(exc).__name__}: {exc}")
    _MEMORY[group] = results
    save_dynamic(group)
    _file(group).write_text(json.dumps(results), encoding="utf-8")
    return results


async def all_results() -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for group in GROUPS:
        path = _file(group)
        if group in _MEMORY:
            out |= _MEMORY[group]
        elif path.exists():
            out |= json.loads(path.read_text(encoding="utf-8"))
        else:
            for _ in range(WAIT_SECONDS * 2):  # another worker is probably running it: wait, do not repeat the work
                if path.exists():
                    break
                await asyncio.sleep(0.5)
            out |= json.loads(path.read_text(encoding='utf-8')) if path.exists() else await run_group(group)
    registry.RESULTS.update(out)
    return out
