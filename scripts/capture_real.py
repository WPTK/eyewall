"""Record today's real NOAA payloads into tests/fixtures/real/<date>/ for the corpus test (tests/real_corpus.py).

    python scripts/capture_real.py [--date YYYY-MM-DD] [--station 41010] [--gauge 8721604] [--force]

One request per feed, one at a time, half a second apart, with the eyewall User-Agent from `eyewall.net`. A day that is
already captured is left alone unless --force is given. Every body is written byte for byte, with a `capture.json`
that records the kind, URL, HTTP status, fetch time (UTC), size and SHA-256. A feed that fails is listed under
"failed" with no file, and the script exits 1, so a gap is visible.

This script reaches the network and is never imported or run by the test suite.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # `tests` is a package of the repo, not of the install

from eyewall.coops.client import STATIONS_URL  # noqa: E402
from eyewall.coops.data import DATAGETTER_URL, datagetter_params  # noqa: E402
from eyewall.models.storm import Basin  # noqa: E402
from eyewall.ndbc.client import LATEST_OBS_URL, five_day_url  # noqa: E402
from eyewall.ndbc.client import STATIONS_URL as NDBC_STATIONS  # noqa: E402
from eyewall.net import FetchError, fetch_bytes, new_client  # noqa: E402
from eyewall.providers.nhc import ids  # noqa: E402
from tests.real_corpus import CORPUS, sha256  # noqa: E402

DELAY_SECONDS = 0.5


def feeds(station: str, gauge: str) -> list[tuple[str, str, dict[str, str] | None, str]]:
    """(kind, url, params, file name) for every feed the corpus replays."""
    return [
        ("current_storms", ids.CURRENT_STORMS_URL, None, "CurrentStorms.json"),
        ("outlook_at", ids.outlook_url(Basin.AL), None, "two_at.txt"),
        ("outlook_ep", ids.outlook_url(Basin.EP), None, "two_ep.txt"),
        ("outlook_cp", ids.outlook_url(Basin.CP), None, "two_cp.txt"),
        ("alerts", ids.alerts_url(), ids.alerts_params(), "alerts_active.json"),
        ("ndbc_stations", NDBC_STATIONS, None, "activestations.xml"),
        ("ndbc_latest", LATEST_OBS_URL, None, "latest_obs.txt"),
        ("ndbc_5day", five_day_url(station, "txt"), None, f"{station}_5day.txt"),
        ("ndbc_spec", five_day_url(station, "spec"), None, f"{station}_5day.spec"),
        ("ndbc_supl", five_day_url(station, "supl"), None, f"{station}_5day.supl"),
        ("coops_stations", STATIONS_URL, {"type": "waterlevels"}, "stations_waterlevels.json"),
        (
            "coops_water_level",
            DATAGETTER_URL,
            datagetter_params("water_level", gauge, date="recent"),
            f"water_level_{gauge}.json",
        ),
        ("coops_wind", DATAGETTER_URL, datagetter_params("wind", gauge, date="recent"), f"wind_{gauge}.json"),
        (
            "coops_pressure",
            DATAGETTER_URL,
            datagetter_params("air_pressure", gauge, date="recent"),
            f"air_pressure_{gauge}.json",
        ),
    ]


async def capture(day: Path, station: str, gauge: str) -> int:
    done: list[dict[str, object]] = []
    failed: list[dict[str, object]] = []
    async with new_client() as client:
        for kind, url, params, name in feeds(station, gauge):
            entry: dict[str, object] = {"kind": kind, "url": url, "params": params}
            try:
                fetched = await fetch_bytes(client, url, params=params)
            except FetchError as exc:
                failed.append({**entry, "error": str(exc)})
                print(f"FAIL {kind}: {exc}")
            else:
                (day / kind).mkdir(parents=True, exist_ok=True)
                (day / kind / name).write_bytes(fetched.body)
                done.append(
                    {
                        **entry,
                        "status": 200,
                        "file": f"{kind}/{name}",
                        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
                        "bytes": len(fetched.body),
                        "sha256": sha256(fetched.body),
                    }
                )
                print(f"ok   {kind}: {len(fetched.body)} bytes")
            await asyncio.sleep(DELAY_SECONDS)
    text = json.dumps({"captures": done, "failed": failed}, indent=2)
    (day / "capture.json").write_text(text + "\n", encoding="utf-8")
    return len(failed)


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--date", default=datetime.now(UTC).date().isoformat())
    parser.add_argument("--station", default="41010")
    parser.add_argument("--gauge", default="8721604")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    day = CORPUS / args.date
    if day.exists() and not args.force:
        print(f"{day} exists; use --force to record it again")
        return 0
    day.mkdir(parents=True, exist_ok=True)
    return 1 if asyncio.run(capture(day, args.station, args.gauge)) else 0


if __name__ == "__main__":
    raise SystemExit(main())
