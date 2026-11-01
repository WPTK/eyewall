"""Write the README screenshots from the bundled Erin replay: SVG from Textual, then PNG through Microsoft Edge.

    python scripts/screenshots.py [--out docs/images]

It drives the real app headless at 140x42 over the recording, takes three pictures (the main screen, still named
dashboard so the README links hold, the Storm screen and a buoy's page with its charts) and converts each with
`msedge --headless=new --screenshot`. Without Edge the SVG files are kept.

It clears NO_COLOR (some shells and agent sessions set it, which makes Textual render monochrome) and asks for
truecolor before eyewall or Textual is imported, then exits non-zero if a picture has no chromatic colour.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import timedelta, timezone
from pathlib import Path

SIZE = (140, 42)
ADVISORIES = 14  # advisories to step into the recording before the first picture


async def _settle(pilot) -> None:  # type: ignore[no-untyped-def]
    for _ in range(4):
        await pilot.pause(0.15)


async def capture(out: Path) -> list[Path]:
    from eyewall.app import EyewallApp  # imported here so main() can fix the environment first
    from eyewall.config import Config
    from eyewall.sources.bundle import DEMO, resolve_bundle
    from eyewall.sources.replay import ReplaySource

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
        await pilot.press("enter")
        await shot("storm")
        await pilot.press("b", "down", "enter")
        await shot("buoy")
    return written


def force_colour() -> None:
    os.environ.pop("NO_COLOR", None)
    os.environ["COLORTERM"] = "truecolor"


_HEX = re.compile(r"#([0-9a-fA-F]{6})")
CHROMA = 30  # max(r,g,b) - min(r,g,b) above this counts as colour
MIN_COLOURS = 4  # distinct chromatic colours a colour screenshot has (map, alerts, status); greyscale has none


def chromatic_colours(svg_text: str) -> set[str]:
    """The distinct chromatic #rrggbb colours in an SVG screenshot."""
    found = set()
    for hexa in _HEX.findall(svg_text):
        r, g, b = (int(hexa[i : i + 2], 16) for i in (0, 2, 4))
        if max(r, g, b) - min(r, g, b) > CHROMA:
            found.add(hexa.lower())
    return found


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
    force_colour()
    svgs = asyncio.run(capture(args.out))
    grey = [svg.name for svg in svgs if len(chromatic_colours(svg.read_text(encoding="utf-8"))) < MIN_COLOURS]
    if grey:
        print(f"no colour in {', '.join(grey)}: is NO_COLOR or a dumb terminal still in effect?", file=sys.stderr)
        return 1
    done = [to_png(svg) for svg in svgs]
    for svg, ok in zip(svgs, done, strict=True):
        if ok:
            svg.unlink()  # the PNG is what the README shows
    print(f"{len(svgs)} SVG and {sum(done)} PNG files in {args.out}")
    return 0 if all(done) else 1


if __name__ == "__main__":
    sys.exit(main())
