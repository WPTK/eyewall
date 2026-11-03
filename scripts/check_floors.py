"""The lower bound pyproject.toml declares for each runtime dependency.

`--pins` prints them as `name==floor` lines, a constraints file for `uv pip install -c`: CI's lowest-direct job installs
the dev tools under it, so a dev tool that cannot coexist with a floor fails the install instead of raising the floor.
With no argument it checks that each one is installed at exactly its floor and exits 1 listing the ones that are not.
"""

import re
import sys
import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def floors() -> dict[str, str]:
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]["dependencies"]
    found = (re.match(r"([A-Za-z0-9_.-]+)\s*>=\s*([^,;\s]+)", dep) for dep in deps)
    return {m[1]: m[2] for m in found if m}


def off_floor() -> list[str]:
    from packaging.version import Version

    bad = []
    for name, floor in floors().items():
        try:
            have = version(name)
        except PackageNotFoundError:
            continue  # a platform-only dependency (tzdata) on another platform
        if Version(have) != Version(floor):
            bad.append(f"{name}: {have} installed, floor is {floor}")
    return bad


if __name__ == "__main__":
    if sys.argv[1:] == ["--pins"]:
        print("\n".join(f"{name}=={floor}" for name, floor in floors().items()))
        sys.exit(0)
    bad = off_floor()
    print("\n".join(bad) or "every runtime dependency is at its floor")
    sys.exit(1 if bad else 0)
