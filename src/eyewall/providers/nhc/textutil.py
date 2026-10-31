"""Small text helpers shared by the NHC text parsers."""

from __future__ import annotations

import re

_STORM_ID = re.compile(r"\b(?P<id>(?:AL|EP|CP)\d{6})\b", re.IGNORECASE)
_NUMBERED = re.compile(r"^\s*(?P<number>\d+)\.\s+")
_FORECASTER = re.compile(r"^\s*Forecasters?\s+(?P<name>\S.*?)\s*$", re.IGNORECASE | re.MULTILINE)


def normalize_newlines(text: str | bytes) -> str:
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def collapse(text: str) -> str:
    """Runs of whitespace, newlines included, become single spaces."""
    return " ".join(text.split())


def paragraphs(text: str) -> tuple[str, ...]:
    """Blank-line separated paragraphs with their internal line breaks collapsed. Empty paragraphs are dropped."""
    blocks = re.split(r"\n\s*\n", text.strip("\n"))
    return tuple(collapse(block) for block in blocks if block.strip())


def numbered_items(text: str) -> tuple[str, ...]:
    """The items of a `1. ... 2. ...` list, each with its line breaks collapsed.

    An item is a paragraph that starts with a number and a period. The list ends at the first paragraph after the
    first item that does not start that way, so text following the list is not swallowed by the last item.
    """
    items: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text.strip("\n")):
        match = _NUMBERED.match(paragraph.lstrip("\n"))
        if match is None:
            if items:
                break
            continue
        item = collapse(paragraph.lstrip("\n")[match.end() :])
        if item:
            items.append(item)
    return tuple(items)


def find_storm_id(text: str) -> str | None:
    """The first `AL052025`-style id in the text, lower case."""
    match = _STORM_ID.search(text)
    return match["id"].lower() if match else None


def find_forecaster(text: str) -> str | None:
    matches = _FORECASTER.findall(text)
    return matches[-1] if matches else None
