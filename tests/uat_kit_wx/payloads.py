"""Recorded NOAA payloads served by the fake proxy (``FakeNoaa``): feeds, listings and small valid pictures. Test-only."""

from __future__ import annotations

import json
import re
import struct
import zlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .fakenoaa import Route

FIX = Path(__file__).resolve().parents[1] / "fixtures"
NHC = "www.nhc.noaa.gov"
STAR = "cdn.star.nesdis.noaa.gov"


def png() -> bytes:
    """A 64x48 truncation-free RGB PNG."""

    def chunk(k: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + k + d + struct.pack(">I", zlib.crc32(k + d))

    raw = b"".join(b"\x00" + b"\x20\x40\x80" * 64 for _ in range(48))
    ihdr = struct.pack(">IIBBBBB", 64, 48, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def nhc_routes(storms: str) -> Route:
    """CurrentStorms.json from ``fixtures/nhc/current/<storms>.json``, the graphics landing page, any picture."""
    body = (FIX / "nhc" / "current" / f"{storms}.json").read_bytes()
    return _routes(body)


def _routes(body: bytes) -> Route:
    landing = (FIX / "nhc" / "graphics" / "landing_active_modelled.html").read_bytes()
    img = png()

    def route(host: str, path: str) -> tuple[int, str, bytes]:
        if host == NHC:
            if path.startswith("/CurrentStorms.json"):
                return 200, "application/json", body
            if path.endswith(".shtml") and "graphics" in path:
                return 200, "text/html", landing
            if path.endswith((".png", ".gif", ".jpg")):
                return 200, "image/png", img
        return 404, "text/plain", b"not found"

    return route


def active_erin_body() -> bytes:
    """``populated.json`` reduced to Erin, with every timestamp moved so that her advisory is one hour old.

    The recorded advisory is from August 2025; against a current clock the app treats that storm as long finished and
    asks for none of its graphics, which would hide the very path under test.
    """
    data = json.loads((FIX / "nhc" / "current" / "populated.json").read_text(encoding="utf-8"))
    data["activeStorms"] = [s for s in data["activeStorms"] if s["id"] == "al052025"]
    text = json.dumps(data)
    stamp = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z")
    ref = datetime.fromisoformat(data["activeStorms"][0]["lastUpdate"].replace("Z", "+00:00"))
    shift = datetime.now(UTC) - timedelta(hours=1) - ref

    def move(m: re.Match[str]) -> str:
        t = datetime.fromisoformat(m.group(0).replace("Z", "+00:00")) + shift
        return t.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    return stamp.sub(move, text).encode()


def active_storm_routes(*, satellite: bool = True) -> Route:
    """Erin as an active storm: NHC feed and landing page, plus the NESDIS satellite listings and pictures for her."""
    base = _routes(active_erin_body())
    root = (FIX / "nhc" / "graphics" / "floater_root.html").read_text(encoding="utf-8")
    if satellite:
        root = root.replace(
            '<a href="../">../</a>', '<a href="../">../</a>\n<a href="AL052025/">AL052025/</a>   01-Nov-2026 10:00   -'
        )
    prod = (
        (FIX / "nhc" / "graphics" / "floater_cp032026.html").read_text(encoding="utf-8").replace("CP032026", "AL052025")
    )
    geo = (
        (FIX / "nhc" / "graphics" / "floater_cp032026_geocolor.html")
        .read_text(encoding="utf-8")
        .replace("CP032026", "AL052025")
    )
    img = png()

    def route(host: str, path: str) -> tuple[int, str, bytes]:
        if host == STAR:
            if path == "/FLOATER/data/":
                return 200, "text/html", root.encode()
            if path == "/FLOATER/data/AL052025/":
                return 200, "text/html", prod.encode()
            if path == "/FLOATER/data/AL052025/GEOCOLOR/":
                return 200, "text/html", geo.encode()
            if path.endswith((".jpg", ".gif", ".png")):
                return 200, "image/png", img
            return 404, "text/plain", b"not found"
        return base(host, path)

    return route
