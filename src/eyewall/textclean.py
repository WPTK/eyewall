"""One place that strips control characters from text a feed or a recording supplied.

An escape sequence in a storm name, a station name or a manifest title would reach the terminal as a command (move the
cursor, retitle the window), so strings are cleaned where they enter the program and again where the screens collapse
them for display. Tabs and newlines stay: callers that want one line already collapse whitespace.
"""

from __future__ import annotations

import re

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def printable(text: str) -> str:
    """`text` without C0 controls (ESC included), DEL and the C1 controls; tab and newline are kept."""
    return _CONTROL.sub("", text)
