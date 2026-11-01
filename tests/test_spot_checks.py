"""The spot-check scripts split feed outages (DOWN, exit 2) from format drift (FAIL, exit 1)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest

from eyewall.net import FetchError, NetworkError

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


obs = _load("spot_check_obs")
nhc = _load("spot_check_nhc")


async def _hooked_get(report: Any, content: bytes) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=content))
    async with httpx.AsyncClient(transport=transport, event_hooks={"response": [report.watch]}) as client:
        await client.get("https://example.test/feed")


async def test_obs_nonempty_body_that_parses_to_nothing_is_a_format_failure() -> None:
    report = obs.Report()
    await _hooked_get(report, b"renamed,columns\n1,2\n")
    report.check(False, "feed", "0 rows")
    assert (report.failures, report.outages) == (1, 0)


async def test_obs_zero_byte_body_is_an_outage() -> None:
    report = obs.Report()
    await _hooked_get(report, b"")
    report.check(False, "feed", "0 rows")
    assert (report.failures, report.outages) == (0, 1)


async def test_obs_empty_flag_does_not_leak_into_the_next_check() -> None:
    report = obs.Report()
    await _hooked_get(report, b"")
    report.check(True, "first", "ok")
    await _hooked_get(report, b"data")
    report.check(False, "second", "0 rows")
    assert (report.failures, report.outages) == (1, 0)


async def test_obs_fetch_error_is_an_outage_and_later_fetches_still_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(obs, "PAUSE_SECONDS", 0)
    report = obs.Report()

    async def down() -> str:
        raise NetworkError("https://example.test/a", "timed out")

    async def fine() -> str:
        return "value"

    assert await report.fetch("a", down) is None
    assert await report.fetch("b", fine) == "value"
    assert (report.failures, report.outages) == (0, 1)


async def test_nhc_report_run_splits_outage_from_failure() -> None:
    report = nhc.Report()

    async def down() -> str:
        raise FetchError("https://example.test/a", "503")

    async def empty() -> str:
        raise nhc.Empty("empty outlook")

    async def drift() -> str:
        raise AssertionError("no storm directories listed")

    async def fine() -> str:
        return "fine"

    for work in (down, empty, drift, fine):
        await report.run(work.__name__, work, 0)
    assert (report.failures, report.outages, report.checks) == (1, 2, 4)


async def test_nhc_one_failed_advisory_fetch_does_not_stop_the_other_storms() -> None:
    report = nhc.Report()
    seen: list[str] = []

    class Client:
        async def advisory(self, storm: Any) -> Any:
            seen.append(storm.id)
            raise FetchError("https://example.test/adv", "503")

    class Storm:
        def __init__(self, id_: str) -> None:
            self.id = id_
            self.name = id_

    class Current:
        storms = (Storm("al01"), Storm("al02"))

    await nhc.check_active_storms(Client(), report, 0, Current())  # type: ignore[arg-type]
    assert seen == ["al01", "al02"]
    assert (report.failures, report.outages) == (0, 2)


@pytest.mark.parametrize(("body", "failures", "outages"), [(b"", 0, 1), (b"<stations><oops/></stations>", 1, 0)])
async def test_obs_hook_works_through_the_real_ndbc_client(body: bytes, failures: int, outages: int) -> None:
    from eyewall.ndbc.client import NdbcClient

    report = obs.Report()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=body))
    async with httpx.AsyncClient(transport=transport, event_hooks={"response": [report.watch]}) as client:
        response = await NdbcClient(client).stations()
    catalog = response.value
    report.check(len(catalog.items if catalog else ()) > 500, "activestations.xml", "none")
    assert (report.failures, report.outages) == (failures, outages)
