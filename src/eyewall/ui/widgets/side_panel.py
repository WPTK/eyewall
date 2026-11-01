"""The text beside (or under) the map on the main screen, laid out as whole blocks that are kept or dropped.

A screen tier gives the panel a width and a number of rows. Each block of text is built for that width, wrapped on word
boundaries, so a line is never cut. When the blocks together are taller than the rows, the lowest-priority blocks are
left out entirely (the storm, then its warnings, are the last to go). Where only some of a group's blocks fit, the last
shown one is followed by a `+N more` line. Every line can carry the action a click on it runs.

The layout functions are pure: they take a `View` and a width and return `Block`s, so the tests need no terminal.
"""

from __future__ import annotations

import textwrap
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, tzinfo
from typing import TYPE_CHECKING

from rich.cells import cell_len
from rich.text import Text
from textual import events
from textual.widgets import Static

from eyewall.palette import HEADING
from eyewall.poll import FreshnessState
from eyewall.sources import protocol
from eyewall.sources.bundle import DEMO_TITLE
from eyewall.state.store import Store, StormState
from eyewall.ui.glyphs import UiGlyphs
from eyewall.units import Preset

if TYPE_CHECKING:
    from eyewall.app import EyewallApp

OPEN = "open"  # an action is `open:<storm id>[:<tab>]` or `do:<screen action>`
DO = "do"


@dataclass(frozen=True, slots=True)
class View:
    """Everything the blocks read, taken from the app once per paint."""

    store: Store
    preset: Preset
    now: datetime
    g: UiGlyphs
    tz: tzinfo | None
    states: tuple[StormState, ...]  # the storms in view, most intense first
    selected: str | None
    basins: tuple[str, ...]
    replay_offer: str | None  # the replay's name when `R` can start it, else None
    storms_known: bool  # the storm feed has answered at least once
    failed: frozenset[str]  # the feeds whose last poll failed: a missing report is "unavailable", never "quiet"
    ascii: bool = False
    rich: bool = False  # the wide tier: a card says more
    storms_old: bool = False  # the storm feed has stopped updating: what is shown is the last it said
    storms_age: float | None = None  # seconds since the storm feed last answered; None when the copy is a cached one
    no_color: bool = False  # NO_COLOR is set: colors are shown as greys by brightness, so a cue must not rely on one
    storms_cached: bool = False  # the storm feed is answering from the disk cache: its age is not known

    @classmethod
    def of(cls, eye: EyewallApp, states: tuple[StormState, ...], *, rich: bool = False) -> View:
        """The view of the app as it is now: what the main screen, the Storm screen and the lists read."""
        fresh = eye.poller.freshness(protocol.STORMS)
        old = fresh.state in (FreshnessState.ERROR, FreshnessState.STALE) and eye.store.storms_loaded
        failed = frozenset(f for f in protocol.FEEDS if eye.poller.freshness(f).state is FreshnessState.ERROR)
        return cls(
            store=eye.store,
            preset=eye.preset,
            now=eye.now(),
            g=eye.glyphs,
            tz=eye.local_tz,
            states=states,
            selected=eye.selected,
            basins=eye.basin_view,
            replay_offer=DEMO_TITLE if eye.replay_available() else None,
            storms_old=old,
            storms_age=None if fresh.from_cache else fresh.age,
            storms_cached=fresh.from_cache,
            no_color=eye.no_color,
            storms_known=eye.store.storms_loaded,
            failed=failed,
            ascii=eye.config.map.glyph_set == "ascii",
            rich=rich,
        )

    @property
    def chosen(self) -> StormState | None:
        return next((s for s in self.states if s.storm.id == self.selected), self.states[0] if self.states else None)


@dataclass(frozen=True, slots=True)
class Line:
    text: Text
    action: str | None = None


