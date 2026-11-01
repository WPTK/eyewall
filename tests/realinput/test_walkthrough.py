"""Executable walkthrough on the built exe, replay of the bundled Erin recording at 120x30.

Reach every screen from Home by keyboard only, then by mouse only; click every footer cell, every crumb, every link and
every list row. Each item is recorded with the assertion that decided it (see conftest.Checks).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest

from .app import App, FooterCell
from .walk import home, sig, start_replay, ticks


@pytest.fixture
def app(artifact: Path) -> Iterator[App]:
    a = start_replay(artifact)
    yield a
    a.close()


# (name, keys from Home, what must be true on arrival)
KEY_SCREENS = [
    ("Storm", ["enter"], lambda a: a.crumb() == ["Home", "Erin"]),
    ("Buoys and gauges", ["b"], lambda a: a.crumb()[-1] == "Buoys and gauges"),
    ("Station", ["b", "enter"], lambda a: a.crumb()[-1].startswith("Buoy ")),
    ("NHC text", ["t"], lambda a: a.crumb()[-1].startswith("NHC text")),
    (
        "Wind chances",
        ["enter", "p"],
        lambda a: a.crumb()[-1].startswith("NHC text") and "Wind Speed Probabilities" in a.text(),
    ),
    ("Pictures", ["g"], lambda a: a.crumb()[-1] == "Pictures"),
    ("Outlook", ["O"], lambda a: a.crumb()[-1].startswith("NHC text") and "Outlook" in a.text()),
    ("Alerts", ["A"], lambda a: a.crumb()[-1] == "Alerts" and "Time (Z)" in a.text()),
    ("Settings", ["S"], lambda a: "Settings" in a.text() and "Poll intervals" in a.text()),
    ("Feeds", ["D"], lambda a: "Feeds" in a.text() and "Next refresh" in a.text()),
    ("Help", ["?"], lambda a: "previous or next storm" in a.text()),
    ("Menu", ["ctrl+p"], lambda a: "Search for commands" in a.text()),
    ("Find", ["/"], lambda a: "Find a buoy or tide gauge" in a.text()),
    ("Layers", ["l"], lambda a: "Map layers" in a.text()),
    ("Full map", ["M"], lambda a: "esc back" in a.text() and a.crumb() == ["Home"] and a.map_width() >= a.cols - 2),
]


def test_reach_every_screen_by_keyboard(app: App, checks) -> None:  # type: ignore[no-untyped-def]
    for name, keys, ok in KEY_SCREENS:
        home(app)
        app.key(*keys)
        checks(f"keyboard reaches {name} with {'+'.join(keys)}", ok(app), app.dump())
        home(app)
        checks(f"Esc leaves {name} to Home", app.crumb() == ["Home"] and not app.has_dialog(), app.dump())
    checks("keyboard walk: no contradictions", not app.violations, "\n".join(app.violations))
    checks.done()


def _click_cell(app: App, key: str) -> None:
    cell = next((c for c in app.footer() if c.key == key), None)
    assert cell is not None, f"footer has no {key!r} cell\n{app.dump()}"
    app.click(cell.mid, cell.y)


def _click_palette(app: App, entry: str) -> None:
    """Open the menu with its footer cell and click a command by its title (scrolling the list with the wheel)."""
    _click_cell(app, "^p")
    for _ in range(8):
        if app.find(entry):
            break
        app.wheel(10, app.rows // 2, up=False)
    app.click_text(entry)


MOUSE_SCREENS = [
    ("Storm", lambda a: a.click_text("enter open ›"), lambda a: a.crumb() == ["Home", "Erin"]),
    ("Buoys and gauges", lambda a: _click_cell(a, "b"), lambda a: a.crumb()[-1] == "Buoys and gauges"),
    ("NHC text", lambda a: _click_cell(a, "t"), lambda a: a.crumb()[-1].startswith("NHC text")),
    (
        "Outlook",
        lambda a: _click_palette(a, "Open NHC's outlook"),
        lambda a: "Outlook" in a.text() and a.crumb()[-1].startswith("NHC"),
    ),
    ("Alerts", lambda a: a.click_text(" alerts"), lambda a: a.crumb()[-1] == "Alerts"),
    ("Settings", lambda a: _click_palette(a, "Open settings"), lambda a: "Poll intervals" in a.text()),
    ("Feeds", lambda a: a.click_text("replay"), lambda a: "Next refresh" in a.text() and "Feeds" in a.text()),
    ("Help", lambda a: _click_cell(a, "?"), lambda a: "previous or next storm" in a.text()),
    ("Menu", lambda a: _click_cell(a, "^p"), lambda a: "Search for commands" in a.text()),
    ("Find", lambda a: _click_palette(a, "Find a buoy or tide gauge"), lambda a: "number..." in a.text()),
    ("Layers", lambda a: _click_cell(a, "l"), lambda a: "Map layers" in a.text()),
    (
        "Pictures",
        lambda a: _click_palette(a, "Open the selected storm's pictures"),
        lambda a: a.crumb()[-1] == "Pictures",
    ),
]


def test_reach_every_screen_by_mouse(app: App, checks) -> None:  # type: ignore[no-untyped-def]
    for name, act, ok in MOUSE_SCREENS:
        home(app)
        try:
            act(app)
            good, ev = ok(app), app.dump()
        except AssertionError as e:
            good, ev = False, str(e)
        checks(f"mouse reaches {name}", good, ev)
        home(app)
    # Station: the buoys list, then its first row
    home(app)
    _click_cell(app, "b")
    row = next((y for y, ln in enumerate(app.lines()) if ln.lstrip("* ").startswith("Buoy 4")), None)
    ok = False
    if row is not None:
        app.click(12, row)
        if not app.crumb()[-1].startswith("Buoy 4"):
            app.click(12, row)
        ok = app.crumb()[-1].startswith("Buoy 4")
    checks("mouse reaches Station by clicking a list row", ok, app.dump())
    home(app)
    # M is "go to the map" (focus the Home map; the footer then shows esc back): the palette is the mouse path
    _click_palette(app, "Go to the map")
    checks("mouse reaches the map focus (palette: Go to the map)", "esc back" in app.lines()[-1], app.dump())
    home(app)
    checks("mouse walk: no contradictions", not app.violations, "\n".join(app.violations))
    checks.done()


# screens with a footer, and the keys to get there
FOOTER_SCREENS = [
    ("Home", []),
    ("Storm", ["enter"]),
    ("Buoys and gauges", ["b"]),
    ("Station", ["b", "enter"]),
    ("NHC text", ["t"]),
    ("Pictures", ["g"]),
    ("Alerts", ["A"]),
    ("Full map", ["M"]),
]
KEY_FOR_CELL = {"+/-": "+", "left/right": "right", "^p": "ctrl+p", "esc": "escape", "/": "/"}
MAP_PREP = {"f": ["+", "+"], "c": ["+", "+", "left", "left"]}
SKIP_CELLS = {"q": "quits the app; covered by the quit scenario", "o": "opens a browser; covered in the keys scenario"}


def test_every_footer_cell_acts_like_its_key(app: App, checks) -> None:  # type: ignore[no-untyped-def]
    for screen, nav in FOOTER_SCREENS:
        home(app)
        app.key(*nav)
        cells: list[FooterCell] = app.footer()
        checks(f"{screen}: footer is readable", len(cells) >= 3, app.dump())
        for cell in cells:
            item = f"{screen}: footer cell '{cell.key} {cell.label}'"
            if screen == "Pictures" and cell.key in {"o", "y"}:
                checks.skip(item, "the Pictures screen is empty in --demo, so there is no picture to open or copy")
                continue
            if cell.key in SKIP_CELLS:
                checks.skip(item, SKIP_CELLS[cell.key])
                continue
            key = KEY_FOR_CELL.get(cell.key, cell.key)
            prep = MAP_PREP.get(cell.key, []) if screen in ("Home", "Full map") else []
            home(app)
            app.key(*nav)
            app.key("f", *prep)  # the map's zoom and pan persist, so start each comparison from a known view
            base = sig(app)
            app.click(cell.mid, cell.y)
            by_click = sig(app)
            home(app)
            app.key(*nav)
            app.key("f", *prep)
            for _ in range(4):  # a toggle (follow, sort, hours) may have changed state; cycle back to the start
                if sig(app) == base:
                    break
                app.key(key)
            app.key(key)
            by_key = sig(app)
            checks(
                item + " does what its key does",
                by_click == by_key and by_click != base,
                f"click changed screen: {by_click != base}; key and click agree: {by_click == by_key}\n"
                f"--click--\n{by_click}\n--key--\n{by_key}",
            )
    home(app)
    checks("footer walk: no contradictions", not app.violations, "\n".join(app.violations))
    checks.done()


def test_every_crumb_segment_goes_there(app: App, checks) -> None:  # type: ignore[no-untyped-def]
    for nav in (["enter"], ["b"], ["b", "enter"], ["enter", "b", "enter"], ["t"], ["g"], ["A"]):
        home(app)
        app.key(*nav)
        full = app.crumb()
        for depth in range(len(full) - 1):
            home(app)
            app.key(*nav)
            seg, x = app.crumb_cells()[depth]
            app.click(x + len(seg) // 2, 0)
            checks(
                f"crumb {'/'.join(full)}: click '{seg}'",
                app.crumb() == full[: depth + 1] and not app.has_dialog(),
                f"after the click the crumb is {app.crumb()}\n{app.dump()}",
            )
    checks("crumb walk: no contradictions", not app.violations, "\n".join(app.violations))
    checks.done()


LINK = re.compile(r"(\S.*›)\s*$|(Click here)")


def test_every_link_opens_what_it_says(app: App, checks) -> None:  # type: ignore[no-untyped-def]
    for screen, nav in (("Home", []), ("Storm", ["enter"]), ("Station", ["b", "enter"])):
        home(app)
        app.key(*nav)
        links = [
            (m.start(), y, m.group(0).strip())
            for y, ln in enumerate(app.lines())
            if (m := re.search(r"\S.*›|Click here", ln))
        ]
        checks(f"{screen}: has a link", bool(links), app.dump())
        for x, y, text in links:
            home(app)
            app.key(*nav)
            base = sig(app)
            app.click(x + max(len(text) // 2, 1), y)
            after = sig(app)
            checks(f"{screen}: link '{text[:30]}' does something", after != base, app.dump())
            if screen == "Station":  # follow toggles: it must be the opposite state, and still be there after ticks
                state = "Following" in app.text()
                ticks(app, 2.0)
                checks("Station: follow state sticks after 2 ticks", ("Following" in app.text()) == state, app.dump())
    checks("link walk: no contradictions", not app.violations, "\n".join(app.violations))
    checks.done()


def test_every_list_row_and_tab_responds(app: App, checks) -> None:  # type: ignore[no-untyped-def]
    # buoys: the near-storm tab, then Your stations
    for tab in ("Near Erin", "Your stations"):
        home(app)
        app.key("b")
        if tab != "Near Erin":
            app.click_text(tab)
            checks(
                f"Buoys: click tab '{tab}'",
                "* means you follow it" in app.text() and "Your stations" in app.text(),
                app.dump(),
            )
        rows = [y for y, ln in enumerate(app.lines()) if re.match(r"^[* ] (Buoy|Gauge) \w+", ln)]
        checks(f"Buoys/{tab}: has rows", len(rows) >= 1, app.dump())
        for i, y in enumerate(rows):
            home(app)
            app.key("b")
            if tab != "Near Erin":
                app.click_text(tab)
            ids = [re.match(r"^[* ] ((?:Buoy|Gauge) \w+)", app.lines()[r]).group(1) for r in rows]  # type: ignore[union-attr]
            app.click(8, y)
            first = app.crumb()[-1]
            if first != ids[i]:
                app.click(8, y)
            checks(
                f"Buoys/{tab}: click row {i + 1} ({ids[i]}) opens it",
                app.crumb()[-1] == ids[i],
                f"crumb {app.crumb()}\n{app.dump()}",
            )
            ticks(app, 2.0)
            checks(f"Buoys/{tab}: row {i + 1} still open after 2 ticks", app.crumb()[-1] == ids[i], app.dump())
    # NHC text: every product tab
    home(app)
    app.key("t")
    tabs = ["Public advisory", "Discussion", "Forecast advisory", "Wind chances", "Outlook", "Past track"]
    for name in tabs:
        x = app.lines()[1].find(name)
        checks(f"NHC text: tab '{name}' is shown", x >= 0, app.dump())
        if x >= 0:
            before = sig(app)
            app.click(x + len(name) // 2, 1)
            checks(
                f"NHC text: click tab '{name}'",
                name.lower() in app.lines()[3].lower() or sig(app) != before or name == "Public advisory",
                app.dump(),
            )
    # alert log rows
    home(app)
    app.key("A")
    rows = [y for y, ln in enumerate(app.lines()) if re.match(r"^Aug \d+ \d\d:\d\d ", ln)]
    checks(
        "Alerts: header count matches the rows",
        (len(rows) == 3 and "3 alerts" in app.lines()[0])
        or len(rows) == int((re.search(r"(\d+) alerts?", app.lines()[0]) or [0, -1])[1]),
        app.dump(),
    )
    for y in rows:
        before = sig(app)
        app.click(20, y)
        checks("Alerts: clicking a row does not break the screen", not app.violations and app.alive(), app.dump())
        if sig(app) != before:
            home(app)
            app.key("A")
    home(app)
    checks("list walk: no contradictions", not app.violations, "\n".join(app.violations))
    checks.done()
