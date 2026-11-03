"""Check that CHANGELOG.md agrees with the code: its newest release is __version__, has entries and a release link.

CI runs this on every pull request; release.yml enforces the same rule against the tag. Exit 0 if fine, 1 with a reason.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def problem() -> str | None:
    version = re.search(r'^__version__ = "(.*)"$', (ROOT / "src/eyewall/__init__.py").read_text("utf-8"), re.M)
    text = (ROOT / "CHANGELOG.md").read_text("utf-8")
    heading = re.search(r"^## \[([^\]]+)\] - (\d{4}-\d{2}-\d{2})$", text, re.M)
    if not version or not heading:
        return "no __version__, or no '## [x.y.z] - YYYY-MM-DD' heading in CHANGELOG.md"
    if heading[1] != version[1]:
        return f"newest CHANGELOG.md release is {heading[1]} but __version__ is {version[1]}"
    section = re.search(r"\n(.*?)(?=^## \[|^\[[^\]]+\]: |\Z)", text[heading.end() :], re.S | re.M)
    if not section or not section[1].strip():
        return f"CHANGELOG.md has an empty section for {version[1]}"
    if not re.search(rf"^\[{re.escape(version[1])}\]: https://\S+$", text, re.M):
        return f"CHANGELOG.md has no '[{version[1]}]: <release url>' link"
    return None


if __name__ == "__main__":
    found = problem()
    if found:
        print(f"CHANGELOG check failed: {found}", file=sys.stderr)
        sys.exit(1)
    print("CHANGELOG.md agrees with __version__")
