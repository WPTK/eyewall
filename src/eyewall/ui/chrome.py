"""The chrome every screen shares: a top bar with the breadcrumb and the feed-health slot, and a one-row footer.

The layout functions are pure: they take words and a width and return text plus the cells that are clickable, so the
tests need no terminal. Nothing is cut mid-word. The breadcrumb shortens first (middle crumbs become an ellipsis), the
health slot never does, and a footer key appears whole or not at all, dropped from the right. `?`, the menu key and
Esc (or `q` on the first screen) sit in a pinned group that is laid out before the other keys.

Colors come from `eyewall.palette`; every cue also has a word or a glyph, so nothing is lost under NO_COLOR.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, ClassVar

from rich.cells import cell_len
from rich.text import Text
from textual import events
from textual.app import App
from textual.screen import Screen
from textual.widgets import Static

from eyewall.palette import DIM, FRESHNESS_CUES, HEADING, WARN
from eyewall.poll import Freshness, FreshnessState
from eyewall.sources import protocol
from eyewall.ui import nav
from eyewall.ui.glyphs import UiGlyphs

if TYPE_CHECKING:
    from eyewall.app import EyewallApp

FEED_LABELS = {
    protocol.STORMS: "storms",
    protocol.OUTLOOK: "outlook",
    protocol.ALERTS: "alerts",
    protocol.BUOYS: "buoys",
    protocol.TIDES: "tides",
    protocol.SATELLITE: "satellite",
}
SHORT_BELOW = 80  # the health slot and the crumb separator tighten below this width
POOR_BELOW = 70  # the pinned footer group drops its words below this width


@dataclass(frozen=True, slots=True)
class FeedStatus:
    feed: str
    freshness: Freshness
    active: bool = True


@dataclass(frozen=True, slots=True)
class ReplayStatus:
    paused: bool
    speed: int
    moment: datetime
    adv: str | None
    over: bool = False


@dataclass(frozen=True, slots=True)
class Target:
    """Cells [start, end) of a row that run `action` when clicked: `app:<action>` runs on the app, `key:<key>` is
    whatever the screen has bound to that key."""

    start: int
    end: int
    action: str


@dataclass(frozen=True, slots=True)
class Row:
    text: Text
    targets: tuple[Target, ...] = ()

    def target_at(self, x: int) -> Target | None:
        return next((t for t in self.targets if t.start <= x < t.end), None)


@dataclass(frozen=True, slots=True)
class FooterItem:
    key: str
    label: str
    target: str


def short_age(seconds: float | None) -> str:
    """12s, 3m, 2h: one unit, for the room a bar has."""
    if seconds is None:
        return ""
    s = max(0, int(seconds))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    return f"{s // 3600}h"


# ---- feed health --------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Health:
    """The words in the top bar's health slot: a glyph, a word, how old the data is. Colour is extra."""

    glyph: str
    word: str
    short: str
    age: str
    style: str

    def text(self, short: bool = False) -> Text:
        body = f"{self.glyph} {self.short if short else self.word}" + (f" {self.age}" if self.age else "")
        return Text(body, style=self.style)


def _feeds_word(count: int) -> str:
    return f"{count} feed" + ("" if count == 1 else "s")


def health(feeds: Sequence[FeedStatus], replay: ReplayStatus | None, g: UiGlyphs) -> Health:
    """The one health word for the feeds being polled: replay, offline, failing, late, checking or ok."""
    if replay is not None:
        mark = g.pause if replay.paused else g.play
        if replay.over:
            return Health(mark, "replay over", "over", "", f"bold {HEADING}")
        if replay.paused:
            return Health(mark, "replay paused", "paused", "", f"bold {HEADING}")
        return Health(mark, f"replay {replay.speed}x", "replay", "", f"bold {HEADING}")
    active = [f for f in feeds if f.active]
    storms = next((f for f in active if f.feed == protocol.STORMS and f.freshness.age is not None), None)
    ages = [f.freshness.age for f in active if f.freshness.age is not None]
    age = short_age(storms.freshness.age if storms is not None else max(ages, default=None))
    errors = [f for f in active if f.freshness.state is FreshnessState.ERROR]
    late = [f for f in active if f.freshness.state is FreshnessState.STALE]
    cue = FRESHNESS_CUES
    if any(f.freshness.from_cache for f in active):
        return Health(g.error, "offline, cached", "offline", age, f"bold {WARN}")
    if errors:
        return Health(g.error, f"{_feeds_word(len(errors))} failing", f"{len(errors)} fail", age, cue["error"].style())
    if late:
        return Health(g.stale, f"{_feeds_word(len(late))} late", f"{len(late)} late", age, cue["stale"].style())
    if not active or any(f.freshness.state is FreshnessState.LOADING for f in active):
        return Health(g.loading, "checking", "checking", "", cue["loading"].style())
    return Health(g.fresh, "data ok", "ok", age, cue["fresh"].style())


