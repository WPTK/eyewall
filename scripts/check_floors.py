"""Check that each runtime dependency is installed at exactly the lower bound pyproject.toml declares.

CI's lowest-direct job runs this after installing the dev tools, to prove they did not pull a runtime dependency up.
Exit 0 if every floor is installed, 1 listing the ones that are not.
"""

import sys
import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version

ROOT = Path(__file__).resolve().parent.parent


def off_floor() -> list[str]:
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]["dependencies"]
    bad = []
    for dep in map(Requirement, deps):
        if dep.marker and not dep.marker.evaluate():
            continue
        floors = [s.version for s in dep.specifier if s.operator == ">="]
        if not floors:
            continue
        try:
            have = version(dep.name)
        except PackageNotFoundError:
            bad.append(f"{dep.name}: not installed")
            continue
        if Version(have) != Version(floors[0]):
            bad.append(f"{dep.name}: {have} installed, floor is {floors[0]}")
    return bad


if __name__ == "__main__":
    bad = off_floor()
    print("\n".join(bad) or "every runtime dependency is at its floor")
    sys.exit(1 if bad else 0)
