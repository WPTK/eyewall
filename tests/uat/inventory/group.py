"""Shared test bodies for the check groups (see runner.py)."""

from __future__ import annotations

import pytest

from tests.uat.inventory.known import KNOWN_ITEMS
from tests.uat.inventory.runner import run_group


async def assert_group(group: str) -> None:
    results = await run_group(group)
    unexpected = {i: m for i, m in sorted(results.items()) if m and i not in KNOWN_ITEMS}
    assert not unexpected, "\n" + "\n".join(f"  {i}: {m}" for i, m in unexpected.items())


def known_params(group: str):  # type: ignore[no-untyped-def]
    from tests.uat.inventory.runner import GROUPS, registry

    owned = {c.split("@")[0] for c in registry.CHECKS} & set(GROUPS[group])
    del owned
    return [pytest.param(i, marks=pytest.mark.xfail(strict=True, reason=n)) for i, n in sorted(KNOWN_ITEMS.items())]


async def assert_known(group: str, item: str) -> None:
    results = await run_group(group)
    if item not in results:
        pytest.skip(f"{item} belongs to another group")
    assert results[item] is None, results[item]
