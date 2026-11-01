"""Watches and warnings, most serious first, in NHC's own words: a watch means conditions are possible, a warning that
they are expected. The list beside the map, and the line under it on a small terminal.

The marker in front of each item is the same stroke the map draws for it (solid for a warning, dashed for a watch, and
so on), and the kind is always written out, so nothing depends on colour.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text

from eyewall.models.watches import WatchWarningArea
from eyewall.palette import DIM, NEUTRAL, PATTERN_SAMPLES, WATCH_WARNING_CUES
from eyewall.state.store import StormState
from eyewall.ui.format import collapse
from eyewall.ui.widgets.side_panel import OPEN, Block, Line, View, heading, spread, wrapped
from eyewall.ui.words import storm as storm_words

SECTION = "ww"
MARKER_WIDTH = 3


@dataclass(frozen=True, slots=True)
class Item:
    state: StormState
    area: WatchWarningArea


def trusted(state: StormState) -> bool:
    """True when the storm's watches and warnings are known to be the current advisory's, so that an empty list
    means none in effect rather than none read."""
    return storm_words.current_public(state) is not None


def items(view: View) -> list[Item]:
    """Every watch and warning with places under it, the most serious first; ties keep the storm and NHC's order."""
    found: list[tuple[int, int, int, Item]] = []
    for s_index, state in enumerate(view.states):
        public = storm_words.current_public(state)
        if public is None:
            continue
        for a_index, area in enumerate(public.watches_warnings.in_effect):
            if area.areas:
                found.append((storm_words.area_rank(area), s_index, a_index, Item(state, area)))
    return [item for *_, item in sorted(found, key=lambda f: f[:3])]


def known(view: View) -> bool:
    return bool(view.states) and all(trusted(s) for s in view.states)


def marker(item: Item, view: View) -> tuple[str, str]:
    """The stroke and style for an item, as the map key draws it."""
    kind = item.area.kind
    cue = WATCH_WARNING_CUES.get(kind) if kind is not None else None
    if cue is None:
        return view.g.chip, NEUTRAL
    return PATTERN_SAMPLES[cue.pattern][1 if view.ascii else 0][:MARKER_WIDTH], cue.color


def _title(item: Item, view: View, width: int) -> list[Line]:
    stroke, color = marker(item, view)
    action = f"{OPEN}:{item.state.storm.id}:{SECTION}"
    label = collapse(item.area.label)
    return wrapped(
        label,
        width,
        style=f"bold {color}",
        prefix=f"{stroke} ",
        prefix_style=color,
        hang=MARKER_WIDTH + 1,
        action=action,
    )


def item_block(item: Item, view: View, width: int, *, first: bool, priority: int, many: bool) -> Block:
    action = f"{OPEN}:{item.state.storm.id}:{SECTION}"
    lines = _title(item, view, width)
    meaning = storm_words.area_phrase(item.area)
    who = f"{item.state.storm.name.title()}: " if many and item.state.storm.name else ""
    if meaning or who:
        lines += wrapped(f"{who}{meaning or ''}".strip(), width, style=DIM, prefix="  ", action=action)
    for place in item.area.areas:
        lines += wrapped(collapse(place), width, prefix="  ", hang=4, action=action)
    return Block(tuple(lines), priority, gap=not first, group=SECTION, more=action, section=SECTION)


def blocks(view: View, width: int) -> list[Block]:
    """WATCHES AND WARNINGS: each area its own block, so a short column keeps the most serious and says `+N more`."""
    if not view.states:
        return []
    found = items(view)
    out = [heading("WATCHES AND WARNINGS", SECTION)]
    if not found:
        if not known(view):
            return []
        none = wrapped("None in effect.", width, style=DIM, prefix="  ")
        return [*out, Block(tuple(none), 1, section=SECTION)]
    many = len(view.states) > 1
    for index, item in enumerate(found):
        out.append(item_block(item, view, width, first=index == 0, priority=1 if index == 0 else 3 + index, many=many))
    return out


def strip_line(view: View, width: int) -> Line | None:
    """`─── Tropical Storm Warning: Turks and Caicos Islands, Southeast Bahamas  +3 more >` for the most serious item.
    Places that do not fit are counted, never cut."""
    if not view.states:
        return None
    found = items(view)
    if not found:
        if not known(view):
            return None
        return Line(Text("No watches or warnings in effect.", style=DIM, no_wrap=True, overflow="ellipsis"))
    top = found[0]
    stroke, color = marker(top, view)
    action = f"{OPEN}:{top.state.storm.id}:{SECTION}"
    total = sum(len(i.area.areas) for i in found)
    head = Text(no_wrap=True, overflow="ellipsis")
    head.append(f"{stroke} ", style=color)
    head.append(collapse(top.area.label), style=f"bold {color}")
    places = [collapse(p) for p in top.area.areas]
    for count in range(len(places), -1, -1):
        body = head.copy()
        if count:
            body.append(": " + ", ".join(places[:count]))
        rest = total - count
        tail = Text(f"+{rest} more {view.g.crumb}" if rest else f"open {view.g.crumb}", style="underline")
        if body.cell_len + 2 + tail.cell_len <= width:
            return Line(spread(body, tail, width), action)
    return Line(head, action)  # the label alone is wider than the row


__all__ = ["Item", "blocks", "items", "known", "marker", "strip_line", "trusted"]
