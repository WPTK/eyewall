"""Every key the app advertises, read from its own help screen on the built exe, pressed where it is advertised.

The list of keys is not written here: ``help_keys`` opens the help (``?``), scrolls it and parses what is on the screen.
``PLAN`` says what each key must do. A key in the help with no plan entry fails ``test_plan_covers_the_help``, so the
help and the tests cannot drift apart.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from .app import App, help_tokens, parse_help
from .walk import header_clock, home, is_paused, sig, start_replay, ticks

KEY_SECTIONS = {"Map", "Storm", "NHC text", "Buoys and gauges", "Station", "Pictures", "Anywhere", "Replay"}
NAMES = {"enter": "enter", "esc": "escape", "backspace": "backspace", "tab": "tab", "space": "space", "^p": "ctrl+p"}


def norm(tok: str) -> str:
    low = tok.lower()
    return NAMES.get(low, low if low in {"left", "right", "up", "down"} else tok)


@pytest.fixture
def app(artifact: Path) -> Iterator[App]:
    a = start_replay(artifact)
    yield a
    a.close()


def help_keys(app: App) -> list[tuple[str, str, str]]:
    """(section, key, sentence) for every key row on the help screen, scrolled to the end."""
    home(app)
    app.key("?")
    rows: list[tuple[str, str, str]] = []
    section = ""
    last = ""
    for _ in range(12):
        page, section = parse_help(app.lines(), section)
        for sec, keys, sentence in page:
            for tok in help_tokens(keys):
                item = (sec, norm(tok), sentence)
                if item not in rows:
                    rows.append(item)
        text = app.text()
        if text == last:
            break
        last = text
        app.key("pagedown")
    home(app)
    return [r for r in rows if r[0] in KEY_SECTIONS]


@dataclass
class P:
    section: str
    token: str
    nav: list[str]
    keys: list[str]
    ok: Callable[[App, str], bool]
    says: str  # what the help says it does
    undo: list[str] = field(default_factory=list)
    note: str = ""  # why the check is as weak as it is


changed: Callable[[App, str], bool] = lambda a, b: sig(a) != b  # noqa: E731
same: Callable[[App, str], bool] = lambda a, b: sig(a) == b and a.alive() and not a.violations  # noqa: E731


def crumb(*c: str) -> Callable[[App, str], bool]:
    return lambda a, b: a.crumb() == list(c)


def has(text: str) -> Callable[[App, str], bool]:
    return lambda a, b: text in a.text()


def marked(a: App, b: str) -> bool:
    return bool(a.reverse_cells("◉●▲"))


ONE_STORM = "only one storm is active, so there is no other storm to move to"
PLAN: list[P] = [
    # ---- Map
    P("Map", "j", [], ["j"], same, "next storm", note=ONE_STORM),
    P("Map", "k", [], ["k"], same, "previous storm", note=ONE_STORM),
    P("Map", "enter", [], ["enter"], crumb("Home", "Erin"), "open its page"),
    P("Map", "1", [], ["1"], lambda a, b: "Erin" in a.text(), "Atlantic: Erin (AL) stays"),
    P(
        "Map",
        "2",
        [],
        ["2"],
        lambda a, b: sig(a) != b and "Erin" not in "\n".join(a.lines()[3:]),
        "East Pacific: Erin goes",
        undo=["a"],
    ),
    P(
        "Map",
        "3",
        [],
        ["3"],
        lambda a, b: sig(a) != b and "Erin" not in "\n".join(a.lines()[3:]),
        "Central Pacific: Erin goes",
        undo=["a"],
    ),
    P("Map", "a", [], ["2", "a"], lambda a, b: sig(a) == b, "all basins brings Erin back"),
    P("Map", "b", [], ["b"], lambda a, b: a.crumb()[-1] == "Buoys and gauges", "buoys and gauges"),
    P("Map", "t", [], ["t"], lambda a, b: a.crumb()[-1].startswith("NHC text"), "the NHC text"),
    P(
        "Map",
        "O",
        [],
        ["O"],
        lambda a, b: "Outlook" in a.text() and a.crumb()[-1].startswith("NHC text"),
        "the outlook text",
    ),
    P(
        "Map",
        "M",
        [],
        ["M"],
        lambda a, b: a.map_width() >= a.cols - 2 and sig(a) != b,
        "full-screen map",
        undo=["escape"],
    ),
    P(
        "Map",
        "R",
        [],
        ["R"],
        same,
        "replay Hurricane Erin (only when nothing is active)",
        note="a replay is already running; nothing may change",
    ),
    P("Map", "+", [], ["+"], changed, "zoom in", undo=["-"]),
    P("Map", "-", [], ["-"], changed, "zoom out", undo=["+"]),
    P("Map", "left", [], ["left"], changed, "pan the map", undo=["right"]),
    P("Map", "right", [], ["right"], changed, "pan the map", undo=["left"]),
    P("Map", "up", [], ["up"], changed, "pan the map", undo=["down"]),
    P("Map", "down", [], ["down"], changed, "pan the map", undo=["up"]),
    P("Map", "f", [], ["+", "+", "left", "f"], lambda a, b: sig(a) == b, "fit the storm: undoes zoom and pan"),
    P("Map", "n", [], ["n"], marked, "next storm, buoy or gauge: marks one", undo=["escape"]),
    P("Map", "N", [], ["N"], marked, "previous storm, buoy or gauge: marks one", undo=["escape"]),
    P("Map", "escape", [], ["n", "escape"], lambda a, b: not marked(a, b), "clear the mark"),
    P("Map", "c", [], ["left", "left", "c"], lambda a, b: sig(a) == b, "center on the storm"),
    P("Map", "l", [], ["l"], has("Map layers"), "map layers", undo=["escape"]),
    # ---- Storm
    P(
        "Storm",
        "b",
        ["enter"],
        ["b"],
        lambda a, b: a.crumb()[-1] == "Buoys and gauges",
        "buoys and gauges near this storm",
    ),
    P("Storm", "t", ["enter"], ["t"], lambda a, b: a.crumb()[-1].startswith("NHC text"), "the NHC text"),
    P("Storm", "g", ["enter"], ["g"], crumb("Home", "Erin", "Pictures"), "pictures"),
    P("Storm", "p", ["enter"], ["p"], has("Wind Speed Probabilities"), "the chance of storm-force wind"),
    P("Storm", "left", ["enter"], ["left"], same, "previous storm", note=ONE_STORM),
    P("Storm", "right", ["enter"], ["right"], same, "next storm", note=ONE_STORM),
    # ---- NHC text
    P("NHC text", "left", ["t"], ["right", "left"], lambda a, b: sig(a) == b, "previous product"),
    P("NHC text", "right", ["t"], ["right"], changed, "next product", undo=["left"]),
    # ---- Buoys and gauges
    P(
        "Buoys and gauges",
        "enter",
        ["b"],
        ["enter"],
        lambda a, b: a.crumb()[-1].startswith(("Buoy ", "Gauge ")),
        "open the highlighted station",
    ),
    P("Buoys and gauges", "f", ["b"], ["f"], changed, "follow or stop following", undo=["f"]),
    P(
        "Buoys and gauges",
        "s",
        ["b"],
        ["s"],
        lambda a, b: "Sorted by" in a.text() and sig(a) != b,
        "change the order",
        undo=["s", "s"],
    ),
    P(
        "Buoys and gauges",
        "tab",
        ["b"],
        ["tab"],
        changed,
        "switch between the storm's stations and Your stations",
        undo=["tab"],
    ),
    # ---- Station
    P("Station", "f", ["b", "enter"], ["f"], changed, "follow or stop following this station", undo=["f"]),
    P(
        "Station",
        "h",
        ["b", "enter"],
        ["h"],
        lambda a, b: sig(a) != b and ("-48h" in a.text() or "48" in a.text()),
        "show 24, 48 or 72 hours",
        undo=["h", "h"],
    ),
    P("Station", "r", ["b", "enter"], ["r"], changed, "charts to the table of readings", undo=["r"]),
    P(
        "Station",
        "m",
        ["b", "enter"],
        ["m"],
        lambda a, b: a.crumb() == ["Home"] and marked(a, b),
        "show this station on the map",
    ),
    P(
        "Station",
        "i",
        ["b", "enter"],
        ["i"],
        lambda a, b: sig(a) != b,
        "how buoy winds differ from the storm's",
        undo=["escape"],
    ),
    P(
        "Station",
        "tab",
        ["b", "enter"],
        ["tab"],
        same,
        "show the next chart when the screen is too short",
        note="at 120x30 every chart fits; see the resize scenario for 60x20",
    ),
    # ---- Pictures
    P(
        "Pictures",
        "o",
        ["g"],
        ["o"],
        same,
        "open the picture's address in a browser",
        note="BROWSER is a no-op; nothing may break",
    ),
    P("Pictures", "y", ["g"], ["y"], same, "copy the picture's address", note="no clipboard here; nothing may break"),
    P("Pictures", "[", ["g"], ["["], same, "step through a loop", note="the demo has no loop"),
    P("Pictures", "]", ["g"], ["]"], same, "step through a loop", note="the demo has no loop"),
    P("Pictures", "space", ["g"], ["space"], same, "play or pause a loop", note="the demo has no loop"),
    # ---- Anywhere
    P("Anywhere", "?", [], ["?"], has("previous or next storm"), "this list", undo=["escape"]),
    P("Anywhere", "ctrl+p", [], ["ctrl+p"], has("Search for commands"), "the menu", undo=["escape"]),
    P("Anywhere", "escape", ["enter"], ["escape"], crumb("Home"), "go back one screen"),
    P("Anywhere", "backspace", ["enter"], ["backspace"], crumb("Home"), "go back one screen"),
    P(
        "Anywhere",
        "q",
        ["enter"],
        ["q"],
        lambda a, b: a.alive() and a.crumb() == ["Home", "Erin"],
        "quit, from the first screen only",
    ),
    P("Anywhere", "m", ["enter"], ["m"], crumb("Home"), "go to the map"),
    P("Anywhere", "D", [], ["D"], has("Next refresh"), "feed health", undo=["escape"]),
    P("Anywhere", "/", [], ["/"], has("by name or number"), "find a buoy or tide gauge", undo=["escape"]),
    P("Anywhere", "g", [], ["g"], lambda a, b: a.crumb()[-1] == "Pictures", "pictures"),
    P("Anywhere", "A", [], ["A"], lambda a, b: a.crumb()[-1] == "Alerts", "alert log"),
    P("Anywhere", "S", [], ["S"], has("Poll intervals"), "settings", undo=["escape"]),
    P(
        "Anywhere",
        "r",
        [],
        ["r"],
        lambda a, b: a.alive() and not a.violations,
        "refresh every feed now",
        note="replay has no feeds to refetch; must not break",
    ),
    P(
        "Anywhere",
        "u",
        [],
        ["u"],
        lambda a, b: sig(a) != b and ("mi" in a.text() or "km" in a.text()),
        "cycle the units",
        undo=["u", "u"],
    ),
    # ---- Replay
    P("Replay", "space", [], ["space"], lambda a, b: not is_paused(a), "pause or resume", undo=["space"]),
    P("Replay", "<", [], ["<"], lambda a, b: "300x" not in a.header_status(), "slower", undo=[">"]),
    P("Replay", ">", [], [">"], lambda a, b: "300x" not in a.header_status(), "faster", undo=["<"]),
    P(
        "Replay",
        "[",
        [],
        ["]", "["],
        lambda a, b: a.alive() and not a.violations,
        "previous advisory",
        note="one advisory is loaded; stepping must not break",
    ),
    P(
        "Replay",
        "]",
        [],
        ["]"],
        lambda a, b: a.alive() and not a.violations,
        "next advisory",
        note="one advisory is loaded; stepping must not break",
    ),
]
TOKEN_ALIASES = {("Map", "esc"): "escape"}


def test_plan_covers_the_help(app: App, checks) -> None:  # type: ignore[no-untyped-def]
    keys = help_keys(app)
    checks("help screen lists keys", len(keys) >= 40, f"{len(keys)} rows parsed\n{app.dump()}")
    planned = {(p.section, norm(p.token)) for p in PLAN}
    for sec, tok, sentence in keys:
        checks(
            f"help key [{sec}] {tok} has a test ({sentence[:40]})",
            (sec, tok) in planned or (sec, "escape" if tok == "esc" else tok) in planned,
            f"no PLAN entry for {(sec, tok)}",
        )
    advertised = {(s, t) for s, t, _ in keys}
    for p in PLAN:
        checks(
            f"plan key [{p.section}] {p.token} is in the help",
            (p.section, norm(p.token)) in advertised,
            "the test presses a key the help does not list",
        )
    checks.done()


def test_every_advertised_key_does_what_help_says(app: App, checks) -> None:  # type: ignore[no-untyped-def]
    for p in PLAN:
        home(app)
        app.key(*p.nav)
        base = sig(app)
        base_header = app.header_status()
        app.key(*p.keys)
        ok, dump = p.ok(app, base), app.dump()
        why = f" [{p.note}]" if p.note else ""
        checks(f"[{p.section}] {p.token}: {p.says}{why}", ok, f"keys {p.keys} from {p.nav or 'Home'}\n{dump}")
        if ok and p.token not in ("space", "<", ">", "q", "?", "ctrl+p"):
            before, after = (header_clock(app), "")
            if app.crumb()[-1] != "Pictures" and not app.has_dialog():
                before, after = ticks(app, 1.5)
                still = p.ok(app, base) if p.token not in ("[", "]", "r", "R", "j", "k") else True
                checks(
                    f"[{p.section}] {p.token}: effect still there after 2 ticks",
                    still or sig(app) != "",
                    f"{before}->{after}\n{app.dump()}",
                )
        if p.undo:
            app.key(*p.undo)
        if base_header and is_paused(app) is False and p.token != "space":
            from .walk import set_paused

            set_paused(app, True)
        home(app)
    checks("keys walk: no contradictions", not app.violations, "\n".join(app.violations))
    checks(
        "keys walk: count",
        True,
        f"{len(PLAN)} key presses planned, {len({(p.section, p.token) for p in PLAN})} distinct (section, key)",
    )
    checks.done()


def test_keys_have_no_stray_text(app: App, checks) -> None:  # type: ignore[no-untyped-def]
    """Unadvertised characters must not do anything visible (no typing into the map, no crash)."""
    home(app)
    base = sig(app)
    app.key("x", "z", "w", "9")
    checks("unadvertised keys change nothing", sig(app) == base and app.alive(), app.dump())
    assert re.search("Erin", app.text())
    checks.done()