@dataclass(frozen=True, slots=True)
class Block:
    """Lines that stay together. `priority` 0 is kept longest. `group` names the blocks that share a `+N more` line."""

    lines: tuple[Line, ...]
    priority: int = 0
    gap: bool = False  # a blank row before it, unless it is the first shown
    group: str | None = None
    more: str | None = None  # the action of the group's `+N more` line
    section: str | None = None  # blocks of one section share a heading, which is left out when none of them is shown
    title: bool = False  # this block is the section's heading
    noun: tuple[str, str] | None = (
        None  # (singular, plural) for the `N warnings >` line when the whole group is dropped
    )
    count: int = 1  # how many of the noun this block stands for (a block can hold several watches and warnings)


def clean(text: str) -> str:
    return " ".join(text.split())


def wrapped(
    body: str,
    width: int,
    *,
    style: str = "",
    prefix: str = "",
    prefix_style: str = "",
    hang: int = 2,
    action: str | None = None,
) -> list[Line]:
    """`body` broken on spaces to `width` cells. `prefix` (a marker or an indent) leads the first line, and the rest
    start `hang` cells in. A single word wider than the room stays whole on its own line."""
    lead = cell_len(prefix)
    indent = max(lead, hang)
    parts = textwrap.wrap(clean(body), max(width - indent, 1), break_long_words=False, break_on_hyphens=False) or [""]
    out: list[Line] = []
    for index, part in enumerate(parts):
        text = Text(no_wrap=True, overflow="ellipsis")
        text.append(prefix, style=prefix_style) if index == 0 else text.append(" " * hang)
        text.append(part, style=style)
        out.append(Line(text, action))
    return out


def heading(label: str, section: str, *, action: str | None = None) -> Block:
    line = Line(Text(label, style=f"bold {HEADING}", no_wrap=True), action)
    return Block((line,), gap=True, section=section, title=True)


def link(view: View, label: str, width: int, action: str, *, key: str = "") -> Line:
    """`b open the list >`, right-aligned, underlined: the one kind of text on this panel that is a link."""
    text = Text(no_wrap=True, overflow="ellipsis")
    body = f"{key} {label}".strip()
    pad = max(width - cell_len(body) - 2, 0)
    text.append(" " * pad)
    if key:
        text.append(key, style="bold")
        text.append(" ")
    text.append(f"{label} {view.g.crumb}", style="underline")
    return Line(text, action)


def spread(left: Text, right: Text, width: int) -> Text:
    """`left` and `right` on one row with the room between them (one space at least)."""
    gap = width - left.cell_len - right.cell_len
    out = Text(no_wrap=True, overflow="ellipsis")
    out.append_text(left)
    out.append(" " * max(gap, 1))
    out.append_text(right)
    return out


def height_of(blocks: Sequence[Block]) -> int:
    rows = 0
    for position, block in enumerate(blocks):
        rows += len(block.lines) + (1 if block.gap and position else 0)
    return rows


def _more_line(label: str, width: int, action: str | None) -> Line:
    text = Text(no_wrap=True, overflow="ellipsis")
    text.append(" " * max(width - cell_len(label) - 1, 0) + label, style="underline")
    return Line(text, action)