# ---- layout -------------------------------------------------------------------------------------------------------


class _Line:
    """A row being built, remembering which cells are clickable."""

    def __init__(self) -> None:
        self.text = Text(no_wrap=True, overflow="crop")
        self.targets: list[Target] = []

    @property
    def width(self) -> int:
        return self.text.cell_len

    def add(self, piece: Text | str, style: str = "", action: str | None = None) -> None:
        start = self.width
        self.text.append_text(piece) if isinstance(piece, Text) else self.text.append(piece, style=style)
        if action is not None:
            self.targets.append(Target(start, self.width, action))

    def row(self) -> Row:
        return Row(self.text, tuple(self.targets))


def fit_crumbs(labels: Sequence[str], room: int, sep: int = 3) -> list[tuple[str, int]]:
    """The breadcrumb as (text, index of the crumb a click goes back to) that fits `room` cells.

    Whole first, then the middle crumbs become one ellipsis, then only the ellipsis and the last, then the last alone,
    cut with an ellipsis as the only text that is ever cut."""
    items = [(label, index) for index, label in enumerate(labels)]

    def width(parts: list[tuple[str, int]]) -> int:
        return sum(cell_len(t) for t, _ in parts) + sep * (len(parts) - 1)

    if width(items) <= room:
        return items
    last = items[-1]
    if len(items) > 2:
        for attempt in ([items[0], ("…", len(items) - 2), last], [("…", len(items) - 2), last]):
            if width(attempt) <= room:
                return attempt
    cut = Text(last[0], no_wrap=True)
    cut.truncate(max(room, 1), overflow="ellipsis")
    return [(cut.plain, last[1])]


def top_bar(
    crumbs: Sequence[str],
    slot: Health,
    extras: Sequence[tuple[str, str | None]],
    width: int,
    g: UiGlyphs,
) -> Row:
    """Breadcrumb on the left, the health slot on the right. The slot is placed first and keeps its words; the crumb
    trail gets what is left, and `extras` (the alert count, the replay time) only what the trail leaves over."""
    short = width < SHORT_BELOW
    slot_text = slot.text(short)
    slot_w = slot_text.cell_len + 1  # one cell of margin on the right
    room = max(width - slot_w - 3, 1)  # a margin on the left and a gap of two
    sep = f" {g.crumb} "
    parts = fit_crumbs(crumbs, room, cell_len(sep))
    line = _Line()
    line.add(" ")
    for position, (label, index) in enumerate(parts):
        if position:
            line.add(sep, DIM)
        if index == len(crumbs) - 1:
            line.add(label, "bold")  # where you are; not a link
        else:
            line.add(label, f"underline {HEADING}", f"app:crumb({index})")
    left = line.width
    shown = [(text, action) for text, action in extras]
    while shown:
        need = sum(cell_len(t) for t, _ in shown) + 2 * len(shown)
        if left + need + slot_w + 1 <= width:
            break
        shown.pop()  # the least important extra goes first: they are listed most important first
    if shown:
        need = sum(cell_len(t) for t, _ in shown) + 2 * (len(shown) - 1)
        line.add(" " * (width - slot_w - need - line.width - 2))
        for position, (text, action) in enumerate(shown):
            if position:
                line.add("  ")
            line.add(text, "bold", action)
    line.add(" " * max(width - slot_w - line.width, 0))
    line.add(slot_text, action="app:feeds")
    line.add(" ")
    return line.row()


def _pair(key: str, label: str) -> Text:
    return Text.assemble((key, "bold"), " ", (label, "dim")) if label else Text(key, style="bold")


def footer_row(items: Sequence[FooterItem], pinned: Sequence[FooterItem], width: int) -> Row:
    """One row: the screen's keys on the left, in order, and the pinned group on the right.

    The pinned group is measured first: `? help  ^p menu  esc back`, or just the keys under `POOR_BELOW` columns. The
    other keys then fill the room that is left, each whole; the first that does not fit, and every key after it, is
    left out (they stay in the help and the menu)."""
    words = width >= POOR_BELOW
    placed: list[tuple[FooterItem, Text]] = []
    for item in pinned:
        placed.append((item, _pair(item.key, item.label if words else "")))
    gap = "  " if words else " "
    right_w = sum(t.cell_len for _, t in placed) + len(gap) * (len(placed) - 1)
    line = _Line()
    line.add(" ")
    room = width - right_w - 1 - 1 - 2  # margins on both sides and a gap of two
    for item in items:
        piece = _pair(item.key, item.label)
        need = piece.cell_len + (2 if line.width > 1 else 0)
        if line.width - 1 + need > room:
            break
        if line.width > 1:
            line.add("  ")
        line.add(piece, action=item.target)
    line.add(" " * max(width - right_w - 1 - line.width, 0))
    for position, (item, piece) in enumerate(placed):
        if position:
            line.add(gap)
        line.add(piece, action=item.target)
    line.add(" ")
    return line.row()


