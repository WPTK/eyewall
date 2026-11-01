"""Shared pytest setup."""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator

import psutil
import pytest

# Test runs are bounded so a runaway test fails instead of exhausting the machine. Time: pytest-timeout, set in
# pyproject.toml. Memory: resource.setrlimit does not exist on Windows, so each test process (the main one and every
# xdist worker) runs a thread that watches its own RSS and kills the process over the limit; under xdist the dead worker
# is reported as a crash and the run fails. EYEWALL_TEST_RSS_MB overrides the limit, and 0 turns the watch off.
RSS_LIMIT_MB = 2048
WATCH_INTERVAL_SECONDS = 0.25


@pytest.fixture(scope="session", autouse=True)
def _memory_limit() -> Iterator[None]:
    limit = int(os.environ.get("EYEWALL_TEST_RSS_MB", RSS_LIMIT_MB)) * 1024 * 1024
    if limit <= 0:
        yield
        return
    process = psutil.Process()
    stop = threading.Event()

    def watch() -> None:
        while not stop.wait(WATCH_INTERVAL_SECONDS):
            rss = process.memory_info().rss
            if rss > limit:
                message = (
                    f"\nFATAL: test process {process.pid} is using {rss >> 20} MB, over the {limit >> 20} MB limit\n"
                )
                os.write(2, message.encode())
                os._exit(70)

    thread = threading.Thread(target=watch, name="rss-watch", daemon=True)
    thread.start()
    yield
    stop.set()
    thread.join(timeout=1)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Tests marked live hit the real NOAA servers, so they only run when asked for."""
    if os.environ.get("EYEWALL_LIVE") == "1":
        return
    skip = pytest.mark.skip(reason="live test; set EYEWALL_LIVE=1 to run")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
