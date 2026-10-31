"""Run the UAT suite and turn every screenshot it saved into a PNG.

    python scripts/uat.py [OUT_DIR] [--keep-svg] [-- PYTEST_ARGS...]

The suite (`tests/uat`) drives the real app over the bundled Erin recording and saves an SVG per step into OUT_DIR
(default: a new temporary directory; nothing is written into the repository). Each SVG is then rendered to PNG through
Microsoft Edge, one at a time, the way `scripts/screenshots.py` does. Without Edge the SVG files are kept.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from screenshots import to_png

OUT_ENV = "EYEWALL_UAT_OUT"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out", nargs="?", type=Path, help="where the screenshots go (default: a temporary directory)")
    parser.add_argument("--keep-svg", action="store_true", help="keep the SVG files next to the PNG files")
    parser.add_argument("pytest_args", nargs="*", help="extra arguments for pytest, after --")
    args = parser.parse_args()
    out = args.out or Path(tempfile.mkdtemp(prefix="eyewall-uat-"))
    out.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, OUT_ENV: str(out.resolve())}
    command = [sys.executable, "-m", "pytest", "tests/uat", "-m", "uat", "-p", "no:cacheprovider", *args.pytest_args]
    code = subprocess.run(command, env=env, check=False).returncode
    svgs = sorted(out.glob("*.svg"))
    converted = 0
    for svg in svgs:  # one at a time: each Edge start is a whole browser
        if to_png(svg):
            converted += 1
            if not args.keep_svg:
                svg.unlink()
    print(f"{len(svgs)} screenshots, {converted} converted to PNG, in {out}")
    return code


if __name__ == "__main__":
    sys.exit(main())
