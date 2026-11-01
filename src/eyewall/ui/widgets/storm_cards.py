"""The named-storm cards beside the map, and the one-line storm summary under it on a small terminal.

A card is made of the plain sentences in `ui.words`: how strong the wind is, how old the advisory is, when the next one
is due. With several storms each card also carries its own lead sentence, since the line above the map then speaks for
all of them. The selected storm is marked with a pointer as well as bold, so the mark survives NO_COLOR.
"""

from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text

from eyewall.palette import DIM, FRESHNESS_CUES
from eyewall.render.canvas import ASCII_GLYPHS, UNICODE_GLYPHS
from eyewall.state.store import StormState
from eyewall.ui.format import advisory_age, movement_text, storm_color
from eyewall.ui.widgets.side_panel import DO, OPEN, Block, Line, View, heading, link, spread, wrapped
from eyewall.ui.words import storm as storm_words

SECTION = "storms"
NEXT_STORM = f"{DO}:cursor(1)"  # the `+N more` line brings the next storm to the front, as `j` does


def storm_mark(view: View) -> str:
    return (ASCII_GLYPHS if view.ascii else UNICODE_GLYPHS).center


def _stale_line(state: StormState, view: View, width: int, action: str) -> list[Line]:
    """`Updated 12m ago.`, with the stale mark and the word when the advisory is old."""
    _age, old = advisory_age(state.storm, view.now)
    old = old or view.storms_old  # the feed itself has stopped: what is shown is the last it said
    words = storm_words.updated(state.storm, view.now).text
    if not old:
        return wrapped(words, width, style=DIM, prefix="  ", action=action)
    cue = FRESHNESS_CUES["stale"]
    glyph = cue.ascii_glyph if view.ascii else cue.glyph
    text = f"{words.rstrip('.')} ({cue.word})."
    return wrapped(text, width, style=cue.style(), prefix=f"{glyph} ", hang=2, action=action)


def card(state: StormState, view: View, width: int, *, selected: bool, lead: bool) -> list[Line]:
    storm = state.storm
    action = f"{OPEN}:{storm.id}"
    pointer = view.g.crumb if selected and len(view.states) > 1 else " "
    title = Text(no_wrap=True, overflow="ellipsis")
    title.append(f"{pointer}")
    title.append(f"{storm_mark(view)} ", style=storm_color(storm))
    name_style = "bold underline" if selected and len(view.states) > 1 else "bold"
    title.append(storm.name.title() if storm.name else storm.id.upper(), style=name_style)
    label = Text(storm_words.short_label(storm), style=f"bold {storm_color(storm)}")
    if title.cell_len + label.cell_len + 2 <= width:
        title = spread(title, label, width)
    lines = [Line(title, action)]
    if lead:
        lines += wrapped(storm_words.storm_lead(state, view.preset).text, width, prefix="  ", action=action)
    wind = storm_words.storm_wind(state, view.preset)
    if wind is not None:
        lines += wrapped(wind.text, width, prefix="  ", action=action)
    if view.rich:
        pressure = view.preset.fmt_pressure(storm.pressure_mb) if storm.pressure_mb is not None else None
        facts = [f"Pressure {pressure}"] if pressure else []
        move = movement_text(storm, view.preset)
        if move != "movement unknown":
            facts.append(f"moving {move}" if "stationary" not in move else move)
        if facts:
            lines += wrapped(", ".join(facts).capitalize() + ".", width, prefix="  ", action=action)
        size = storm_words.size_sentence(state, view.preset)
        if size is not None:
            lines += wrapped(size.text, width, prefix="  ", action=action)
    lines += _stale_line(state, view, width, action)
    nxt = storm_words.next_advisory(state)
    if nxt is not None:
        lines += wrapped(nxt.text, width, style=DIM, prefix="  ", action=action)
    lines.append(link(view, "open", width, action, key="enter" if selected else ""))
    return lines


def card_blocks(view: View, width: int) -> list[Block]:
    """The NAMED STORMS heading and one card per storm. The selected storm's card is the last to be dropped; the other
    cards go before the first warning does."""
    if not view.states:
        return []
    chosen = view.chosen
    many = len(view.states) > 1
    out = [heading("NAMED STORMS", SECTION)]
    for index, state in enumerate(view.states):
        selected = chosen is state
        lines = card(state, view, width, selected=selected, lead=many or view.rich)
        out.append(
            Block(
                tuple(lines),
                0 if selected else 2,
                gap=index > 0,
                group=SECTION,
                more=NEXT_STORM,
                section=SECTION,
                noun=("storm", "storms"),
            )
        )
    return out


def strip_line(view: View, width: int) -> Line | None:
    """`◉ Erin  Cat 4  140 mph  NW 10 mph  adv 30, 12m ago` and `open >`: the fields on the right go first when the
    row is too narrow, then the count of storms."""
    state = view.chosen
    if state is None:
        return None
    storm = state.storm
    action = f"{OPEN}:{storm.id}"
    gap = "  "
    tail = Text(f"open {view.g.crumb}", style="underline")
    head = Text(no_wrap=True, overflow="ellipsis")
    head.append(f"{storm_mark(view)} ", style=storm_color(storm))
    head.append(storm.name.title() if storm.name else storm.id.upper(), style="bold")
    head.append(f"{gap}{storm_words.short_label(storm)}", style=f"bold {storm_color(storm)}")
    age, old = advisory_age(storm, view.now)
    adv = state.advisories.adv_num or storm.adv_num
    advisory = f"adv {adv}, {age} ago" if adv and storm.last_update else f"adv {adv}" if adv else "no advisory"
    old = old or view.storms_old
    if old and storm.last_update:
        cue = FRESHNESS_CUES["stale"]
        advisory = f"{cue.ascii_glyph if view.ascii else cue.glyph} {advisory} ({cue.word})"
    wind = view.preset.fmt_wind(storm.intensity_kt) if storm.intensity_kt is not None else None
    fields = [
        f"{n} of {len(view.states)}" if (n := _position(view)) else "",
        wind or "",
        movement_text(storm, view.preset),
        advisory,
    ]
    fields = [f for f in fields if f]
    while True:
        body = head.copy()
        for item in fields:
            body.append(gap + item, style=DIM if item is fields[-1] else "")
        if body.cell_len + cell_len(gap) + tail.cell_len <= width or not fields:
            break
        fields.pop()
    return Line(spread(body, tail, width), action)


def _position(view: View) -> int:
    if len(view.states) < 2:
        return 0
    return 1 + next((i for i, s in enumerate(view.states) if s is view.chosen), 0)


__all__ = ["card", "card_blocks", "strip_line"]
