"""Run the live data source against the real services once, then cut the network and check the feeds go stale.

    python scripts/spot_check_live.py

It reads NOAA, so it is a smoke check, not a test: run it before a release. Exit status is 1 when a feed fails or the
offline behavior is wrong. Quiet days are fine; the storm-specific calls run only when a storm is active.

1. With a temporary cache and the network up: storms (and, for the first storm, its text products and GIS), the
   outlook, the alerts, the NDBC catalog and latest observations, and the CO-OPS catalog. None may be stale.
2. The network is switched off underneath the same source: the feeds fetched in step 1 must answer from the cache and
   report `stale`, and an endpoint never fetched must raise a FetchError rather than return nothing.
3. One pass of the poller over the live source, to show the whole pipeline runs.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

import httpx

from eyewall.config import Config
from eyewall.net import FetchError
from eyewall.poll import Poller
from eyewall.sources import protocol
from eyewall.sources.live import LiveSource
from eyewall.state.alerts import AlertEngine
from eyewall.state.store import Store

failures: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'} {label}" + (f"  {detail}" if detail else ""))
    if not ok:
        failures.append(label)


class Switch(httpx.AsyncBaseTransport):
    """The real network, until `down` is set."""

    def __init__(self) -> None:
        self.down = False
        self._real = httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("network switched off by the spot check", request=request)
        return await self._real.handle_async_request(request)

    async def aclose(self) -> None:
        await self._real.aclose()


async def main() -> int:
    switch = Switch()
    with tempfile.TemporaryDirectory() as folder:
        source = LiveSource(cache_dir=Path(folder), transport=switch)
        try:
            storms = await source.storms()
            check(not source.stale(protocol.STORMS), "storms", f"{len(storms.storms)} active")
            for storm in storms.storms[:1]:
                advisories = await source.advisory(storm)
                check(advisories.adv_num is not None, f"advisory {storm.id}", str(advisories.adv_num))
                gis = await source.forecast_gis(storm)
                check(gis is not None, f"forecast gis {storm.id}")
            outlook = await source.outlook()
            check(bool(outlook.texts), "outlook", f"{len(outlook.texts)} basin texts, {len(outlook.invests)} invests")
            alerts = await source.alerts()
            check(not source.stale(protocol.ALERTS), "alerts", f"{len(alerts.alerts)} tropical alerts")
            stations = await source.ndbc_stations()
            latest = await source.ndbc_latest()
            check(len(stations) > 500 and len(latest) > 100, "ndbc", f"{len(stations)} stations, {len(latest)} latest")
            tides = await source.coops_stations()
            check(len(tides) > 100, "coops", f"{len(tides)} gauges")

            print("-- network off --")
            switch.down = True
            await source.storms()
            check(source.stale(protocol.STORMS), "storms answered from the cache and marked stale")
            await source.ndbc_latest()
            check(source.stale(protocol.BUOYS), "buoys answered from the cache and marked stale")
            try:
                await source.ndbc_series("41047")
                check(False, "an endpoint never fetched raises while offline")
            except FetchError:
                check(True, "an endpoint never fetched raises while offline")

            print("-- network on, one poller pass --")
            switch.down = False
            poller = Poller(source, Store(Config()), AlertEngine(), Config().poll)
            results = await poller.tick()
            for result in results:
                check(result.ok, f"poll {result.feed}", result.freshness.state.value)
        finally:
            await source.aclose()
    print("FAILED: " + ", ".join(failures) if failures else "all checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
