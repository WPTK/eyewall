"""Real-terminal tests of the published Windows exe, driven by the tui-test kit (``tests/uat_kit_wx``).

Run them with ``pytest tests/realinput_wx -m realinput`` (the default run excludes the marker). They need Windows, the
published v0.9.0 exe (``EYEWALL_EXE`` overrides the default path) and, for the --summary cases, internet access.
"""

from __future__ import annotations

import hashlib
import os
import socket
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from tests.uat_kit_wx.fakenoaa import FakeNoaa, Route
from tests.uat_kit_wx.isolation import guard_real_folders

HERE = Path(__file__).parent
V090_SHA256 = "a0bed6ebd3137badfe3952ef713d48e88fb3d2eca1fd4bc87d5b2b731e7d4220"
DEFAULT_EXE = Path(r"C:\Users\billp\uat-s2b\dl\eyewall-windows-x86_64.exe")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if Path(str(item.fspath)).parent == HERE:
            item.add_marker(pytest.mark.realinput)
            if sys.platform != "win32":
                item.add_marker(pytest.mark.skip(reason="drives the published Windows exe through a ConPTY"))


# A session fixture: the session errors at the end if the real user folders were touched by any test.
real_folders_untouched = pytest.fixture(scope="session", autouse=True)(guard_real_folders)


@pytest.fixture(scope="session")
def exe() -> Path:
    """The exe under test. The default path is pinned to the v0.9.0 hash; ``EYEWALL_EXE`` is trusted as given."""
    given = os.environ.get("EYEWALL_EXE")
    path = Path(given) if given else DEFAULT_EXE
    if not path.is_file():
        pytest.skip(f"the exe under test is not present: {path} (set EYEWALL_EXE)")
    if not given:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != V090_SHA256:
            pytest.fail(f"{path} is not the v0.9.0 exe: sha256 {digest}, expected {V090_SHA256}")
    return path


@pytest.fixture
def fake_noaa(tmp_path: Path) -> Iterator[Callable[..., FakeNoaa]]:
    """Factory for the fake NOAA proxy; every proxy made is closed at the end of the test."""
    made: list[FakeNoaa] = []

    def make(*, modes: dict[str, str] | None = None, default: str = "real", routes: Route | None = None) -> FakeNoaa:
        fake = FakeNoaa(tmp_path / f"fake{len(made)}", modes=modes, default=default, routes=routes)
        made.append(fake)
        return fake

    yield make
    for fake in made:
        fake.close()


@pytest.fixture(scope="session")
def internet() -> None:
    """Skip a test that needs the real NOAA hosts (the cases that refuse one host and let the rest through)."""
    try:
        socket.create_connection(("www.ndbc.noaa.gov", 443), timeout=5).close()
    except OSError as exc:
        pytest.skip(f"no route to the real NOAA hosts: {exc}")
