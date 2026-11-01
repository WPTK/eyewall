"""Input inventory, group 'clicks': every item the group's checks exercise passes, or is a strict xfail with an issue."""

from __future__ import annotations

import pytest

from tests.uat.inventory.group import assert_group, assert_known, known_params

pytestmark = pytest.mark.uat


async def test_clicks_all_items_work() -> None:
    await assert_group("clicks")


@pytest.mark.parametrize("item", known_params("clicks"))
async def test_clicks_known_defect(item: str) -> None:
    await assert_known("clicks", item)
