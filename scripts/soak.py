"""Soak the headless app for N simulated hours and report what grows.

    python scripts/soak.py [--hours 6] [--source replay|wire] [--step 30] [--sample 30]

The clock is a `VirtualClock`, so six hours take about a minute: every `--step` seconds of simulated time the poller
is asked for a poll, and every few steps a screen is opened and closed so widgets are built and torn down.

  replay  The real app (Textual, headless) over the bundled Erin recording, the clock wrapping back to the start when
          the recording ends. Finds leaks in screens, the store and the alert log.
  wire    The real `Poller` over the real `LiveSource` (disk cache, retry loop, clients) over the fault-injecting fake
          NOAA in `tests/fault_support.py`, with a storm in the list and a failing host now and then. Finds leaks in
          sockets, cache files and the HTTP client. Needs a source checkout (it imports `tests`).

Every `--sample` simulated minutes it records open handles (file descriptors on POSIX, handles on Windows), sockets,
open files, threads, asyncio tasks, files left in this process's temp folder (it gets a private one), files in the
cache folder, and the traced Python heap. It ends with a table of first-after-warm-up against last, the heap's biggest
growers by line, and a verdict. Not run in CI. Exit code 1 when something grew past its limit.
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import sys
import tempfile
import threading
import tracemalloc
from dataclasses import dataclass, field
from datetime import UTC
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

WARM_UP_HOURS = 0.5  # the first half hour builds caches and pools; growth is judged after it
# What may grow over the run after warm-up before it counts as a leak.
LIMITS = {
    "handles": 8,
    "sockets": 4,
    "open files": 2,
    "threads": 2,
    "tasks": 6,
    "temp files": 0,
    "cache files": 400,
    "heap kB": 4096,
}


@dataclass
class Sample:
    hours: float
    handles: int
    sockets: int
    files: int
    threads: int
    tasks: int
    temp_files: int
    cache_files: int
    heap_kb: int


@dataclass
class Meter:
    cache_dir: Path | None = None
    samples: list[Sample] = field(default_factory=list)
    process: psutil.Process = field(default_factory=psutil.Process)
    temp_root: Path = field(default_factory=Path)
    heap_start: tracemalloc.Snapshot | None = None
    heap_warm: tracemalloc.Snapshot | None = None

    def start(self) -> None:
        self.temp_root = Path(tempfile.mkdtemp(prefix="eyewall-soak-tmp-"))
        tempfile.tempdir = str(self.temp_root)  # this process's temp files land here, so only they are counted
        tracemalloc.start(1)

    def sample(self, hours: float) -> Sample:
        gc.collect()
        proc = self.process
        handles = proc.num_handles() if hasattr(proc, "num_handles") else proc.num_fds()
        sockets = len(proc.net_connections(kind="inet"))
        files = len(proc.open_files())
        temp = {p.name for p in self.temp_root.rglob("*")}
        cache = sum(1 for _ in self.cache_dir.rglob("*")) if self.cache_dir and self.cache_dir.exists() else 0
        taken = Sample(
            hours,
            handles,
            sockets,
            files,
            max(proc.num_threads(), threading.active_count()),
            len(asyncio.all_tasks()),
            len(temp),
            cache,
            tracemalloc.get_traced_memory()[0] // 1024,
        )
        if self.heap_start is None:
            self.heap_start = tracemalloc.take_snapshot()
        if self.heap_warm is None and hours >= WARM_UP_HOURS:
            self.heap_warm = tracemalloc.take_snapshot()
        self.samples.append(taken)
        return taken


async def run_replay(hours: float, step: float, every: float, meter: Meter) -> None:
    from eyewall.app import EyewallApp
    from eyewall.config import Config
    from eyewall.sources import bundle
    from eyewall.sources.replay import ReplaySource

    source = ReplaySource(bundle.resolve_bundle(bundle.DEMO))
    app = EyewallApp(Config(), source, autoplay=False, local_tz=UTC)
    start = source.manifest.start
    end = source.advisory_times()[-1]
    screens = ["A", "b", "g", "question_mark", "ctrl+p"]
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause()
        await asyncio.wait_for(app.first_poll.wait(), 60)
        for _ in range(14):  # into the storm, as the test helpers do
            source.step_advisory(1)
        steps = int(hours * 3600 / step)
        every_steps = max(1, int(every * 60 / step))
        for n in range(steps + 1):
            source.clock.advance(step)
            if source.clock.now() > end:
                source.clock.set(start)  # the recording ended: play it again
                source.step_advisory(1)
            async with app._tick_lock:
                app.poller.refresh()
                await app.poller.tick()
            if n % 6 == 0:
                key = screens[(n // 6) % len(screens)]
                await pilot.press(key)
                await pilot.pause()
                await pilot.press("escape")
                await pilot.pause()
            if n % every_steps == 0:
                report(meter.sample(n * step / 3600))


async def run_wire(hours: float, step: float, every: float, meter: Meter, cache_dir: Path) -> None:
    from eyewall.clock import VirtualClock
    from eyewall.config import Config
    from eyewall.poll import Poller, no_sleep
    from eyewall.sources.live import LiveSource
    from eyewall.state.alerts import AlertEngine
    from eyewall.state.store import Store
    from tests.fault_support import API, COOPS, NDBC, NHC, STORM_NOW, Wire

    wire = Wire(storm=True)
    clock = VirtualClock(STORM_NOW)
    source = LiveSource(cache_dir=cache_dir, transport=wire, clock=clock)
    source.nhc._sleep = no_sleep
    poller = Poller(source, Store(Config()), AlertEngine(), Config().poll, clock=clock, sleep=no_sleep)
    hosts = (NHC, API, NDBC, COOPS)
    steps = int(hours * 3600 / step)
    every_steps = max(1, int(every * 60 / step))
    try:
        for n in range(steps + 1):
            clock.advance(step)
            if n % 40 == 20:  # a host fails for a few polls, then recovers
                wire.faults = {
                    hosts[(n // 40) % len(hosts)]: ("http-500", "timeout", "empty", "bad-json")[(n // 160) % 4]
                }
            elif n % 40 == 26:
                wire.faults = {}
            poller.refresh()
            await poller.tick()
            if n % every_steps == 0:
                report(meter.sample(n * step / 3600))
    finally:
        await source.aclose()


def report(s: Sample) -> None:
    print(
        f"{s.hours:5.2f} h  handles {s.handles:4d}  sockets {s.sockets:3d}  files {s.files:3d}  threads {s.threads:3d}"
        f"  tasks {s.tasks:4d}"
        f"  temp {s.temp_files:3d}  cache {s.cache_files:4d}  heap {s.heap_kb:6d} kB",
        flush=True,
    )


def verdict(meter: Meter) -> int:
    samples = meter.samples
    base = next((s for s in samples if s.hours >= WARM_UP_HOURS), samples[0])
    last = samples[-1]
    rows = {
        "handles": (base.handles, last.handles),
        "sockets": (base.sockets, last.sockets),
        "open files": (base.files, last.files),
        "threads": (base.threads, last.threads),
        "tasks": (base.tasks, last.tasks),
        "temp files": (base.temp_files, last.temp_files),
        "cache files": (base.cache_files, last.cache_files),
        "heap kB": (base.heap_kb, last.heap_kb),
    }
    print(f"\nafter warm-up ({base.hours:.2f} h) against the end ({last.hours:.2f} h):")
    leaks = []
    for name, (first, final) in rows.items():
        grown = final - first
        flag = "LEAK?" if grown > LIMITS[name] else "ok"
        if flag != "ok":
            leaks.append(name)
        print(f"  {name:12s} {first:7d} -> {final:7d}  ({grown:+d}, limit {LIMITS[name]})  {flag}")
    if meter.heap_warm is not None:
        print("\nheap growth by line since warm-up (top 8):")
        now = tracemalloc.take_snapshot()
        for stat in now.compare_to(meter.heap_warm, "lineno")[:8]:
            print(f"  {stat}")
    print("\nverdict:", "growth past the limit in " + ", ".join(leaks) if leaks else "no growth past the limits")
    return 1 if leaks else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hours", type=float, default=6.0, help="simulated hours (default 6)")
    parser.add_argument("--source", choices=("replay", "wire"), default="replay")
    parser.add_argument("--step", type=float, default=30.0, help="simulated seconds between polls (default 30)")
    parser.add_argument("--sample", type=float, default=30.0, help="simulated minutes between samples (default 30)")
    args = parser.parse_args()
    meter = Meter()
    with tempfile.TemporaryDirectory(prefix="eyewall-soak-") as folder:  # made before the private temp folder exists
        meter.start()
        if args.source == "wire":
            meter.cache_dir = Path(folder)
            asyncio.run(run_wire(args.hours, args.step, args.sample, meter, Path(folder)))
        else:
            asyncio.run(run_replay(args.hours, args.step, args.sample, meter))
        return verdict(meter)


if __name__ == "__main__":
    raise SystemExit(main())
