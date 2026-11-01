"""Input inventory, group 'keys': every item the group's checks exercise passes, or is a strict xfail with an issue."""

from __future__ import annotations

import pytest

from tests.uat.inventory.group import assert_group, assert_known, known_params

pytestmark = pytest.mark.uat


async def test_keys_all_items_work() -> None:
    await assert_group("keys")


@pytest.mark.parametrize("item", known_params("keys"))
async def test_keys_known_defect(item: str) -> None:
    await assert_known("keys", item)
