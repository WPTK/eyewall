"""The dashboard uses the space it is given at the five sizes that matter: nothing runs off the screen, panels hold their
text instead of empty bands, the legend is whole and the storm sits in the middle of its map. Widget regions and map
dots are checked rather than pictures."""

from __future__ import annotations

import pytest
from textual.widgets import TabbedContent

from eyewall.ui.adapt import storm_scene
from eyewall.ui.screens.dashboard import DashboardScreen
from eyewall.ui.widgets.panels import Panel
from tests.ui_support import into_the_storm, replay_app, running, screen_text, scripted_app

STACKED = [(120, 30), (200, 50), (280, 70)]  # 110 columns and up: the panels are stacked beside the map
TABBED = [(100, 50), (80, 24)]
ALL = STACKED + TABBED


def _stack(app) -> dict[str, Panel]:  # type: ignore[no-untyped-def]
    return {p.kind: p for p in app.screen.query_one("#side-stack").query(Panel)}


@pytest.mark.parametrize("size", STACKED, ids=lambda s: f"{s[0]}x{s[1]}")
async def test_the_stacked_column_fits_the_screen(size) -> None:  # type: ignore[no-untyped-def]
    app = replay_app()
    async with running(app, size) as pilot:
        await into_the_storm(pilot)
        side = app.screen.query_one("#side-stack")
        assert side.virtual_size.height <= side.size.height  # the column itself does not scroll
        shown = [p for p in _stack(app).values() if p.display]
        assert {p.kind for p in shown} == {"headline", "ww", "wind", "surge", "buoys"}
        for panel in shown:
            assert panel.region.height >= 4  # a border and at least two lines
            assert panel.region.bottom <= side.region.bottom <= app.size.height - 1  # clear of the status line
        assert sum(p.region.height for p in shown) <= side.size.height
        # The headline gets what is left: its first line is always there, and at 120x30 it is not squeezed below four.
        assert "advisory" in screen_text(app)


@pytest.mark.parametrize("size", TABBED, ids=lambda s: f"{s[0]}x{s[1]}")
async def test_a_tab_panel_fills_its_tab(size) -> None:  # type: ignore[no-untyped-def]
    app = replay_app()
    async with running(app, size) as pilot:
        await into_the_storm(pilot)
        tabs = app.screen.query_one("#side-tabs", TabbedContent)
        pane = tabs.get_pane("tab-headline")
        panel = pane.query_one(Panel)
        assert pane.region.height > 3 and panel.region.height == pane.region.height
        assert panel.region.bottom <= app.size.height - 1
        if size[1] >= 50:  # the headline's text wraps over many lines, and they are all drawn
            assert panel.region.height >= 30
            assert "BEACHGOERS" in screen_text(app)


@pytest.mark.parametrize("size", [(120, 30), (100, 50), (200, 50), (280, 70)], ids=lambda s: f"{s[0]}x{s[1]}")
async def test_the_legend_is_never_cut(size) -> None:  # type: ignore[no-untyped-def]
    app = replay_app()
    async with running(app, size) as pilot:
        await into_the_storm(pilot)
        pane = app.screen.query_one("#map-pane")
        legend = pane.query_one(".legend")
        assert legend.region.bottom == pane.region.bottom - 1  # the legend's rows sit inside the map's border
        shown = " ".join(screen_text(app).splitlines()[legend.region.y : legend.region.bottom])
        assert all(
            name in shown for name in ("storm", "forecast", "buoy", "gauge")
        )  # on the screen, not just in the text


@pytest.mark.parametrize("size", ALL, ids=lambda s: f"{s[0]}x{s[1]}")
async def test_the_map_is_centred_on_the_storm_with_its_rings(size) -> None:  # type: ignore[no-untyped-def]
    app = replay_app()
    async with running(app, size) as pilot:
        await into_the_storm(pilot)
        screen = app.screen
        assert isinstance(screen, DashboardScreen)
        if size[0] < 90:  # the map is hidden below 90 columns until `m` shows it
            await pilot.press("m")
            await pilot.pause()
        view = screen.map_view.viewport
        assert view is not None
        scene = storm_scene(app.store.storms[app.selected])  # type: ignore[index]
        center = scene.center
        assert center is not None
        x, y = view.to_dot(center.lat, center.lon)
        assert 0.15 * view.width < x < 0.85 * view.width  # not in a corner
        assert 0.15 * view.height < y < 0.85 * view.height
        for lat, lon in scene.near_extent():  # the rings and the next 72 hours are all inside
            px, py = view.to_dot(lat, lon)
            assert 0 <= px <= view.width and 0 <= py <= view.height


async def test_f_fits_the_same_view_again() -> None:
    app = replay_app()
    async with running(app, (120, 30)) as pilot:
        await into_the_storm(pilot)
        view = app.screen.map_view
        before = view.viewport
        await pilot.press("plus")
        await pilot.pause()
        assert view.viewport != before
        await pilot.press("f")
        await pilot.pause()
        assert view.viewport == before


@pytest.mark.parametrize("size", ALL, ids=lambda s: f"{s[0]}x{s[1]}")
async def test_an_outlook_area_leaves_out_the_panels_with_nothing_to_show(size) -> None:  # type: ignore[no-untyped-def]
    app = scripted_app()
    async with running(app, size):
        assert app.selected and app.selected.startswith("invest:")
        panels = _stack(app)
        assert panels["headline"].display
        for kind in ("ww", "wind", "surge", "buoys"):
            assert not panels[kind].display
        tabs = app.screen.query_one("#side-tabs", TabbedContent)
        for kind in ("ww", "wind", "surge", "buoys"):
            assert tabs.get_tab(f"tab-{kind}").display is False
        assert "Select a storm" not in screen_text(app)
        if size[0] >= 110:
            assert panels["headline"].region.height <= panels["headline"].body.outer_size.height + 2  # no empty band
