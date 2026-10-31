"""Command line: parse flags, load the configuration, start the app."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from eyewall import __version__
from eyewall.config import BASINS, GLYPH_SETS, Config, apply_overrides, load_config
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
    loaded = load_config(args.config, use_file=not args.no_config)
    config = apply_overrides(loaded.config, basins=args.basin, glyph_set=args.glyphs)
    return config, loaded.warnings


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
    return 0


def _run_app(args: argparse.Namespace, config: Config) -> int:
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
        run_app(config, source, state_dir=state_dir)
        return 0
    live = LiveSource()
    run_app(config, live, state_dir=state_dir, closer=live.aclose)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config, warnings = resolve_config(args)
    for warning in warnings:
        print(f"eyewall: config: {warning}", file=sys.stderr)
    if args.headless:
        return _headless(args, config)
    return _run_app(args, config)
