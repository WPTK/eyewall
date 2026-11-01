"""The six basic checks from the owner's list, on the built exe: launch, nav key, footer click, row click, resize, quit."""

from __future__ import annotations

from pathlib import Path

from .walk import sig, start_replay


def test_six_checks(artifact: Path, checks) -> None:  # type: ignore[no-untyped-def]
    app = start_replay(artifact)
    try:
        checks("1 launch: waits for text", "Erin" in app.text() and app.crumb() == ["Home"], app.dump())
        # 2 a nav key changes the screen
        before = sig(app)
        app.key("enter")
        checks("2 nav key Enter opens the storm", app.crumb() == ["Home", "Erin"] and sig(app) != before, app.dump())
        app.key("escape")
        checks("2 Esc returns Home", app.crumb() == ["Home"], app.dump())
        # 3 a real click on a footer cell
        cell = next((c for c in app.footer() if c.key == "b"), None)
        checks("3 footer has 'b buoys'", cell is not None, str(app.footer()))
        if cell:
            app.click(cell.mid, cell.y)
            checks("3 click footer 'b' opens Buoys", app.crumb()[-1].startswith("Buoys"), app.dump())
        # 4 click a list row twice
        rows = [y for y, ln in enumerate(app.lines()) if ln.lstrip("* ").startswith("Buoy 4")]
        checks("4 list has rows", len(rows) >= 2, app.dump())
        if rows:
            app.click(10, rows[0])
            app.click(10, rows[0])
            checks("4 two clicks on a row open the station", app.crumb()[-1].startswith("Buoy"), app.dump())
        # 5 resize
        before_crumb = app.crumb()
        app.resize(60, 20)
        checks("5 resize 60x20 keeps the screen", app.crumb() == before_crumb and not app.violations, app.dump())
        app.resize(50, 14)
        checks("5 resize 50x14 explains", "60" in app.text() or "small" in app.text().lower(), app.dump())
        app.resize(120, 30)
        checks("5 resize back recovers", app.crumb() == before_crumb and "? help" in app.text(), app.dump())
        # 6 quit
        for _ in range(6):
            if app.crumb() == ["Home"]:
                break
            app.key("escape")
        app.key("q", settle=False)
        code = app.wait_exit(15)
        checks("6 q exits with code 0", code == 0, f"exit code {code}")
    finally:
        app.close()
    checks("sense: no contradictions through the run", not app.violations, "\n".join(app.violations))
    checks.done()
