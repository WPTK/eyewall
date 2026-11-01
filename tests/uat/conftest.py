"""Fixtures for the UAT suite: where screenshots go, the terminal sizes, and a journey factory."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path

import pytest

from eyewall.app import EyewallApp
from tests.uat.harness import SIZES, Journey, size_id
from tests.ui_support import into_the_storm, replay_app, running

OUT_ENV = "EYEWALL_UAT_OUT"


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Everything under tests/uat carries the `uat` marker and a longer time limit than the unit tests."""
    for item in items:
        if "tests/uat/" in item.nodeid.replace("\\", "/"):
            item.add_marker(pytest.mark.uat)
            item.add_marker(pytest.mark.timeout(300))


@pytest.fixture(autouse=True)
def _colour(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run with colour, as a terminal normally has it; the no-colour case has a test of its own."""
    monkeypatch.delenv("NO_COLOR", raising=False)


@pytest.fixture(scope="session")
def uat_out(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Screenshots go to $EYEWALL_UAT_OUT when scripts/uat.py sets it, otherwise to a temporary directory."""
    chosen = os.environ.get(OUT_ENV)
    path = Path(chosen) if chosen else tmp_path_factory.mktemp("uat")
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture(params=SIZES, ids=size_id)
def size(request: pytest.FixtureRequest) -> tuple[int, int]:
    return request.param  # type: ignore[no-any-return]


OpenJourney = Callable[..., AbstractAsyncContextManager[Journey]]


@pytest.fixture
def journey(request: pytest.FixtureRequest, caplog: pytest.LogCaptureFixture, uat_out: Path) -> OpenJourney:
    """`async with journey(size=...) as j:` runs the Erin replay (or the app given) at that size, in the storm."""
    scenario = request.node.originalname.removeprefix("test_")  # type: ignore[attr-defined]

    @asynccontextmanager
    async def open_journey(
        size: tuple[int, int] = SIZES[0],
        *,
        app: EyewallApp | None = None,
        storm: bool = True,
        name: str | None = None,
    ) -> AsyncIterator[Journey]:
        app = app if app is not None else replay_app()
        async with running(app, size) as pilot:
            if storm and app.replay is not None:
                await into_the_storm(pilot)
            j = Journey(app, pilot, name or scenario, size, uat_out, caplog)
            yield j
            j.check(footer=False)

    return open_journey
