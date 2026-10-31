"""Command line: parse flags, load the configuration, start the app."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from eyewall import __version__
from eyewall.config import BASINS, GLYPH_SETS, Config, apply_overrides, load_config

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


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _config, warnings = resolve_config(args)
    for warning in warnings:
        print(f"eyewall: config: {warning}", file=sys.stderr)
    print(
        f"eyewall {__version__}: the terminal interface is not built yet (planned for 0.5.0).",
        file=sys.stderr,
    )
    return 1
