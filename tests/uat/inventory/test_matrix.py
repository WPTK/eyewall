"""The state matrix: states x screens x sizes against the rules in rules.py. One test per launched cell."""

from __future__ import annotations

import pytest

from tests.uat.inventory.known import KNOWN_MATRIX
from tests.uat.inventory.matrix import CELLS, WORLDS, results_for

pytestmark = pytest.mark.uat


def test_matrix_size() -> None:
    """The matrix is the size the PR says it is."""
    assert len(WORLDS) == 9 + 4 + 2
    assert len({(s, n, z) for s, n, z in CELLS}) == len(CELLS)


@pytest.mark.parametrize("world", WORLDS, ids=lambda w: w.id)
async def test_matrix_rules(world) -> None:  # type: ignore[no-untyped-def]
    """No rule is broken on any screen of this state at this size, except the known defects."""
    results = await results_for(world)
    unexpected = []
    for screen, found in results.items():
        if isinstance(found, str):
            continue
        for rule, message in found:
            if (rule, world.state, screen) not in KNOWN_MATRIX:
                unexpected.append(f"  [{rule}] {world.state}/{screen}/{world.size[0]}x{world.size[1]}: {message}")
    assert not unexpected, "\n" + "\n".join(unexpected)


@pytest.mark.parametrize(
    "triple",
    [pytest.param(t, marks=pytest.mark.xfail(strict=True, reason=n)) for t, n in sorted(KNOWN_MATRIX.items())],
    ids=lambda t: "/".join(t),
)
async def test_matrix_known_defect(triple) -> None:  # type: ignore[no-untyped-def]
    rule, state, screen = triple
    hits = []
    for world in WORLDS:
        if world.state != state:
            continue
        found = (await results_for(world)).get(screen, [])
        if not isinstance(found, str):
            hits += [m for r, m in found if r == rule]
    assert not hits, hits[0]