# ---- what the chrome reads from the app ---------------------------------------------------------------------------


def footer_items(screen: Screen[object]) -> tuple[list[FooterItem], list[FooterItem]]:
    """(screen keys, pinned keys) for `screen` as it is now.

    The keys are the active, enabled bindings found from the focused widget up to the app, nearest first, that the key
    table lists for the footer; inside one node they follow the table's order. The pinned group is `?`, the menu key and
    the back key, or `q` on the first screen."""
    app = screen.app
    seen: list[tuple[int, int, nav.Key, str]] = []
    nodes: dict[int, int] = {}
    taken: set[nav.Key] = set()
    for key, active in screen.active_bindings.items():
        if not active.enabled:
            continue
        node = active.node
        scopes = ("app", "replay") if isinstance(node, App) else getattr(node, "NAV_SCOPES", ())
        entry = nav.find(key, active.binding.action, scopes)
        if entry is None or not entry.footer or entry in taken or entry.action in nav.PINNED:
            continue
        taken.add(entry)
        rank = nodes.setdefault(id(node), len(nodes))
        seen.append((rank, nav.KEYS.index(entry), entry, key))
    seen.sort(key=lambda item: item[:2])
    items = [FooterItem(nav.footer_name(entry), entry.label, f"key:{key}") for _, _, entry, key in seen]
    by_action = {entry.action: entry for entry in nav.KEYS if entry.scope == "app"}
    last = nav.BACK if app.check_action(nav.BACK, ()) else nav.QUIT
    pinned = [
        FooterItem(nav.footer_name(by_action[action]), by_action[action].label, f"app:{action}")
        for action in (*nav.PINNED, last)
        if app.check_action(action, ())
    ]
    return items, pinned


# ---- widgets ------------------------------------------------------------------------------------------------------


class ChromeBar(Static):
    """A one-row bar of text with clickable cells. Subclasses say what the row is."""

    def __init__(self) -> None:
        super().__init__("")
        self.row: Row | None = None

    def build(self, width: int) -> Row:
        raise NotImplementedError

    @property
    def eye(self) -> EyewallApp:
        return self.app  # type: ignore[return-value]

    def on_mount(self) -> None:
        self.refresh_bar()

    def on_resize(self) -> None:
        self.refresh_bar()

    def refresh_bar(self) -> None:
        width = self.size.width or self.app.size.width
        if not self.is_attached or width < 1:
            return
        self.row = self.build(width)
        self.update(self.row.text)

    def on_click(self, event: events.Click) -> None:
        target = self.row.target_at(event.x) if self.row is not None else None
        if target is None:
            return
        event.stop()
        kind, _, value = target.action.partition(":")
        if kind == "app":
            # Run on the app's own queue: an action that pops this screen would otherwise wait on this handler.
            self.app.call_later(self.app.run_action, value)
            return
        active = self.screen.active_bindings.get(value)
        if active is not None and active.enabled:
            self.app.call_later(active.node.run_action, active.binding.action)  # type: ignore[attr-defined]


class TopBar(ChromeBar):
    def build(self, width: int) -> Row:
        eye = self.eye
        crumbs = [screen.crumb() for screen in eye.screen_stack if isinstance(screen, ChromeScreen)]
        return top_bar(crumbs, eye.health(), eye.top_bar_extras(), width, eye.glyphs)


class FooterBar(ChromeBar):
    def build(self, width: int) -> Row:
        items, pinned = footer_items(self.screen)
        return footer_row(items, pinned, width)


class ChromeScreen(Screen[None]):
    """A full screen with the shared chrome. A screen yields a `TopBar` first and a `FooterBar` last, names itself with
    `CRUMB` (or `crumb()`), and lists the key-table scopes it and its widgets own in `NAV_SCOPES`."""

    CRUMB: ClassVar[str] = ""
    NAV_SCOPES: ClassVar[tuple[str, ...]] = ()

    @property
    def eye(self) -> EyewallApp:
        return self.app  # type: ignore[return-value]

    def crumb(self) -> str:
        return self.CRUMB

    def can_go_back(self) -> bool:
        return True

    def go_back(self) -> None:
        self.app.pop_screen()

    def action_back(self) -> None:
        if self.can_go_back():
            self.go_back()

    def refresh_status(self) -> None:
        """Redraw the top bar and the footer; the app calls this after a poll, a focus change and every second."""
        for bar in self.query(ChromeBar):
            bar.refresh_bar()
