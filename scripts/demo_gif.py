"""Record docs/images/demo.gif from the bundled Erin replay.

    python scripts/demo_gif.py [--out docs/images/demo.gif]

It drives the real app headless at 120x30, steps through the recording one advisory at a time, then opens the storm's
Forecast tab and a buoy's charts. Each step is exported as an SVG by Textual, rendered to PNG by the helper in
screenshots.py (needs Microsoft Edge) and assembled into a GIF with Pillow.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from datetime import timedelta, timezone
from pathlib import Path

from PIL import Image
from screenshots import _settle, to_png

from eyewall.app import EyewallApp
from eyewall.config import Config
from eyewall.sources.bundle import DEMO, resolve_bundle
from eyewall.sources.replay import ReplaySource

SIZE = (120, 30)
FIRST, ADVISORY_FRAMES = 2, 12  # advisories into the recording for the first frame, then one frame per advisory
WIDTH = 960  # pixels in the finished GIF


async def capture(out: Path) -> list[tuple[Path, int]]:
    """Return (svg, milliseconds on screen) for each frame."""
    app = EyewallApp(
        Config(),
        ReplaySource(resolve_bundle(DEMO)),
        autoplay=False,
        local_tz=timezone(timedelta(hours=-4), "EDT"),
    )
    frames: list[tuple[Path, int]] = []

    async def shot(ms: int) -> None:
        await _settle(pilot)
        app.clear_notifications()
        path = out / f"f{len(frames):02d}.svg"
        path.write_text(app.export_screenshot(title="eyewall"), encoding="utf-8", newline="\n")
        frames.append((path, ms))

    async def advance(n: int) -> None:
        async with app._tick_lock:
            for _ in range(n):
                app.replay.step_advisory(1)
            app.poller.refresh()
            await app.poller.tick()

    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await asyncio.wait_for(app.first_poll.wait(), 60)
        await advance(FIRST)
        await shot(900)
        for _ in range(ADVISORY_FRAMES - 1):
            await advance(1)
            await shot(900)
        await pilot.press("enter", "2")
        await shot(2000)
        await pilot.press("7", "down", "enter")
        await shot(2500)
    return frames


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=Path("docs/images/demo.gif"))
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        frames = asyncio.run(capture(Path(tmp)))
        images = []
        for svg, _ in frames:
            if not to_png(svg):
                print("Microsoft Edge is needed to render the frames", file=sys.stderr)
                return 1
            with Image.open(svg.with_suffix(".png")) as png:
                rgb = png.convert("RGB")
                images.append(rgb.resize((WIDTH, round(rgb.height * WIDTH / rgb.width)), Image.LANCZOS))
    first, *rest = (im.quantize(128, dither=Image.Dither.NONE) for im in images)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    first.save(args.out, save_all=True, append_images=rest, duration=[ms for _, ms in frames], loop=0, optimize=True)
    print(f"{len(frames)} frames, {args.out.stat().st_size / 1e6:.2f} MB, {sum(ms for _, ms in frames) / 1000:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
