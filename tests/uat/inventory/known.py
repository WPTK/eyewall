"""Known defects, each filed as a GitHub issue. A listed item is a strict xfail: the test that names it fails the build
when the app is fixed ("remove the marker"), so this list cannot go stale.

KNOWN_ITEMS: inventory item id -> "#issue".  KNOWN_MATRIX: (rule, state, screen) -> "#issue" (any size).
"""

from __future__ import annotations

KNOWN_ITEMS: dict[str, str] = {}
KNOWN_MATRIX: dict[tuple[str, str, str], str] = {}