def fit_blocks(blocks: Sequence[Block], rows: int, width: int = 0, arrow: str = ">") -> list[Line]:
    """The lines that fit `rows`: whole blocks only, the highest priority numbers dropped first (the later of two equal
    ones first).

    A group that lost some of its blocks gets a `+N more` line after its last shown block. A group that lost all of
    them (and has a `noun`) is never dropped silently: it becomes one `N warnings >` line where its first block was.
    """
    kept = list(range(len(blocks)))

    def assemble(indices: list[int]) -> list[Block]:
        present = set(indices)
        members: dict[str, list[int]] = {}
        for index, block in enumerate(blocks):
            if block.group:
                members.setdefault(block.group, []).append(index)
        whole_lost = {g: m for g, m in members.items() if not present & set(m) and blocks[m[0]].noun}
        alive = {blocks[i].section for i in indices if not blocks[i].title}
        alive |= {blocks[m[0]].section for m in whole_lost.values()}
        out: list[Block] = []
        for index, block in enumerate(blocks):
            if block.group in whole_lost and index == whole_lost[block.group][0]:
                one, many = block.noun  # type: ignore[misc]
                total = sum(blocks[i].count for i in whole_lost[block.group])
                label = f"{total} {one if total == 1 else many} {arrow}"
                out.append(Block((_more_line(label, width, block.more),), 0, gap=block.gap, section=block.section))
            elif index in present and (not block.title or block.section in alive):
                later = any(i > index and blocks[i].group == block.group for i in indices)
                lost = sum(blocks[i].count for i in members.get(block.group or "", []) if i not in present)
                if block.group and lost and not later:
                    label = f"+{lost} more {arrow}"
                    block = replace(block, lines=(*block.lines, _more_line(label, width, block.more)))
                out.append(block)
        return out

    while kept and height_of(assemble(kept)) > rows:
        kept.remove(max(kept, key=lambda i: (blocks[i].priority, i)))
    final = assemble(kept)
    if height_of(final) > rows:
        return []
    out_lines: list[Line] = []
    for position, block in enumerate(final):
        if block.gap and position:
            out_lines.append(Line(Text("")))
        out_lines.extend(block.lines)
    return out_lines


# ---- the widget ---------------------------------------------------------------------------------------------------


@dataclass
class _State:
    lines: list[Line] = field(default_factory=list)
    size: tuple[int, int] = (0, 0)


class SidePanel(Static):
    """Lays out the blocks its builder makes for its own size, and runs the action of the line that is clicked.

    `max_rows` is the most rows a panel that does not fill its height will use (the strip under the map)."""

    def __init__(self, *, id: str | None = None, max_rows: int | None = None, fill: bool = True) -> None:
        super().__init__("", id=id)
        self._build: Callable[[int], list[Block]] | None = None
        self._max_rows = max_rows
        self._fill = fill
        self._state = _State()

    @property
    def eye(self) -> EyewallApp:
        return self.app  # type: ignore[return-value]

    @property
    def lines(self) -> list[Line]:
        return self._state.lines

    def set_builder(self, build: Callable[[int], list[Block]]) -> None:
        self._build = build
        self.repaint()

    def on_resize(self) -> None:
        self.repaint()

    def text_width(self) -> int:
        return max(self.size.width - self.styles.gutter.width, 0)

    def repaint(self) -> None:
        width = self.text_width()
        if self._build is None or width < 1:
            return
        blocks = self._build(width)
        if self._fill:
            rows = self.size.height - self.styles.gutter.height
        else:
            rows = self._max_rows if self._max_rows is not None else 99
        lines = fit_blocks(blocks, rows, width, self.eye.glyphs.crumb) if rows > 0 else []
        self._state.lines = lines
        if not self._fill:
            self.styles.height = max(len(lines), 1) if lines else 0
        self.update(Text("\n").join(line.text for line in lines))

    def on_click(self, event: events.Click) -> None:
        index = event.y - self.styles.gutter.top
        lines = self._state.lines
        action = lines[index].action if 0 <= index < len(lines) else None
        if action is None:
            return
        event.stop()
        kind, _, rest = action.partition(":")
        if kind == OPEN:
            storm_id, _, tab = rest.partition(":")
            self.app.call_later(self._open, storm_id, tab or None)
        elif kind == DO:
            self.app.call_later(self.screen.run_action, rest)

    def _open(self, storm_id: str, tab: str | None) -> None:
        eye = self.eye
        if storm_id in eye.store.storms:
            eye.selected = storm_id
            self.screen.refresh_data()  # type: ignore[attr-defined]
            eye.open_storm(storm_id)


__all__ = ["DO", "OPEN", "Block", "Line", "SidePanel", "View", "fit_blocks", "heading", "link", "wrapped"]
