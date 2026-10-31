"""Write the README screenshots from the bundled Erin replay: SVG from Textual, then PNG through Microsoft Edge.

    python scripts/screenshots.py [--out docs/images]

It drives the real app headless at 140x42 over the recording, paused at advisory 14, takes three pictures (the dashboard,
the storm detail's Forecast tab and a buoy's charts) and converts each with `msedge --headless --screenshot`. Without Edge
the SVG files are kept.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import timedelta, timezone
from pathlib import Path

from eyewall.app import EyewallApp
from eyewall.config import Config
from eyewall.sources.bundle import DEMO, resolve_bundle
from eyewall.sources.replay import ReplaySource

SIZE = (140, 42)
ADVISORIES = 14


async def _settle(pilot) -> None:  # type: ignore[no-untyped-def]
    for _ in range(4):
        await pilot.pause(0.15)


async def capture(out: Path) -> list[Path]:
    app = EyewallApp(
        Config(),
        ReplaySource(resolve_bundle(DEMO)),
        autoplay=False,
        local_tz=timezone(timedelta(hours=-4), "EDT"),
    )
    written: list[Path] = []

    async def shot(name: str) -> None:
        await _settle(pilot)
        app.clear_notifications()
        path = out / f"{name}.svg"
        path.write_text(app.export_screenshot(title="eyewall"), encoding="utf-8", newline="\n")
        written.append(path)

    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await asyncio.wait_for(app.first_poll.wait(), 60)
        async with app._tick_lock:
            for _ in range(ADVISORIES):
                app.replay.step_advisory(1)
            app.poller.refresh()
            await app.poller.tick()
        await shot("dashboard")
        await pilot.press("enter", "2")
        await shot("forecast")
        await pilot.press("7", "down", "enter")
        await shot("buoy")
    return written


def to_png(svg: Path) -> bool:
    edge = shutil.which("msedge") or next(
        (p for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",) if Path(p).exists()), None
    )
    if edge is None:
        return False
    box = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg.read_text(encoding="utf-8"))
    assert box is not None
    width, height = (int(float(v)) + 1 for v in box.groups())
    png = svg.with_suffix(".png")
    for _ in range(3):  # Edge sometimes returns without writing the file; ask again
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as profile:
            subprocess.run(
                [edge, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1.25",
                 f"--user-data-dir={profile}", f"--window-size={width},{height}", f"--screenshot={png.resolve()}",
                 svg.resolve().as_uri()],
                check=False, capture_output=True, timeout=60,
            )  # fmt: skip
            for _ in range(40):  # the browser can hand off to another process and return before the file exists
                if png.exists():
                    return True
                time.sleep(0.5)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=Path("docs/images"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    svgs = asyncio.run(capture(args.out))
    done = [to_png(svg) for svg in svgs]
    for svg, ok in zip(svgs, done, strict=True):
        if ok:
            svg.unlink()  # the PNG is what the README shows
    print(f"{len(svgs)} SVG and {sum(done)} PNG files in {args.out}")
    return 0 if all(done) else 1


if __name__ == "__main__":
    sys.exit(main())
