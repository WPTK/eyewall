"""Fixtures for the real-input suite: the built exe in an empty directory, and the results table."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pytest

from . import known

HERE = Path(__file__).parent
RELEASE_TAG = os.environ.get("EYEWALL_RELEASE", "v0.9.0")
ASSET = "eyewall-windows-x86_64.exe"
RESULTS_PATH = Path(
    os.environ.get("EYEWALL_REAL_RESULTS", Path(tempfile.gettempdir()) / "eyewall-realinput-results.json")
)
UNIT_ONLY = {"test_helpers.py"}  # CI-safe tests of the harness itself; everything else needs the exe


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


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if Path(str(item.fspath)).parent == HERE and Path(str(item.fspath)).name not in UNIT_ONLY:
            item.add_marker(pytest.mark.realinput)
            if sys.platform != "win32":
                item.add_marker(pytest.mark.skip(reason="the real-input suite drives the Windows exe"))


@pytest.fixture(scope="session")
def artifact() -> Iterator[Path]:
    """The exe under test, copied into a fresh empty directory (so nothing next to it can help)."""
    root = Path(tempfile.mkdtemp(prefix="ew-artifact-"))
    src = os.environ.get("EYEWALL_EXE")
    if src:
        origin = f"EYEWALL_EXE={src}"
        if not Path(src).is_file():
            pytest.fail(f"EYEWALL_EXE points at {src}, which is not a file")
        shutil.copy2(src, root / Path(src).name)
        exe = root / Path(src).name
    else:
        origin = f"gh release download {RELEASE_TAG} -p {ASSET}"
        subprocess.run(
            ["gh", "release", "download", RELEASE_TAG, "-R", "WPTK/eyewall", "-p", ASSET, "-D", str(root)],
            check=True,
            capture_output=True,
        )
        exe = root / ASSET
    sha = hashlib.sha256(exe.read_bytes()).hexdigest()
    COLLECTOR.artifact = {"name": exe.name, "sha256": sha, "origin": origin, "size": str(exe.stat().st_size)}
    yield exe
    shutil.rmtree(root, ignore_errors=True)


class Checks:
    """Soft assertions for a walkthrough: every item is recorded, then the test fails once with all that went wrong."""

    def __init__(self, scenario: str) -> None:
        self.scenario = scenario
        self.failures: list[str] = []

    def __call__(self, item: str, ok: bool, evidence: str = "") -> bool:
        issue = known.issue_for(f"{self.scenario}:{item}") or known.issue_for(item)
        if issue and not ok:
            status = "XFAIL"
        elif issue and ok:
            status = "XPASS"
            self.failures.append(f"{item}: passed but is listed as a known defect ({issue}); delete it from known.py")
        elif ok:
            status = "PASS"
        else:
            status = "FAIL"
            self.failures.append(f"{item}: {evidence}")
        COLLECTOR.rows.append(Row(self.scenario, item, status, evidence.replace("\n", " | ")[:400], issue or ""))
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
                f"  {r.status:5} {r.scenario}:{r.item} {r.issue} {r.evidence[:110]}".encode("ascii", "replace").decode()
            )
    tr.write_line(f"full table: {RESULTS_PATH}")
