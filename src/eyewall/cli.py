"""Command line: parse flags, load the configuration, start the app."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib.resources
import sys
from collections.abc import Sequence
from pathlib import Path

from eyewall import __version__
from eyewall.config import BASINS, GLYPH_SETS, Config, LoadResult, apply_overrides, default_path, load_config
from eyewall.models.events import Event

DEMO_BUNDLE = "demo"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eyewall",
        description="Track tropical cyclones, nearby buoys and tide gauges from NOAA data in your terminal.",
    )
    parser.add_argument("--version", action="version", version=f"eyewall {__version__}")

    config = parser.add_mutually_exclusive_group()
    config.add_argument("--config", type=Path, metavar="PATH", help="read this config file instead of the default")
    config.add_argument("--no-config", action="store_true", help="ignore the config file and use built-in defaults")

    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--replay",
        metavar="BUNDLE",
        help='replay a recorded storm instead of live data: a bundle directory, or "demo" for the bundled recording',
    )
    source.add_argument("--demo", action="store_true", help="shorthand for --replay demo")

    parser.add_argument(
        "--selftest",
        action="store_true",
        help="replay the bundled storm for an hour and draw one map frame; exit 0 if the installation works",
    )
    parser.add_argument("--headless", action="store_true", help="run the poller with no interface and print the events")
    parser.add_argument(
        "--until",
        metavar="WHEN",
        help="with --headless, stop at this moment: +12h, +90m or an ISO timestamp (replay: from the bundle start)",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        metavar="DIR",
        help="where the seen-event set is saved (default: the user data directory)",
    )
    parser.add_argument(
        "--basin",
        action="append",
        type=str.upper,
        choices=BASINS,
        metavar="{AL,EP,CP}",
        help="show only this basin (repeat for several); overrides the config file",
    )
    parser.add_argument("--glyphs", choices=GLYPH_SETS, help="symbol set for the map; overrides the config file")
    return parser


def resolve_config(args: argparse.Namespace) -> tuple[Config, tuple[str, ...]]:
    """The configuration after the file and the flags, plus any warnings about the file."""
    loaded = _load(args)
    return apply_overrides(loaded.config, basins=args.basin, glyph_set=args.glyphs), loaded.warnings


def _load(args: argparse.Namespace) -> LoadResult:
    return load_config(args.config, use_file=not args.no_config)


def _selftest() -> int:
    """Parse the bundled recording through the whole poller and draw one map frame; 0 if it all worked."""
    try:
        from eyewall.config import Config
        from eyewall.headless import run_replay
        from eyewall.render.basemap import basemap_canvas
        from eyewall.render.projection import Viewport
        from eyewall.sources.bundle import demo_bundle_path
        from eyewall.sources.replay import ReplaySource

        if not (Path(str(importlib.resources.files("eyewall"))) / "ui" / "app.tcss").is_file():
            raise RuntimeError("the packaged stylesheet ui/app.tcss is missing")
        result = asyncio.run(run_replay(ReplaySource(demo_bundle_path()), Config(), None, "+1h"))
        frame = basemap_canvas(Viewport(25.0, -75.0, 0.05, 80, 24)).to_text()
        if not result.events or not frame.strip():
            raise RuntimeError(f"{len(result.events)} event(s), frame {'blank' if not frame.strip() else 'drawn'}")
    except Exception as exc:  # any failure of a frozen build is the answer
        print(f"eyewall: selftest failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"eyewall {__version__}: selftest ok ({len(result.events)} events, {result.polls} polls, 1 frame)")
    return 0


def _headless(args: argparse.Namespace, config: Config) -> int:
    from eyewall.headless import UntilError, print_event, run_live, run_replay
    from eyewall.sources.bundle import BundleError, resolve_bundle
    from eyewall.sources.replay import ReplaySource
    from eyewall.state.alerts import default_state_dir

    replaying = bool(args.replay or args.demo)
    # A replay must not read or write the user's real seen set; it keeps none unless --state-dir is given.
    state_dir = args.state_dir if args.state_dir is not None or replaying else default_state_dir()

    def emit(event: Event) -> None:
        print_event(event, sys.stdout)

    try:
        if args.replay or args.demo:
            source = ReplaySource(resolve_bundle(DEMO_BUNDLE if args.demo else args.replay))
            result = asyncio.run(run_replay(source, config, state_dir, args.until or "+12h", emit=emit))
        else:
            result = asyncio.run(run_live(config, state_dir, args.until, emit=emit))
    except (BundleError, UntilError) as exc:
        print(f"eyewall: {exc}", file=sys.stderr)
        return 2
    print(f"eyewall: {len(result.events)} event(s) in {result.polls} poll(s)", file=sys.stderr)
    if result.feeds_failed and not result.feeds_ok:  # nothing was fetched: a script must not read this as "quiet"
        print("eyewall: every feed failed", file=sys.stderr)
        return 1
    return 0


def _config_path(args: argparse.Namespace) -> Path | None:
    """Where the app saves settings and the watchlist: the file it was told to read, else the default; with
    --no-config nowhere, so changes last for the run."""
    return None if args.no_config else (args.config or default_path())


def _run_app(args: argparse.Namespace, config: Config, loaded: LoadResult | None = None) -> int:
    config_path = _config_path(args)
    # What is saved starts from the file as loaded, never from the flags, and never over a file that failed to load.
    file_config = loaded.config if loaded is not None else None
    file_broken = loaded.broken if loaded is not None else False
    from eyewall.app import run_app
    from eyewall.sources.bundle import BundleError, resolve_bundle
    from eyewall.sources.live import LiveSource
    from eyewall.sources.replay import ReplaySource
    from eyewall.state.alerts import default_state_dir

    replaying = bool(args.replay or args.demo)
    # A replay must not read or write the user's real seen set; it keeps none unless --state-dir is given.
    state_dir = args.state_dir if args.state_dir is not None or replaying else default_state_dir()
    if replaying:
        try:
            source = ReplaySource(resolve_bundle(DEMO_BUNDLE if args.demo else args.replay))
        except BundleError as exc:
            print(f"eyewall: {exc}", file=sys.stderr)
            return 2
        run_app(
            config,
            source,
            state_dir=state_dir,
            config_path=config_path,
            file_config=file_config,
            config_file_broken=file_broken,
        )
        return 0
    live = LiveSource()
    run_app(
        config,
        live,
        state_dir=state_dir,
        closer=live.aclose,
        config_path=config_path,
        file_config=file_config,
        config_file_broken=file_broken,
    )
    return 0


def _interactive() -> bool:
    """True when both stdin and stderr are terminals (either can be None or closed, as under pythonw)."""
    try:
        return bool(sys.stdin and sys.stderr and sys.stdin.isatty() and sys.stderr.isatty())
    except (ValueError, OSError, AttributeError):
        return False


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.selftest:
        return _selftest()
    loaded = _load(args)
    config = apply_overrides(loaded.config, basins=args.basin, glyph_set=args.glyphs)
    warnings = loaded.warnings
    for warning in warnings:
        print(f"eyewall: config: {warning}", file=sys.stderr)
    if args.until is not None and not args.headless:
        build_parser().error("--until needs --headless")
    if args.headless:
        return _headless(args, config)
    if warnings and _interactive():
        # The full-screen app covers stderr at once, and the settings behind these warnings are in effect as defaults.
        try:
            with contextlib.suppress(EOFError):
                input("eyewall: press Enter to start with these settings ")
        except KeyboardInterrupt:
            return 130
    return _run_app(args, config, loaded)
