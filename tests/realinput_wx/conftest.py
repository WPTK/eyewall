"""Real-terminal tests of the published Windows exe, driven by the tui-test kit (``tests/uat_kit_wx``).

Run them with ``pytest tests/realinput_wx -m realinput`` (the default run excludes the marker). They need Windows, the
published v0.9.0 exe (``EYEWALL_EXE`` overrides the default path) and, for the --summary cases, internet access.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import sys
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pytest

from tests.uat_kit_wx.fakenoaa import FakeNoaa, Route
from tests.uat_kit_wx.isolation import guard_real_folders

HERE = Path(__file__).parent
V090_SHA256 = "a0bed6ebd3137badfe3952ef713d48e88fb3d2eca1fd4bc87d5b2b731e7d4220"
DEFAULT_EXE = Path(r"C:\Users\billp\uat-s2b\dl\eyewall-windows-x86_64.exe")
RELEASE_TAG = os.environ.get("EYEWALL_RELEASE", "v0.9.0")
ASSET = "eyewall-windows-x86_64.exe"
RESULTS_PATH = Path(
    os.environ.get("EYEWALL_REAL_RESULTS", Path(tempfile.gettempdir()) / "eyewall-realinput-results.json")
)
UNIT_ONLY = {"test_helpers.py"}  # tests of the harness itself: no exe, no pseudo-console, they run in the default suite


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if Path(str(item.fspath)).parent == HERE and Path(str(item.fspath)).name not in UNIT_ONLY:
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


@pytest.fixture
def artifact(exe: Path) -> Iterator[Path]:
    """The exe under test, copied into a fresh empty directory (so nothing next to it can help)."""
    root = Path(tempfile.mkdtemp(prefix="ew-artifact-"))
    shutil.copy2(exe, root / exe.name)
    COLLECTOR.artifact = {
        "name": exe.name,
        "sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
        "origin": str(exe),
        "size": str(exe.stat().st_size),
    }
    yield root / exe.name
    shutil.rmtree(root, ignore_errors=True)


@dataclass
class Row:
    scenario: str
    item: str
    status: str  # PASS | FAIL | XFAIL | XPASS | SKIP
    evidence: str
    issue: str = ""


@dataclass
class Collector:
    rows: list[Row] = field(default_factory=list)
    artifact: dict[str, str] = field(default_factory=dict)
    notes: dict[str, str] = field(default_factory=dict)


COLLECTOR = Collector()

# Items whose id starts with a key are a known defect, filed as the issue. Such an item is expected to fail: it is
# reported XFAIL and does not fail the test, and when it passes (XPASS) the run fails so the entry gets deleted.
KNOWN: dict[str, str] = {
    "list -> map:": "#151",  # opening a station from the list does not highlight its mark on the map
    "[Station] m:": "#151",
    "recovery:": "#164",  # r does nothing while feeds are in failure back-off
    "59x16: no toast covers": "#175",
    "60x15: no toast covers": "#175",
    "40x10: no toast covers": "#175",
}


def issue_for(item: str) -> str | None:
    return next((issue for prefix, issue in KNOWN.items() if item.startswith(prefix)), None)


class Checks:
    """Soft assertions for a walkthrough: every item is recorded, then the test fails once with all that went wrong.

    A defect that has its own test carries a strict xfail keyed by its issue (``test_defects``); one found inside a
    walkthrough is listed in ``KNOWN`` by item prefix.
    """

    def __init__(self, scenario: str) -> None:
        self.scenario = scenario
        self.failures: list[str] = []

    def __call__(self, item: str, ok: bool, evidence: str = "") -> bool:
        issue = issue_for(item)
        if issue and not ok:
            status = "XFAIL"
        elif issue and ok:
            status = "XPASS"
            self.failures.append(f"{item}: passed but is listed as a known defect ({issue}); delete it from KNOWN")
        elif ok:
            status = "PASS"
        else:
            status = "FAIL"
            self.failures.append(f"{item}: {evidence}")
        COLLECTOR.rows.append(Row(self.scenario, item, status, evidence.replace(chr(10), " | ")[:1200], issue or ""))
        return ok

    def skip(self, item: str, reason: str) -> None:
        COLLECTOR.rows.append(Row(self.scenario, item, "SKIP", reason))

    def done(self, extra: str = "") -> None:
        if self.failures:
            raise AssertionError("\n".join(self.failures[:40]) + (f"\n{extra}" if extra else ""))


@pytest.fixture
def checks(request: pytest.FixtureRequest) -> Checks:
    return Checks(request.node.name)


@pytest.fixture(scope="session")
def note() -> Callable[[str, str], None]:
    def _note(k: str, v: str) -> None:
        COLLECTOR.notes[k] = v

    return _note


def pytest_sessionfinish(session: pytest.Session) -> None:
    if COLLECTOR.rows:
        RESULTS_PATH.write_text(
            json.dumps(
                {"artifact": COLLECTOR.artifact, "notes": COLLECTOR.notes, "rows": [asdict(r) for r in COLLECTOR.rows]},
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    if not COLLECTOR.rows:
        return
    tr = terminalreporter
    tr.section("real-input results")
    counts: dict[str, int] = {}
    for r in COLLECTOR.rows:
        counts[r.status] = counts.get(r.status, 0) + 1
    tr.write_line(f"artifact: {COLLECTOR.artifact}")
    tr.write_line(f"items: {len(COLLECTOR.rows)}  " + "  ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    for r in COLLECTOR.rows:
        if r.status != "PASS":
            tr.write_line(
                f"  {r.status:5} {r.scenario}:{r.item} {r.evidence[:110]}".encode("ascii", "replace").decode()
            )
    tr.write_line(f"full table: {RESULTS_PATH}")
