"""Marks on the map: click each one on the built exe, and keep the map and the lists pointing at the same thing."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest

from .app import MAP_GLYPHS, App
from .walk import home, start_replay, ticks


@pytest.fixture
def app(artifact: Path) -> Iterator[App]:
    a = start_replay(artifact)
    yield a
    a.close()


def map_marks(app: App) -> list[tuple[str, int, int]]:
    """Every storm, buoy and gauge glyph inside the map area (not the legend, not the side panel)."""
    mw = app.map_width()
    out = []
    for kind, glyph in MAP_GLYPHS.items():
        for x, y in app.find_all(glyph):
            if 3 <= y < app.rows - 4 and x < mw:
                out.append((kind, x, y))
    return sorted(out, key=lambda m: (m[2], m[1]))


def opened_name(app: App) -> str:
    """The thing the screen is about, from its crumb: 'Erin', 'Buoy 41047', 'Gauge 8721604'."""
    return app.crumb()[-1]


def test_click_every_mark_on_the_map(app: App, checks) -> None:  # type: ignore[no-untyped-def]
    marks = map_marks(app)
    checks("map shows marks", len(marks) >= 2, app.dump())
    kinds = {k for k, _, _ in marks}
    checks("map shows a storm mark", "storm" in kinds, f"marks: {marks}")
    seen: dict[str, tuple[int, int]] = {}
    for kind, x, y in marks:
        home(app)
        again = map_marks(app)
        item = f"click {kind} mark at ({x},{y})"
        if (kind, x, y) not in again:
            checks(item + ": map is stable between visits", False, f"marks now {again}")
            continue
        app.click(x, y)
        name = opened_name(app)
        opened = (
            (kind == "storm" and name == "Erin")
            or (kind == "buoy" and name.startswith("Buoy "))
            or (kind == "gauge" and name.startswith("Gauge "))
        )
        if not opened and app.has_dialog():  # a chooser when marks overlap: take the first entry
            app.key("enter")
            name = opened_name(app)
            opened = bool(name) and name != "Home"
        checks(item + " opens it", opened, f"crumb {app.crumb()}\n{app.dump()}")
        if opened:
            seen[name] = (x, y)
            body = " ".join(app.lines()[1:4])
            tail = name.split()[-1]
            checks(item + f": page is about {name}", tail in body or (name == "Erin" and "Erin" in body), app.dump())
            before, after = ticks(app, 2.0)
            checks(
                item + f": still {name} after 2 ticks ({before} -> {after})",
                opened_name(app) == name and before != after,
                app.dump(),
            )
    home(app)
    checks("mark walk: marks still where they were", len(map_marks(app)) == len(marks), f"{map_marks(app)} vs {marks}")
    checks("mark walk: no contradictions", not app.violations, "\n".join(app.violations))
    checks.done()


def _marked(app: App) -> list[tuple[str, int, int]]:
    cells = []
    for kind, glyph in MAP_GLYPHS.items():
        cells += [(kind, x, y) for x, y in app.reverse_cells(glyph) if 3 <= y < app.rows - 4 and x < app.map_width()]
    return cells


def _mark_line(app: App) -> str:
    return next((ln for ln in app.lines() if "enter opens" in ln), "")


def test_map_mark_and_station_pages_agree(app: App, checks) -> None:  # type: ignore[no-untyped-def]
    home(app)
    steps: dict[str, tuple[str, int, int]] = {}
    labels: list[str] = []
    for i in range(12):
        app.key("n")
        marked = _marked(app)
        line = _mark_line(app)
        checks(f"n #{i + 1}: exactly one mark is highlighted on the map", len(marked) == 1, f"{marked}\n{app.dump()}")
        checks(f"n #{i + 1}: the highlighted mark is named below the map", bool(line), app.dump())
        if line in labels:
            break
        labels.append(line)
        if len(marked) != 1:
            continue
        app.key("enter")
        name = opened_name(app)
        first_row = app.lines()[1]
        nm = re.search(r"\(([^)]+)\)", first_row)
        name_ok = name in line or (nm is not None and nm.group(1)[:14] in line) or name.split()[-1] in line
        checks(f"n #{i + 1}: Enter opens what the map line named ({name})", name_ok, f"label: {line!r}\n{app.dump()}")
        steps[name] = marked[0]
        app.key("escape")
        checks(
            f"n #{i + 1}: after Esc the same mark is still highlighted",
            _marked(app) == marked,
            f"{_marked(app)} vs {marked}",
        )
    ticks(app, 2.0)
    checks("mark highlight sticks after 2 ticks", len(_marked(app)) == 1, app.dump())
    # list -> map: open a station from the list, press m, the map must highlight that station's mark
    for name, cell in steps.items():
        if not name.startswith(("Buoy", "Gauge")):
            continue
        home(app)
        app.key("b")
        rows = [y for y, ln in enumerate(app.lines()) if re.match(rf"^[* ] {re.escape(name)}\b", ln)]
        if not rows:
            checks.skip(f"list -> map for {name}", "not in the near-storm list")
            continue
        app.click(8, rows[0])
        if opened_name(app) != name:
            app.click(8, rows[0])
        app.click_text("map")  # the 'm map' footer cell
        now = _marked(app)
        checks(
            f"list -> map: {name} from the list is highlighted where n found it",
            now == [cell],
            f"highlighted {now}, expected {cell}\n{app.dump()}",
        )
        ticks(app, 2.0)
        checks(f"list -> map: {name} stays highlighted after 2 ticks", _marked(app) == [cell], app.dump())
    home(app)
    checks("agreement walk: no contradictions", not app.violations, "\n".join(app.violations))
    checks.done()
