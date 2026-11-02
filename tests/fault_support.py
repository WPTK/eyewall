"""A fault-injecting NOAA stand-in for the real `LiveSource`, below the HTTP client.

`Wire` is an httpx transport: it answers every request from the saved payloads under `tests/fixtures` (a healthy day),
except for the hosts it was told to break. A broken host times out, answers 500, answers 200 with half a JSON document,
or answers 200 with nothing. Everything above it is the real code: the cache, the retry loop, the clients, the parsers,
the poller and the screens. It is the in-process counterpart of the exe-level proxy in `tests/uat_kit_wx/fakenoaa.py`
(which serves the same payloads to the built exe) and shares its host list.

`wire_app` builds the app over it; `OnWallClock` makes the saved payloads look current. Nothing here touches the
network, the wall clock's date or the user's folders.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from eyewall.app import EyewallApp
from eyewall.clock import SystemClock
from eyewall.config import Config
from eyewall.net import fetch_bytes
from eyewall.sources.live import LiveSource
from tests.nhc_fixtures import gis_bytes, nhc_bytes
from tests.ui_support import EDT, QUIET_NOW

FIXTURES = Path(__file__).parent / "fixtures"
NHC = "www.nhc.noaa.gov"
FTP = "ftp.nhc.noaa.gov"
TGFTP = "tgftp.nws.noaa.gov"
API = "api.weather.gov"
NDBC = "www.ndbc.noaa.gov"
COOPS = "api.tidesandcurrents.noaa.gov"
STAR = "cdn.star.nesdis.noaa.gov"
HOSTS = (NHC, FTP, TGFTP, API, NDBC, COOPS, STAR)

MODES = ("timeout", "http-500", "bad-json", "empty")
STORM_NOW = datetime(2026, 9, 29, 22, tzinfo=UTC)  # when the saved advisory of the storm world was current
STORM_ID = "al062026"


class OnWallClock(SystemClock):
    """The system's monotonic clock and a calendar that starts at `start` and runs with it, so a saved payload is
    current for as long as a test lasts."""

    def __init__(self, start: datetime) -> None:
        self._start = start
        self._t0 = time.monotonic()

    def now(self) -> datetime:
        return self._start + timedelta(seconds=time.monotonic() - self._t0)


def one_storm() -> bytes:
    data = json.loads(nhc_bytes("current/populated.json"))
    data["activeStorms"] = [s for s in data["activeStorms"] if s["id"] == STORM_ID]
    return json.dumps(data).encode()


class Wire(httpx.AsyncBaseTransport):
    """`faults` maps a host to a mode in `MODES`; `delay` is the seconds every answer from a host is held back (one
    number for all hosts, or a dict by host). `storm` puts the Fay advisory in the storm list instead of nothing."""

    def __init__(
        self, faults: dict[str, str] | None = None, *, delay: float | dict[str, float] = 0.0, storm: bool = False
    ) -> None:
        self.faults = dict(faults or {})
        self.delay = delay
        self.storm = storm
        self.requests: list[tuple[str, str]] = []

    def count(self, host: str) -> int:
        return sum(1 for h, _ in self.requests if h == host)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        self.requests.append((host, path))
        wait = self.delay.get(host, 0.0) if isinstance(self.delay, dict) else self.delay
        if wait:
            await asyncio.sleep(wait)
        mode = self.faults.get(host, "ok")
        if mode == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        if mode == "http-500":
            return httpx.Response(500, request=request)
        if mode == "bad-json":
            return httpx.Response(
                200,
                content=b'{"activeStorms": [{"id": "al06',
                headers={"Content-Type": "application/json"},
                request=request,
            )
        if mode == "empty":
            return httpx.Response(200, content=b"", request=request)
        return self.healthy(request, host, path)

    # -- a healthy day -------------------------------------------------------------------------------------------
    def healthy(self, request: httpx.Request, host: str, path: str) -> httpx.Response:
        def ok(body: bytes) -> httpx.Response:
            return httpx.Response(200, content=body, request=request)

        def missing() -> httpx.Response:
            return httpx.Response(404, request=request)

        if host == NHC:
            if path == "/CurrentStorms.json":
                return ok(one_storm() if self.storm else nhc_bytes("current/empty.json"))
            if path.endswith("gtwo_shapefiles.zip"):
                return ok(gis_bytes("gtwo_20261031.zip"))
            if path.endswith(".shtml"):
                return ok(nhc_bytes("graphics/landing_at1_quiet.html"))
            if "_fcst_" in path:
                return ok(gis_bytes("erin_fcst_030.zip"))
            if "_5day_" in path:
                return ok(gis_bytes("erin_5day_030.zip"))
            return missing()
        if host == FTP:
            return ok(nhc_bytes("atcf/bep222026.dat")) if path.endswith(".dat") else missing()
        if host == TGFTP:
            for basin, name in (("at", "abnt20.knhc"), ("ep", "abpz20.knhc"), ("cp", "acpn50.phfo")):
                if name in path:
                    return ok(nhc_bytes(f"two/{basin}_20261031.txt"))
            for kind in ("tcm", "tcp", "tcd", "pws"):
                if path.endswith(f".{kind}.at1.txt"):
                    return ok(nhc_bytes(f"{kind}/fay_039.txt"))
            return missing()
        if host == API:
            return ok(nhc_bytes("api/alerts_active_none.json")) if path == "/alerts/active" else missing()
        if host == NDBC:
            ndbc = FIXTURES / "ndbc"
            if path.endswith("activestations.xml"):
                return ok((ndbc / "activestations.xml").read_bytes())
            if path.endswith("latest_obs.txt"):
                return ok((ndbc / "latest_obs.txt").read_bytes())
            for suffix in ("spec", "supl", "txt"):
                if path.endswith(f"_5day.{suffix}"):
                    return ok((ndbc / f"41010_5day.{suffix}").read_bytes())
            return missing()
        if host == COOPS:
            coops = FIXTURES / "coops"
            if "webapi/stations" in path:
                return ok((coops / "stations_waterlevels.json").read_bytes())
            if path.endswith("datagetter"):
                return ok((coops / "water_level_recent.json").read_bytes())
            return missing()
        if host == STAR:
            return ok(nhc_bytes("graphics/floater_root.html"))
        return missing()


def quick_retries(monkeypatch: object) -> None:
    """Retries without the waiting: the retry loop's back-off (1 s, then 2 s) is real time under a real client."""
    kw = fetch_bytes.__kwdefaults__
    assert kw is not None
    monkeypatch.setitem(kw, "backoff", 0.0)  # type: ignore[attr-defined]


@asynccontextmanager
async def wire_app(
    wire: Wire, cache_dir: Path, size: tuple[int, int] = (120, 30), *, storm: bool = False
) -> AsyncIterator[tuple[EyewallApp, object]]:
    """The real app over the real `LiveSource` over `wire`. Yields (app, pilot) as soon as the app has started; the
    first poll is under way, not finished, so a test sees the cold start."""
    start = STORM_NOW if storm else QUIET_NOW
    source = LiveSource(cache_dir=cache_dir, transport=wire, clock=OnWallClock(start))
    source.nhc._sleep = _no_wait
    app = EyewallApp(Config(), source, local_tz=EDT, closer=source.aclose)
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        yield app, pilot


async def _no_wait(_: float) -> None:
    return None
