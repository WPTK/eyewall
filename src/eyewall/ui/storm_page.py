"""The Storm screen's page: one storm in plain words, built as whole wrapped lines.

Order of the page: the lead sentence, the watches and warnings in NHC's own words with what they mean, the numbers right
now, the forecast, the chance of wind at named places, when the next advisory is due, what changed, and a few links to
the other screens. Every sentence comes from `ui.words`; this module only lays them out. A small terminal drops the
links and the list of changes, never a watch or a warning.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text

from eyewall.palette import DIM, FRESHNESS_CUES, HEADING
from eyewall.state.events import current_adv
from eyewall.state.store import StormState
from eyewall.ui.format import collapse
from eyewall.ui.products import fmt_local
from eyewall.ui.widgets import storm_cards, warning_list
from eyewall.ui.widgets.side_panel import DO, Line, View, link, wrapped
from eyewall.ui.words import storm as storm_words
from eyewall.units import MISSING

LABEL = 10  # the width of a row label (`Wind`, `Pressure`, `Where`): values start here
BUOYS, TEXT, PICTURES, CHANCES = f"{DO}:buoys", f"{DO}:text", f"{DO}:pictures", f"{DO}:chances"


@dataclass(frozen=True, slots=True)
class Context:
    """What the page reads besides the view: how many stations are near and whether the terminal is small."""

    state: StormState
    buoys: int = 0
    gauges: int = 0
    small: bool = False


def _heading(label: str, *, first: bool = False) -> list[Line]:
    head = Line(Text(label, style=f"bold {HEADING}", no_wrap=True, overflow="ellipsis"))
    return [head] if first else [Line(Text("")), head]


def _row(label: str, value: str, width: int, *, action: str | None = None) -> list[Line]:
    return wrapped(value, width, prefix=f"  {label:<{LABEL}}", prefix_style=DIM, hang=2 + LABEL, action=action)


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def lead_lines(view: View, state: StormState, width: int) -> list[Line]:
    """The sentence at the top: what the storm is and where, then its worst warning, or that they are not yet read."""
    text = storm_words.storm_lead(state, view.preset).text
    sentences = storm_words.warning_sentences(state)
    if not warning_list.trusted(state):
        text += " " + _unread_sentence(state)
    elif sentences:
        text += " " + sentences[0].text.rstrip(".") + "."  # NHC's place names can end in a full stop
    lines = wrapped(text, width, style="bold", hang=0)
    return [*lines, *storm_cards.age_line(state, view, width, "")[:1]]


def _unread_sentence(state: StormState) -> str:
    unread = storm_words.unread_warnings(state)
    return unread.text if unread is not None else ""


def in_effect_lines(view: View, state: StormState, width: int) -> list[Line]:
    """Every watch and warning, with every place under it, as NHC worded it; then what they mean."""
    public = storm_words.current_public(state)
    head = "IN EFFECT"
    if public is not None:
        adv = current_adv(state.storm)
        when = fmt_local(public.issued, view.tz) if public.issued is not None else ""
        bits = [f"advisory {adv}" if adv else "", when if when != MISSING else ""]
        head += "  (" + ", ".join(b for b in bits if b) + ")" if any(bits) else ""
    out = _heading(head)
    if public is None:
        cue = FRESHNESS_CUES["stale"]
        glyph = cue.ascii_glyph if view.ascii else cue.glyph
        return out + wrapped(warning_list.unread_text(state), width, style=cue.style(), prefix=f"{glyph} ", hang=2)
    areas = [a for a in sorted(public.watches_warnings.in_effect, key=storm_words.area_rank) if a.areas]
    if not areas:
        return out + wrapped("None in effect.", width, style=DIM, prefix="  ")
    for area in areas:
        stroke, color = warning_list.area_marker(area, view)
        out += wrapped(
            collapse(area.label), width, style=f"bold {color}".strip(), prefix=f"{stroke} ", prefix_style=color, hang=4
        )
        phrase = storm_words.area_phrase(area)
        if phrase:
            out += wrapped(phrase, width, style=DIM, prefix="    ", hang=4)
        for place in area.areas:
            out += wrapped(collapse(place), width, prefix="    ", hang=6)
    meanings = storm_words.meaning_sentences(state)
    if meanings:
        out += _heading("WHAT THIS MEANS")
        for words in meanings:
            out += wrapped(words.text, width, prefix="  ")
    return out


def now_lines(view: View, state: StormState, width: int) -> list[Line]:
    storm, preset = state.storm, view.preset
    out = _heading("RIGHT NOW")
    wind = storm_words.wind_value(state, preset, with_knots=True)
    if wind is not None:
        out += _row("Wind", f"{wind.text} sustained", width)
    if storm.pressure_mb is not None:
        out += _row("Pressure", preset.fmt_pressure(storm.pressure_mb), width)
    moving = storm_words.moving_text(state, preset)
    if moving is not None:
        out += _row("Moving", moving.text, width)
    for index, where in enumerate(storm_words.where_lines(state, preset)):
        out += _row("Where" if index == 0 else "", where.text, width)
    size = storm_words.size_sentence(state, preset)
    if size is not None:
        out += _row("Size", size.text, width)
    return out if len(out) > 2 else []


def forecast_lines(view: View, state: StormState, width: int) -> list[Line]:
    rows = storm_words.forecast_rows(state, view.preset, view.tz)
    if not rows:
        return []
    zone = view.now.astimezone(view.tz).tzname() or "your time"
    out = _heading(f"WHERE IT IS FORECAST TO GO  ({zone})")
    for words in rows:
        out += wrapped(words.text, width, prefix="  ", hang=4, style=DIM if words.text.startswith("96 and") else "")
    strongest = storm_words.strongest(state, view.preset, view.tz)
    if strongest is not None:
        out += wrapped(strongest.text, width, prefix="  ", style="bold")
    return out


def chances_lines(view: View, state: StormState, width: int) -> list[Line]:
    words = storm_words.wind_chances(state, view.preset)
    if words is None:
        return []
    out = _heading("CHANCE OF STRONG WIND")
    out += wrapped(words.text, width, prefix="  ", action=CHANCES)
    out.append(link(view, "all places", CHANCES, key="p"))
    return out


def next_lines(view: View, state: StormState, width: int) -> list[Line]:
    nxt = storm_words.next_advisory(state)
    if nxt is None:
        return []
    return [*_heading("NEXT ADVISORY"), *wrapped(nxt.text, width, prefix="  ")]


def changes_lines(view: View, state: StormState, width: int) -> list[Line]:
    changes = storm_words.changes_this_advisory(state)
    if not changes:
        return []
    out = _heading("NEW THIS ADVISORY")
    for words in changes:
        out += wrapped(words.text, width, prefix=f"{view.g.sep} ", hang=2)
    return out


def elsewhere_lines(view: View, ctx: Context, width: int) -> list[Line]:
    name = ctx.state.storm.name.title() or ctx.state.storm.id.upper()
    near = [_plural(ctx.buoys, "buoy")] if ctx.buoys else []
    if ctx.gauges:
        near.append(_plural(ctx.gauges, "tide gauge"))
    out = _heading("ELSEWHERE")
    text = f"{' and '.join(near)} near {name}" if near else f"Buoys and tide gauges near {name}"
    out += [_link_row(view, text, "b", BUOYS, width)]
    out += [_link_row(view, "NHC graphics and satellite pictures", "g", PICTURES, width)]
    out += [_link_row(view, "The full NHC text", "t", TEXT, width)]
    return out


def _link_row(view: View, label: str, key: str, action: str, width: int) -> Line:
    body = Text(no_wrap=True, overflow="ellipsis")
    body.append("  " + label)
    tail = Text(no_wrap=True)
    tail.append(key, style="bold")
    tail.append(f" {view.g.crumb}", style="underline")
    gap = max(width - body.cell_len - tail.cell_len, 1)
    body.append(" " * gap)
    body.append_text(tail)
    return Line(body, action)


def page_lines(view: View, ctx: Context, width: int) -> list[Line]:
    """The whole page for one storm at this width."""
    state = ctx.state
    out = lead_lines(view, state, width)
    out += in_effect_lines(view, state, width)
    out += now_lines(view, state, width)
    out += forecast_lines(view, state, width)
    out += chances_lines(view, state, width)
    out += next_lines(view, state, width)
    if not ctx.small:
        out += changes_lines(view, state, width)
        out += elsewhere_lines(view, ctx, width)
    return out


__all__ = ["Context", "page_lines"]
