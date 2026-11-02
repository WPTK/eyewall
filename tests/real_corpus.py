"""The real-payload corpus: dated captures of what NOAA actually served, replayed through the parsers.

Layout, written by `scripts/capture_real.py` and never edited by hand (`tests/fixtures/**` is `-text`):

    tests/fixtures/real/2026-11-01/capture.json         what was fetched: kind, url, status, fetched_at, sha256, bytes
    tests/fixtures/real/2026-11-01/<kind>/<file>        the body, byte for byte

`KINDS` maps a kind to the parser that must accept it. A body that fails to parse, or a capture whose bytes no longer
match their hash, fails a test; so does a kind with no parser, so a new feed cannot be captured and then never
replayed. The loader is the only code the capture script and the tests share.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eyewall.coops.data import parse_air_pressure, parse_water_level, parse_wind
from eyewall.coops.stations import parse_tide_stations
from eyewall.ndbc.latest import parse_latest_obs
from eyewall.ndbc.spec import parse_spec
from eyewall.ndbc.stations import parse_stations
from eyewall.ndbc.stdmet import parse_stdmet
from eyewall.ndbc.supl import parse_supl
from eyewall.providers.nhc.alerts import parse_alerts
from eyewall.providers.nhc.current import parse_current_storms
from eyewall.providers.nhc.text import parse_two

CORPUS = Path(__file__).parent / "fixtures" / "real"
STATION = "41010"  # the buoy whose 5-day files are captured

KINDS: dict[str, Callable[[bytes], Any]] = {
    "current_storms": parse_current_storms,
    "outlook_at": parse_two,
    "outlook_ep": parse_two,
    "outlook_cp": parse_two,
    "alerts": parse_alerts,
    "ndbc_stations": parse_stations,
    "ndbc_latest": lambda b: parse_latest_obs(b.decode("utf-8")),
    "ndbc_5day": lambda b: parse_stdmet(b.decode("utf-8"), STATION),
    "ndbc_spec": lambda b: parse_spec(b.decode("utf-8")),
    "ndbc_supl": lambda b: parse_supl(b.decode("utf-8")),
    "coops_stations": parse_tide_stations,
    "coops_water_level": parse_water_level,
    "coops_wind": parse_wind,
    "coops_pressure": parse_air_pressure,
}


@dataclass(frozen=True)
class Capture:
    date: str
    kind: str
    path: Path
    entry: dict[str, Any]

    @property
    def id(self) -> str:
        return f"{self.date}/{self.kind}"

    def body(self) -> bytes:
        return self.path.read_bytes()


def days(root: Path = CORPUS) -> list[Path]:
    return sorted(p for p in root.glob("*") if p.is_dir())


def manifest(day: Path) -> list[dict[str, Any]]:
    return json.loads((day / "capture.json").read_text(encoding="utf-8"))["captures"]


def captures(root: Path = CORPUS) -> Iterator[Capture]:
    for day in days(root):
        for entry in manifest(day):
            yield Capture(day.name, entry["kind"], day / entry["file"], entry)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def replay(capture: Capture) -> Any:
    """Run a capture's body through its parser. Raises whatever the parser raises."""
    return KINDS[capture.kind](capture.body())
