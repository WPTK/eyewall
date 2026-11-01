"""The input-inventory pattern (app-agnostic: the shared template for eyewall, wxbrief and earthwave).

The idea: an application's inputs are an enumerable set (every key binding, every clickable region, every menu entry,
every documented claim). Three pieces keep that set honest:

1. An INVENTORY, collected programmatically from the code (binding tables) and from the running screens (footer cells,
   links, tabs, rows). Item ids are plain strings such as `key:storm:left` or `click:footer:main:key:b`.
2. CHECKS: async functions that drive a launched `World` (an app state at a terminal size) and report, per inventory
   item, whether pressing/clicking it produced an observable change: `rec(item)` for a pass, `rec(item, "why")` for
   a failure. A check never asserts mid-way, so one dead key does not hide the rest.
3. A META-TEST: the inventory minus the items some check exercised must be empty, and it prints the uncovered list and
   a count summary. A new key or button with no test fails the build.

Each item is then one pytest test (`test_item[<id>]`), and a known defect is a strict xfail keyed by the item id with
the issue number as the reason, so fixing the app turns the xfail into a failure that says "remove the marker".

To reuse: copy this module, write `inventory.py` (how to enumerate YOUR keys and clickables), `worlds.py` (how to
launch YOUR app in each state) and the checks. Nothing here imports the application.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class World:
    """The environment a check runs in: an app state and a terminal size. Hashable, used as the launch key."""

    state: str
    size: tuple[int, int]

    @property
    def id(self) -> str:
        return f"{self.state}-{self.size[0]}x{self.size[1]}"


Rec = Callable[..., None]
CheckFn = Callable[[Any, Rec], Awaitable[None]]
CHECKS: dict[str, tuple[World, CheckFn]] = {}
RESULTS: dict[str, str | None] = {}  # item id -> failure text, or None when it passed


def check(world: World) -> Callable[[CheckFn], CheckFn]:
    """Register a check that runs in this world. It reports through `rec(item, failure=None)`."""

    def deco(fn: CheckFn) -> CheckFn:
        CHECKS[f"{fn.__name__}@{world.id}"] = (world, fn)
        return fn

    return deco


def worlds() -> list[World]:
    return sorted({w for w, _ in CHECKS.values()}, key=lambda w: w.id)


def exercised() -> set[str]:
    return set(RESULTS)


def uncovered(inventory: set[str]) -> list[str]:
    return sorted(inventory - exercised())


def orphans(inventory: set[str]) -> list[str]:
    """Items a check reported that the inventory does not contain (a renamed key leaves these behind)."""
    return sorted(exercised() - inventory)


def summary(inventory: set[str]) -> str:
    """`key 176/176, click 60/60, palette 20/20, claim 40/40` for a PR description."""
    kinds = Counter(i.split(":", 1)[0] for i in inventory)
    done = Counter(i.split(":", 1)[0] for i in inventory & exercised())
    return ", ".join(f"{kind} {done[kind]}/{total}" for kind, total in sorted(kinds.items()))
