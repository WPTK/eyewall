"""Every color lives in `eyewall/palette.py`. A hex literal anywhere else in the package is a second source of truth."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PALETTE = ROOT / "src" / "eyewall" / "palette.py"
HEX = re.compile(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b")


def _offenders() -> list[str]:
    found = []
    for folder in ("src", "scripts"):
        for path in sorted((ROOT / folder).rglob("*")):
            if path.suffix not in {".py", ".tcss"} or path == PALETTE:
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                # `"#"` alone and `#{...}` format strings are not colors; a comment is not a literal color either
                code = line.split("  # ")[0]
                if HEX.search(code):
                    found.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
    return found


def test_no_hex_color_literal_outside_the_palette():
    assert _offenders() == []
