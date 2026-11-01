"""Known defects in eyewall, each filed as a GitHub issue. An item whose id starts with a key here is expected to fail.

The expectation is strict: if the item passes, the run fails and the entry has to be deleted (the defect was fixed).
"""

from __future__ import annotations

KNOWN: dict[str, str] = {}


def issue_for(item: str) -> str | None:
    for prefix, issue in KNOWN.items():
        if item.startswith(prefix):
            return issue
    return None
