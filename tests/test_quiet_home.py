"""The quiet-day Home: a map fitted to the Atlantic and the places NHC is watching, a short footer, a panel that leads
with the chance the map shows. Pure fits first, then the screen."""

from __future__ import annotations

from dataclasses import replace

from eyewall.models.outlook import Outlook, OutlookGis, OutlookSystem
from eyewall.render.hits import Mark
from eyewall.render.projection import Viewport
from eyewall.ui import adapt, nav
from eyewall.ui.chrome import footer_items
from tests.test_main_screen import panel_text
from tests.ui_support import (
    WATCHLIST_BUOYS,
    WATCHLIST_GAUGES,
    ScriptedSource,
    into_the_storm,
    quiet_outlook,
    replay_app,
    running,
    scripted_app,
)

ALL = ("AL", "EP", "CP")
ATLANTIC = (adapt.BASIN_BOUNDS["AL"][0], adapt.BASIN_BOUNDS["AL"][1])


def square(lat: float, lon: float, half: float = 1.0) -> tuple[tuple[float, float], ...]:
    return (
        (lat - half, lon - half),
        (lat - half, lon + half),
        (lat + half, lon + half),
        (lat + half, lon - half),
    )


def test_the_quiet_map_fits_the_atlantic_not_the_hemisphere() -> None:
    assert adapt.quiet_points(ALL) == list(ATLANTIC)
    quiet = Viewport.fit_points(adapt.quiet_points(ALL), 100, 27)
    hemisphere = Viewport.fit_points(adapt.basin_points(()), 100, 27)
    assert quiet.deg_per_dot < 0.6 * hemisphere.deg_per_dot
    assert not quiet.bounds().contains(10.0, -150.0)  # the Pacific is off the map
    assert quiet.bounds().contains(25.0, -80.0)


def test_the_first_enabled_basin_is_the_whole_fit() -> None:
    assert adapt.quiet_points(("EP", "CP")) == list(adapt.BASIN_BOUNDS["EP"])
    assert adapt.quiet_points(("CP",)) == list(adapt.BASIN_BOUNDS["CP"])
    assert adapt.quiet_points(()) == list(ATLANTIC)


def atlantic_only() -> Outlook:
    system = OutlookSystem("Atlantic", "1", 0, "low", 50, "medium", polygons=(square(15.0, -45.0, 2.0),))
    return replace(quiet_outlook(), gis=OutlookGis(None, (system,)))


async def test_the_quiet_screen_is_the_atlantic_at_half_a_degree_a_dot_whatever_the_outlook() -> None:
    far = OutlookSystem("Pacific", "1", 0, "low", 40, "medium", polygons=(square(12.0, -150.0, 2.0),))
    for outlook in (atlantic_only(), replace(quiet_outlook(), gis=OutlookGis(None, (far,)))):
        app = scripted_app(ScriptedSource(outlook))
        async with running(app, (120, 30)):
            view = app.screen.map_view.viewport
            assert view is not None and view.deg_per_dot <= 0.5
            assert not view.bounds().contains(12.0, -150.0) and view.bounds().contains(25.0, -80.0)


async def test_an_area_in_another_basin_is_panel_text_not_a_wider_map() -> None:
    far = OutlookSystem("Pacific", "1", 0, "low", 40, "medium", polygons=(square(12.0, -150.0, 2.0),))
    app = scripted_app(ScriptedSource(replace(quiet_outlook(), gis=OutlookGis(None, (far,)))))
    async with running(app, (120, 30)):
        assert "1 area in the Central Pacific: a 40% chance" in " ".join(panel_text(app).split())


async def test_every_followed_station_inside_the_quiet_view_has_a_mark() -> None:
    app = scripted_app(ScriptedSource(stations=WATCHLIST_BUOYS, gauges=WATCHLIST_GAUGES))
    async with running(app, (120, 30)):
        view = app.screen.map_view.viewport
        assert view is not None
        marks = {mark for mark, _ in app.screen.map_view.hits.drawn}
        followed = [(Mark("buoy", s.id), s.lat, s.lon) for s in WATCHLIST_BUOYS]
        followed += [(Mark("gauge", g.id), g.lat, g.lon) for g in WATCHLIST_GAUGES]
        inside = [m for m, lat, lon in followed if view.bounds().contains(lat, lon)]
        assert len(inside) == 4 and set(inside) <= marks


async def test_the_quiet_footer_keeps_to_what_there_is_to_do() -> None:
    app = scripted_app()
    async with running(app, (120, 30)):
        items, pinned = footer_items(app.screen)
        assert [i.key for i in items] == ["enter", "b", "R"]
        assert [p.key for p in pinned] == ["?", "^p", "q"]
        # the keys that are left out of the footer are still in the key table, so help and the menu list them
        left_out = {"zoom_in", "screen.fit", "screen.center", "screen.layers", "text"}
        assert left_out <= {k.action for k in nav.KEYS if k.busy}


async def test_a_storm_keeps_the_whole_footer() -> None:
    app = replay_app()
    async with running(app, (120, 30)) as pilot:
        await into_the_storm(pilot)
        items, _ = footer_items(app.screen)
        assert {"+/-", "f", "c", "l", "enter", "b", "t"} <= {i.key for i in items}


async def test_the_panel_has_quiet_headings_and_leads_with_the_seven_day_chance() -> None:
    app = scripted_app(ScriptedSource(atlantic_only()))
    async with running(app, (120, 30)):
        text = panel_text(app)
        assert "Areas NHC is watching" in text and "See it with a storm" in text and "Your stations" in text
        assert not any(word.isupper() and len(word) > 3 for word in text.split())
        assert "a 50% chance it forms within 7 days, and 0% within 2 days" in text
        side = app.screen.query_one("#side")
        heads = [line for line in side.lines if line.text.plain.startswith(("Areas", "See it", "Your"))]
        assert len(heads) == 3 and all(line.text.style == "dim" for line in heads)
