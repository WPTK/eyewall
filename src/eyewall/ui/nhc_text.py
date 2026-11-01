"""The NHC text screen's content: each product laid out from its parsed sections, with a header that says which
advisory it is and a banner when it is out of date.

This is a reformatted view, not the bulletin itself: the models keep a product's sections, not its raw text, so the page
is rebuilt from them (see `ui.products`). Hard-wrapped lines are joined, some sections are collapsed, and numbers are
shown in the chosen units. The wording inside each section is NHC's own, and the watches and warnings text is kept
as NHC wrote it. Pure functions with no Textual in them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, tzinfo

from rich.console import RenderableType
from rich.text import Text

from eyewall.clock import ensure_utc, format_age, format_zulu
from eyewall.models.outlook import Chance, Outlook, OutlookArea
from eyewall.models.storm import AdvNum
from eyewall.palette import DIM, FRESHNESS_CUES, HEADING, risk_color
from eyewall.state.events import current_adv
from eyewall.state.store import StormState, storm_key
from eyewall.ui import products
from eyewall.ui.format import BASIN_NAMES, OLD_ADVISORY_HOURS, collapse, text_basins
from eyewall.ui.glyphs import UiGlyphs
from eyewall.units import Preset

# (tab id, title). The first five are NHC's products; the last is the best track the feed keeps.
TABS: tuple[tuple[str, str], ...] = (
    ("public", "Public advisory"),
    ("discussion", "Discussion"),
    ("forecast", "Forecast advisory"),
    ("chances", "Wind chances"),
    ("outlook", "Outlook"),
    ("track", "Past track"),
)
STORM_TABS = ("public", "discussion", "forecast", "chances", "track")
OUTLOOK_OLD_HOURS = 12.0  # the outlook is issued four times a day; two missed issues is old


@dataclass(frozen=True, slots=True)
class Header:
    """The line above a product: what it is and when it was issued; `stale` is the banner text, or None."""

    text: Text
    stale: str | None = None


def tab_title(tab: str) -> str:
    return dict(TABS)[tab]


def first_tab(storm: bool) -> str:
    return "public" if storm else "outlook"


def _titled(label: str, adv: AdvNum | None) -> str:
    return f"{label} {adv}" if adv is not None else label


def _issued(moment: datetime | None, tz: tzinfo | None) -> str:
    if moment is None:
        return ""
    local = ensure_utc(moment).astimezone(tz)
    return f"{local:%I:%M %p %Z %a %d %b}".lstrip("0")


def _product(state: StormState, tab: str) -> tuple[str, AdvNum | None, datetime | None] | None:
    adv = state.advisories
    if tab == "public" and adv.public is not None:
        return "Public Advisory", adv.public.adv_num, adv.public.issued
    if tab == "discussion" and adv.discussion is not None:
        return "Forecast Discussion", adv.discussion.adv_num, adv.discussion.issued
    if tab == "forecast" and adv.forecast is not None:
        return "Forecast/Advisory", adv.forecast.adv_num, adv.forecast.issued
    if tab == "chances" and adv.wind_probabilities is not None:
        return "Wind Speed Probabilities", adv.wind_probabilities.adv_num, adv.wind_probabilities.issued
    return None


def _not_heard(age: float | None) -> str:
    ago = f" for {format_age(age)}" if age is not None else " lately"
    return f"eyewall has not heard from NHC{ago}."


def _banner(g: UiGlyphs, reasons: list[str]) -> str:
    return f"{g.stale} {FRESHNESS_CUES['stale'].word.capitalize()}: {' '.join(reasons)} This text may be out of date."


def storm_header(
    state: StormState,
    tab: str,
    now: datetime,
    tz: tzinfo | None,
    g: UiGlyphs,
    *,
    feed_old: bool,
    feed_age: float | None,
    feed_error: bool = False,
) -> Header:
    """`Public Advisory 30, 5:00 PM EDT Mon 18 Aug. Issued 12m ago.`, and the banner when that is not the newest."""
    if tab == "track":
        text = Text("The best track NHC keeps for this storm, newest position first.", style=DIM)
        if feed_old:
            return Header(text, _banner(g, [_not_heard(feed_age)]))
        return Header(text)
    product = _product(state, tab)
    if product is None:
        if state.fetched_key == storm_key(state.storm):
            note = "NHC has not published this product for the current advisory."
        elif feed_error:
            note = "Could not fetch this product: the NHC feed is failing. eyewall will try again."
        else:
            note = "Not fetched yet: waiting for NHC's product for the current advisory."
        return Header(Text(note, style=DIM), _banner(g, [_not_heard(feed_age)]) if feed_old else None)
    label, adv, issued = product
    text = Text(_titled(label, adv), style="bold")
    reasons: list[str] = []
    if issued is not None:
        age = max(0.0, (now - ensure_utc(issued)).total_seconds())
        text.append(f", {_issued(issued, tz)}. ")
        text.append(f"Issued {format_age(age)} ago.", style=DIM)
        if age > OLD_ADVISORY_HOURS * 3600:
            reasons.append(f"This was issued {format_age(age)} ago.")
    current = current_adv(state.storm)
    # An intermediate advisory (31A) is a public advisory only: the other products stay at 31 and are current, so
    # they are compared by base number; the Public tab still showing 31 is the previous one, compared with the suffix.
    behind = (
        adv is not None
        and current is not None
        and (adv != current if tab == "public" else adv.number != current.number)
    )
    if behind:
        reasons.append(f"NHC's current advisory is {current}.")
    if feed_old:
        reasons.append(_not_heard(feed_age))
    if not reasons:
        return Header(text)
    return Header(text, _banner(g, reasons))


def outlook_header(
    outlook: Outlook | None,
    now: datetime,
    tz: tzinfo | None,
    g: UiGlyphs,
    *,
    feed_old: bool,
    feed_error: bool = False,
) -> Header:
    if outlook is None:
        if feed_error:
            return Header(
                Text("Could not fetch the tropical weather outlook: the NHC feed is failing.", style=DIM),
                _banner(g, [_not_heard(None)]),
            )
        return Header(Text("Waiting for the tropical weather outlook.", style=DIM))
    issued = [t.issued for t in outlook.texts if t.issued is not None]
    text = Text("Tropical Weather Outlook", style="bold")
    reasons: list[str] = []
    if issued:
        newest = max(ensure_utc(m) for m in issued)
        age = max(0.0, (now - newest).total_seconds())
        text.append(f", {_issued(newest, tz)}. ")
        text.append(f"Issued {format_age(age)} ago.", style=DIM)
        if age > OUTLOOK_OLD_HOURS * 3600:
            reasons.append(f"This was issued {format_age(age)} ago.")
    if feed_old:
        reasons.append(_not_heard(None))
    if not reasons:
        return Header(text)
    return Header(text, _banner(g, reasons))


# ---- the bodies ----------------------------------------------------------------------------------------------------


def _chance(chance: Chance | None) -> str:
    return "--" if chance is None or chance.percent is None else f"{chance.percent}%"


def _area_text(out: Text, area: OutlookArea, label: str) -> None:
    out.append(f"\n{label}", style="bold")
    if area.invest_id:
        out.append(f"  ({area.invest_id})", style=DIM)
    out.append("\n")
    out.append(collapse(area.description) + "\n")
    for name, chance in (("48 hours", area.chance_48h), ("7 days", area.chance_7d)):
        if chance is not None:
            out.append(f"  {name}: ", style=DIM)
            out.append(f"{chance.risk or '--'}, {_chance(chance)}\n", style=f"bold {risk_color(chance.risk)}")


def outlook_body(outlook: Outlook | None, basins: tuple[str, ...]) -> Text:
    """The outlook of every enabled basin: each area with its description and its 48 hour and 7 day chances."""
    out = Text()
    if outlook is None:
        out.append("Waiting for the tropical weather outlook.", style=DIM)
        return out
    shown = False
    seen: set[tuple[str, str]] = set()  # the eastern Pacific text repeats the central Pacific areas east of 180
    for text in outlook.texts:
        covered = [b for b in text_basins(text) if b in basins]
        if not covered:
            continue
        areas = [a for a in text.areas if (a.title, a.description) not in seen]
        seen.update((a.title, a.description) for a in text.areas)
        shown = True
        out.append(f"{text.region or ' / '.join(BASIN_NAMES[b] for b in covered)}\n", style=f"bold {HEADING}")
        if text.issued is not None:
            out.append(f"Issued {format_zulu(text.issued, day=True)}\n", style=DIM)
        if text.active_systems:
            out.append("\n" + collapse(text.active_systems) + "\n")
        if text.areas:
            for area in areas:
                index = text.areas.index(area) + 1
                name = f"Invest {area.invest_id}" if area.invest_id else f"Area {area.number or index}"
                _area_text(out, area, f"{name}: {collapse(area.title)}")
        else:
            out.append("\n" + collapse(text.summary) + "\n")
        out.append("\n")
    if not shown:
        out.append("No outlook for the enabled basins.", style=DIM)
    return out


def table_text(table: products.Table, note: str) -> Text:
    """A products table in aligned monospace columns: the first column left, the rest right-aligned."""
    columns, rows = table
    out = Text()
    if note:
        out.append(note + "\n\n", style=DIM)
    if not rows:
        out.append("Nothing to show yet.", style=DIM)
        return out
    widths = [max(len(columns[i]), *(len(r[i]) for r in rows)) for i in range(len(columns))]

    def line(cells: tuple[str, ...], style: str) -> None:
        parts = [c.ljust(widths[0]) if i == 0 else c.rjust(widths[i]) for i, c in enumerate(cells)]
        out.append("  ".join(parts).rstrip() + "\n", style=style)

    line(columns, f"bold {HEADING}")
    for row in rows:
        line(row, "")
    return out


def storm_body(state: StormState, tab: str, preset: Preset, tz: tzinfo | None, g: UiGlyphs) -> RenderableType:
    if tab == "public":
        return products.public_advisory(state, g)
    if tab == "discussion":
        return products.discussion(state, g)
    if tab == "forecast":
        return products.forecast_advisory(state, preset)
    if tab == "chances":
        return table_text(products.wind_probabilities(state), products.probabilities_note(state))
    return table_text(products.history_table(state, preset), "")


__all__ = [
    "STORM_TABS",
    "TABS",
    "Header",
    "first_tab",
    "outlook_body",
    "outlook_header",
    "storm_body",
    "storm_header",
    "tab_title",
    "table_text",
]
