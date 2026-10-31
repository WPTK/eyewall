"""Shared pytest setup."""

from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Tests marked live hit the real NOAA servers, so they only run when asked for."""
    if os.environ.get("EYEWALL_LIVE") == "1":
        return
    skip = pytest.mark.skip(reason="live test; set EYEWALL_LIVE=1 to run")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
