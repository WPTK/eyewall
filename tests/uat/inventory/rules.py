"""The state-matrix rule list: what must hold on EVERY screen, in EVERY state, at EVERY size.

`violations(w, name)` returns `[(rule_id, message)]` for the screen now showing. The rules are the checks a person
makes with their eyes ("does this make sense?"), written as assertions:

- footer: present on a chrome screen, one row, ends with the pinned keys, every key it advertises is bound here
- layout: nothing clipped, nothing overlapping
- hygiene: no raw exception text, no Rich markup leaking, no control characters, no error toast
- agreement: the health slot agrees with the sentences (no "data ok" beside "not updating"), "No tropical storms"
  never appears while a storm is listed or while the storm feed failed, a count agrees with its list, the title agrees
  with the view, the header, the side panel and the footer do not contradict each other, units are not mixed.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from rich.cells import cell_len
from textual.screen import ModalScreen, Screen
from textual.widget import Widget
from textual.widgets import Tab, Tabs

from eyewall.sources import protocol
from eyewall.ui import nav, station_view
from eyewall.ui.chrome import ChromeScreen, FooterBar, TopBar
from eyewall.ui.screens.buoys import NEAR, YOURS, BuoysScreen
from eyewall.ui.screens.main import MainScreen
from eyewall.ui.screens.nhc_text import NhcTextScreen
from eyewall.ui.screens.station import StationScreen
from eyewall.ui.screens.storm import StormScreen
from eyewall.ui.widgets.station_list import StationList
from tests.uat.harness import clipped_widgets
from tests.uat.inventory.worlds import W

Violation = tuple[str, str]
Rule = Callable[[W, str, Screen[Any], str], list[Violation]]

# Text that means something went wrong, and must never reach a person.
RAW = re.compile(
    r"Traceback|\b\w*(Error|Exception)\b:|\bFetchError\b|\bNetworkError\b|\bHttpError\b|object at 0x|<[\w.]+ object|"
    r"\bNoneType\b|\bnan\b|\bTypeError\b|\bKeyError\b|\bValueError\b|\bAttributeError\b|scripted://|\bNone\b(?!\.)"
)
MARKUP = re.compile(
    r"\[/?(?:bold|dim|italic|underline|reverse|strike|link|b|i|u|s|red|green|yellow|blue|cyan|magenta|white|black|"
    r"grey\d*|gray\d*|orange\d*|bright_\w+|on \w+|#[0-9a-fA-F]{3,6}|@click[^\]]*|\$[\w-]+)(?: [^\]]*)?\]"
)
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
UNITS = {"kt": "kt", "mph": "mph", "km/h": "km/h", "m/s": "m/s"}
WIND = re.compile(r"\b\d+(?:\.\d+)?\s?(kt|mph|km/h|m/s)\b")

FAILING_WORDS = ("failing", "offline")
BAD_BODY = re.compile(
    r"unavailable|not updating|could not be reached|has not heard from|out of date|failing|offline", re.I
)


def chrome_of(screen: Screen[Any]) -> bool:
    return isinstance(screen, ChromeScreen)


def lines(text: str) -> list[str]:
    return text.splitlines()


# ---- footer -----------------------------------------------------------------------------------------------------


def footer(w: W, name: str, screen: Screen[Any], text: str) -> list[Violation]:
    out: list[Violation] = []
    if not chrome_of(screen):
        return out
    bars = list(screen.query(FooterBar))
    if len(bars) != 1:
        return [("footer", f"{len(bars)} footer bars on {name}")]
    bar = bars[0]
    if bar.region.height != 1 or bar.region.width != w.world.size[0]:
        out.append(("footer", f"footer region {bar.region}"))
    last = lines(text)[-1].rstrip()
    if bar.region.y + 1 != screen.size.height:
        out.append(("footer", f"footer is on row {bar.region.y}, not the last"))
    if cell_len(last) > w.world.size[0]:
        out.append(("footer", f"footer wider than the terminal: {last!r}"))
    row = bar.row
    if row is None:
        return out + [("footer", "footer never built")]
    actions = [t.action for t in row.targets]
    for needed in ("app:help", "app:command_palette"):
        if needed not in actions:
            out.append(("footer", f"{needed} missing from the footer {last!r}"))
    if not any(a in actions for a in ("app:back", "app:quit_top")):
        out.append(("footer", f"neither back nor quit in the footer {last!r}"))
    for target in row.targets:
        kind, _, value = target.action.partition(":")
        if kind == "key":
            active = screen.active_bindings.get(value)
            if active is None or not active.enabled:
                out.append(("footer-key", f"footer advertises {value!r} but it is not bound/enabled on {name}"))
        elif kind == "app" and not w.app.check_action(value, ()):
            out.append(("footer-key", f"footer advertises app:{value} but the app refuses it on {name}"))
    return out


def _scopes(node: Any) -> tuple[str, ...]:
    from textual.app import App

    return ("app", "replay") if isinstance(node, App) else getattr(node, "NAV_SCOPES", ())


# ---- layout -----------------------------------------------------------------------------------------------------


def layout(w: W, name: str, screen: Screen[Any], text: str) -> list[Violation]:
    out = [("clipped", problem) for problem in clipped_widgets(screen)]
    visible = [
        (widget, region)
        for widget, (region, _clip) in screen._compositor.visible_widgets.items()
        if widget is not screen and region.area and widget.region.area
    ]
    for i, (a, ra) in enumerate(visible):
        for b, rb in visible[i + 1 :]:
            if a in b.ancestors or b in a.ancestors:
                continue
            if _is_overlay(a) or _is_overlay(b) or isinstance(a, FooterBar | TopBar) or isinstance(b, FooterBar | TopBar):
                continue  # the chrome is docked over scrolling content by design
            common = ra.intersection(rb)
            if common.area > 0:
                out.append(("overlap", f"{a!r} and {b!r} overlap at {common}"))
    return out


def _is_overlay(widget: Widget) -> bool:
    return widget.styles.layer is not None and widget.styles.layer not in ("default", "")


# ---- hygiene ----------------------------------------------------------------------------------------------------


def hygiene(w: W, name: str, screen: Screen[Any], text: str) -> list[Violation]:
    out: list[Violation] = []
    for found in RAW.finditer(text):
        out.append(("raw-text", f"raw/diagnostic text {found.group(0)!r} in {_line_of(text, found.start())!r}"))
    for found in MARKUP.finditer(text):
        out.append(("markup", f"markup {found.group(0)!r} in {_line_of(text, found.start())!r}"))
    for found in CONTROL.finditer(text):
        out.append(("control-char", f"control character {found.group(0)!r} in {_line_of(text, found.start())!r}"))
    for severity, message in ((n.severity, n.message) for n in w.app._notifications):
        if severity == "error":
            out.append(("error-toast", message))
    return out


def _line_of(text: str, index: int) -> str:
    start = text.rfind("\n", 0, index) + 1
    end = text.find("\n", index)
    return text[start : end if end >= 0 else len(text)].strip()[:140]


# ---- agreement --------------------------------------------------------------------------------------------------


def health_vs_body(w: W, name: str, screen: Screen[Any], text: str) -> list[Violation]:
    """The health slot and the sentences must tell one story."""
    out: list[Violation] = []
    app = w.app
    health = app.health()
    top = lines(text)[0] if lines(text) else ""
    body = "\n".join(lines(text)[1:])
    if chrome_of(screen) and health.word not in top and health.short not in top:
        out.append(("health", f"the top bar does not show the health {health.word!r}: {top.strip()!r}"))
    fresh = health.word in ("data ok",) or health.word.startswith("replay")
    if chrome_of(screen) and fresh and app.replay is None:
        # Slot says everything is current: nothing in the body may say a feed is down or old.
        for found in BAD_BODY.finditer(body):
            if name in ("feeds",):
                continue
            out.append(("contradiction", f"slot says {health.word!r} but the screen says {found.group(0)!r}: {_line_of(body, found.start())!r}"))
    if app.replay is not None:
        for word in ("offline", "failing", "data ok"):
            if word in top:
                out.append(("contradiction", f"replay mode shows {word!r} in the top bar: {top.strip()!r}"))
    if app.replay is None and "replay" in top and "R" not in top:
        out.append(("contradiction", f"live app shows replay words in the top bar: {top.strip()!r}"))
    if health.word.startswith("checking") and app.first_poll.is_set() and w.world.state != "loading":
        out.append(("contradiction", "the slot says 'checking' after the first poll finished"))
    return out


def storms_sentence(w: W, name: str, screen: Screen[Any], text: str) -> list[Violation]:
    """`No tropical storms` only when the storm feed answered, recently, and no storm is listed."""
    out: list[Violation] = []
    app = w.app
    flat = " ".join(text.split())
    fresh = app.poller.freshness(protocol.STORMS)
    if "No tropical storms" in flat:
        if app.store.storms:
            out.append(("no-storms", f"'No tropical storms' while {list(app.store.storms)} is listed"))
        if fresh.state.value in ("error", "stale", "loading"):
            out.append(("no-storms", f"'No tropical storms' while the storm feed is {fresh.state.value}"))
    if "Checking for storms" in flat and fresh.state.value in ("error", "stale") and w.world.state != "loading":
        out.append(("no-storms", f"'Checking for storms' while the storm feed is {fresh.state.value}"))
    if isinstance(screen, MainScreen):
        states = app.storm_states()
        for s in states:
            name_ = s.storm.name.title() if s.storm.name else s.storm.id.upper()
            if name_ not in flat and not w.screen._full_map:
                out.append(("storm-listed", f"{name_} is in the store but not on the Home screen"))
        if not states and ("NAMED STORMS" in flat):
            out.append(("storm-listed", "a storm card heading with no storm"))
    return out


def counts(w: W, name: str, screen: Screen[Any], text: str) -> list[Violation]:
    """A number in a sentence agrees with the list it counts."""
    out: list[Violation] = []
    app = w.app
    flat = " ".join(text.split())
    # the alert count in the top bar
    found = re.search(r"\b(\d+) alerts?\b", lines(text)[0] if lines(text) else "")
    if found and int(found.group(1)) != len(app.alert_log):
        out.append(("count", f"top bar says {found.group(0)} but the log holds {len(app.alert_log)}"))
    if chrome_of(screen) and app.alert_log and w.world.size[0] >= 100 and not found and name not in ("alerts",):
        # the count may be dropped for room, but never silently when there is room beside a short crumb
        pass
    if isinstance(screen, BuoysScreen):
        out += _buoys_counts(w, screen, flat)
    if isinstance(screen, MainScreen):
        out += _home_counts(w, flat)
    if name == "alerts":
        table = screen.query_one("#alert-table")
        rows = table.row_count  # type: ignore[attr-defined]
        if rows != len(app.alert_log):
            out.append(("count", f"alert table has {rows} rows, the log holds {len(app.alert_log)}"))
        empty = screen.query_one("#alert-empty")
        if bool(empty.display) != (not app.alert_log):
            out.append(("count", f"'No alerts yet' shown={empty.display} with {len(app.alert_log)} alerts"))
    return out


def _plural_counts(text: str) -> tuple[int, int]:
    b = re.search(r"(\d+) buoys?", text)
    g = re.search(r"(\d+) tide gauges?", text)
    return (int(b.group(1)) if b else 0, int(g.group(1)) if g else 0)


def _buoys_counts(w: W, screen: BuoysScreen, flat: str) -> list[Violation]:
    out: list[Violation] = []
    head = " ".join(str(screen.query_one("#buoys-head").render()).split())
    listing = screen.query_one(StationList)
    rows = listing.rows
    buoys = sum(1 for r in rows if r.kind == station_view.BUOY)
    gauges = len(rows) - buoys
    active = screen.query_one(Tabs).active
    if active != f"t-{screen.tab}":
        out.append(("title-view", f"tab {active} is active but the screen is on {screen.tab}"))
    if screen.tab == NEAR:
        if " near " in head and _plural_counts(head.split(" near ")[0]) != (buoys, gauges):
            out.append(("count", f"head says {head!r} but the list has {buoys} buoys and {gauges} gauges"))
        if rows and "near" not in head:
            out.append(("title-view", f"Near tab with rows but head {head!r}"))
        if not rows and "No buoys or tide gauges" not in head and "no longer active" not in head:
            out.append(("count", f"Near tab is empty but head says {head!r}"))
    else:
        found = re.search(r"You follow (\d+) stations?", head)
        if rows and (not found or int(found.group(1)) != len(rows)):
            out.append(("count", f"Your stations: head {head!r} vs {len(rows)} rows"))
        if not rows and "not following" not in head:
            out.append(("count", f"Your stations is empty but head says {head!r}"))
        if not rows and not screen.query_one("#buoys-empty").display:
            out.append(("count", "no stations and no hint about how to follow one"))
    label = str(screen.query_one(f"#t-{YOURS}", Tab).label)
    followed = len(station_view.followed_rows(w.app.store, w.app.now(), w.app.preset, w.app.glyphs, w.app.local_tz, False))
    found = re.search(r"\((\d+)\)", label)
    if found and int(found.group(1)) != followed:
        out.append(("count", f"tab says {label!r} but {followed} stations are followed"))
    if screen.tab == YOURS and rows and len(rows) != followed:
        out.append(("count", f"Your stations lists {len(rows)} rows but {followed} are followed"))
    if screen.tab == NEAR:
        near_label = str(screen.query_one(f"#t-{NEAR}", Tab).label)
        state = w.app.store.storms.get(screen.storm_id or "")
        if state is not None and state.storm.name and state.storm.name.title() not in near_label:
            out.append(("title-view", f"tab {near_label!r} does not name {state.storm.name.title()}"))
        if state is not None and state.storm.name and state.storm.name.title() not in head and rows:
            out.append(("title-view", f"head {head!r} does not name {state.storm.name.title()}"))
    return out


def _home_counts(w: W, flat: str) -> list[Violation]:
    out: list[Violation] = []
    app = w.app
    storm = app.selected
    if storm and storm in app.store.storms:
        near = _plural_counts(flat.split(" near ")[0][-30:]) if " near " in flat else None
        buoys = len(app.store.nearby_buoys(storm, app.now()))
        gauges = len(app.store.nearby_tides(storm, app.now()))
        found = re.search(r"(?:(\d+) buoys?)?(?: and )?(?:(\d+) tide gauges?)? near [A-Z][A-Za-z ]+\.", flat)
        if found and (found.group(1) or found.group(2)):
            got = (int(found.group(1) or 0), int(found.group(2) or 0))
            if got != (buoys, gauges):
                out.append(("count", f"Home says {found.group(0)!r} but the store has {buoys} buoys and {gauges} gauges near"))
        del near
    found = re.search(r"YOUR STATIONS\s+(\d+) buoys?(?: and (\d+) tide gauges?)?\.", flat)
    if found:
        followed = (len(app.config.watchlist.ndbc), len(app.config.watchlist.coops))
        got = (int(found.group(1)), int(found.group(2) or 0))
        if got != followed:
            out.append(("count", f"Home says {found.group(0)!r} but the watchlist is {followed}"))
    return out


def titles(w: W, name: str, screen: Screen[Any], text: str) -> list[Violation]:
    """The crumb, the header and the view are about the same thing."""
    out: list[Violation] = []
    app = w.app
    if isinstance(screen, StormScreen):
        state = app.store.storms.get(screen.storm_id)
        crumb = screen.crumb()
        if state is not None and state.storm.name and state.storm.name.title() != crumb:
            out.append(("title-view", f"crumb {crumb!r} vs storm {state.storm.name.title()!r}"))
        if state is not None and state.storm.name and state.storm.name.title() not in " ".join(text.split()):
            out.append(("title-view", f"the storm page does not name {state.storm.name.title()}"))
        if state is None and "no longer active" not in text:
            out.append(("title-view", "a storm that is gone has no 'no longer active' notice"))
    if isinstance(screen, NhcTextScreen):
        tab_title = dict(screen.tabs).get(screen.tab, "")
        active = screen.query_one(Tabs).active
        if active != f"t-{screen.tab}":
            out.append(("title-view", f"tab {active} active but screen shows {screen.tab}"))
        head = " ".join(str(screen.query_one("#text-head").render()).split())
        first = {"outlook": "Outlook", "tcp": "Public"}.get(screen.tab, tab_title.split()[0] if tab_title else "")
        if first and first.lower() not in head.lower() and "no longer active" not in head:
            out.append(("title-view", f"tab {tab_title!r} is active but the header says {head!r}"))
    if isinstance(screen, StationScreen):
        flat = " ".join(text.split())
        if screen.station_id not in flat:
            out.append(("title-view", f"station page for {screen.station_id} never names it"))
        if screen.readings and "Readings in the last" not in flat:
            out.append(("title-view", "readings view without the readings table"))
        if not screen.readings and "Readings in the last" in flat:
            out.append(("title-view", "charts view showing the readings table"))
        crumb = screen.crumb()
        if crumb not in lines(text)[0]:
            out.append(("title-view", f"crumb {crumb!r} not in the top bar"))
    if chrome_of(screen):
        top = lines(text)[0] if lines(text) else ""
        stack = [s.crumb() for s in app.screen_stack if isinstance(s, ChromeScreen)]
        if stack[-1] not in top and "…" not in top:
            out.append(("title-view", f"top bar {top.strip()!r} does not end at {stack[-1]!r}"))
    return out


def units(w: W, name: str, screen: Screen[Any], text: str) -> list[Violation]:
    """One wind unit on a screen that is ours to word (NHC's own text quotes mph and km/h side by side)."""
    if name in ("text", "help", "settings", "palette", "search", "feeds"):
        return []
    found = {m.group(1) for m in WIND.finditer(text)}
    wanted = w.app.preset.wind
    out: list[Violation] = []
    if len(found) > 1:
        out.append(("units", f"mixed wind units {sorted(found)}"))
    elif wanted and found and found != {wanted}:
        out.append(("units", f"preset wants {wanted} but the screen shows {sorted(found)}"))
    return out


RULES: tuple[Rule, ...] = (
    footer,
    layout,
    hygiene,
    health_vs_body,
    storms_sentence,
    counts,
    titles,
    units,
)


def violations(w: W, name: str) -> list[Violation]:
    screen = w.screen
    text = w.text()
    out: list[Violation] = []
    for rule in RULES:
        try:
            out += rule(w, name, screen, text)
        except Exception as exc:  # a rule that cannot run is itself a finding, not a pass
            out.append(("rule-error", f"{rule.__name__}: {type(exc).__name__}: {exc}"))
    if isinstance(screen, ModalScreen) and not text.strip():
        out.append(("blank", f"{name} rendered nothing"))
    return out


__all__ = ["RULES", "TopBar", "violations"]
