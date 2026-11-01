"""Layout facts at the two sizes that matter: 140x45 with a storm selected, and 80x24. Nothing may be pushed out of view,
cut off or clipped; widget regions are checked against the screen rather than pictures."""

from __future__ import annotations

from textual.widgets import DataTable, SelectionList, Switch, TabbedContent

from eyewall.ui.screens.dashboard import DashboardScreen
from eyewall.ui.screens.detail import TABS
from eyewall.ui.widgets.panels import Panel
from tests.ui_support import into_the_storm, press, replay_app, running, screen_text, scripted_app, settle, wait_until


def _stacked(app) -> dict[str, Panel]:  # type: ignore[no-untyped-def]
    return {p.kind: p for p in app.screen.query_one("#side-stack").query(Panel)}


async def test_the_right_column_fits_at_140x45() -> None:
    app = replay_app()
    async with running(app, (140, 45)) as pilot:
        await into_the_storm(pilot)
        side = app.screen.query_one("#side-stack")
        panels = _stacked(app)
        assert set(panels) == {"headline", "ww", "wind", "surge", "buoys"}
        assert side.virtual_size.height <= side.size.height  # the column itself does not scroll
        for panel in panels.values():
            assert panel.display
            region = panel.region
            assert region.height >= 3
            assert region.bottom <= side.region.bottom <= app.size.height
        wind = panels["wind"]
        assert wind.virtual_size.height <= wind.size.height  # Wind shows everything, down to "Most likely"
        text = screen_text(app)
        assert "Most likely" in text and "Nearest buoys" in text and "Storm surge" in text


async def test_full_map_refits_to_the_wider_pane() -> None:
    app = replay_app()
    async with running(app, (140, 45)) as pilot:
        await into_the_storm(pilot)
        view = app.screen.map_view
        before = view.size.width
        await press(pilot, "M")
        assert view.size.width > before
        assert view.viewport is not None and view.viewport.cols == view.size.width
        assert view._strips is not None and view._strips[0].cell_length == view.size.width
        region = view.region
        lines = screen_text(app).splitlines()
        right_part = "".join(line[region.x + before + 2 : region.right] for line in lines[region.y : region.bottom])
        assert right_part.strip()  # something is drawn in the columns the old width did not have


async def test_a_quiet_day_has_no_empty_surge_panel() -> None:
    app = scripted_app()
    async with running(app, (140, 45)) as pilot:
        panels = _stacked(app)
        assert not panels["surge"].display
        assert "Storm surge" not in screen_text(app)
        tabs = app.screen.query_one("#side-tabs", TabbedContent)
        assert tabs.get_tab("tab-surge").display is False
    app = replay_app()
    async with running(app, (80, 24)) as pilot:
        await into_the_storm(pilot)
        tabs = app.screen.query_one("#side-tabs", TabbedContent)
        assert tabs.get_tab("tab-surge").display is True


async def test_the_storm_list_note_stays_on_one_line_at_80x24() -> None:
    app = replay_app()
    async with running(app, (80, 24)) as pilot:
        await into_the_storm(pilot)
        assert " Pacific: none" in screen_text(app)


async def test_every_detail_tab_is_visible_at_80x24() -> None:
    app = replay_app()
    async with running(app, (80, 24)) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "enter")
        bar = screen_text(app).splitlines()[2]  # under the top bar and the storm line
        for _tab_id, title in TABS:
            assert title in bar
        assert len(bar) <= 80


async def test_the_alert_log_wraps_instead_of_scrolling_sideways() -> None:
    app = replay_app()
    async with running(app, (80, 24)) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "A")
        table = app.screen.query_one("#alert-table", DataTable)
        assert not table.show_horizontal_scrollbar
        assert table.virtual_size.width <= table.size.width
        flat = " ".join(screen_text(app).split())
        assert "Chincoteague, Virginia, including Pamlico and Albemarle sounds." in flat


async def test_settings_scrolls_to_its_last_switch_at_80x24() -> None:
    app = replay_app()
    async with running(app, (80, 24)) as pilot:
        await press(pilot, "S")
        last = app.screen.query_one("#alerts-bell", Switch)
        last.focus()  # focusing scrolls it into view with an animation, which a slow runner finishes late
        screen = app.screen.region
        await wait_until(pilot, lambda: last.region.height > 0 and screen.contains_region(last.region))


async def test_scrollbars_are_one_column_wide() -> None:
    app = replay_app()
    async with running(app, (140, 45)) as pilot:
        await into_the_storm(pilot)
        panel = _stacked(app)["headline"]
        assert panel.virtual_size.height > panel.size.height  # it does scroll
        assert panel.scrollbar_size_vertical == 1


async def test_unchecked_layers_are_readable() -> None:
    app = replay_app()
    async with running(app, (100, 40)) as pilot:
        await press(pilot, "l")
        menu = app.screen.query_one("#layer-list", SelectionList)
        style = menu.get_component_rich_style("selection-list--button")
        assert style.color is not None and style.bgcolor is not None
        fg, bg = style.color.get_truecolor(), style.bgcolor.get_truecolor()

        def luminance(c) -> float:  # type: ignore[no-untyped-def]
            return 0.2126 * c.red + 0.7152 * c.green + 0.0722 * c.blue

        assert abs(luminance(fg) - luminance(bg)) > 60


async def test_the_quiet_outlook_shows_each_area_once() -> None:
    app = scripted_app()
    async with running(app, (140, 45)) as pilot:
        await press(pilot, "O")
        flat = " ".join(screen_text(app).split())
        assert flat.count("A broad area of low pressure") == 1
        assert flat.count("Area 1: Well Southeast") == 1
        assert "For the North Atlantic...Caribbean Sea and the Gulf of America" in flat
        assert isinstance(app.screen_stack[0], DashboardScreen)


async def test_a_repeated_area_is_skipped_but_its_text_keeps_its_header() -> None:
    app = scripted_app()
    async with running(app, (140, 45)) as pilot:
        await press(pilot, "O")
        flat = " ".join(screen_text(app).split())
        assert "For the central North Pacific...between 140W and 180W" in flat
        assert flat.count("A broad area of low pressure") == 1


async def test_a_text_outside_the_basin_view_does_not_hide_areas() -> None:
    app = scripted_app()
    async with running(app, (140, 45)) as pilot:
        app.basin_filter = "CP"
        await press(pilot, "O")
        flat = " ".join(screen_text(app).split())
        assert flat.count("A broad area of low pressure") == 1
        assert "Area 1: Well Southeast" in flat


async def test_hiding_the_active_surge_tab_falls_back_to_another_tab(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from rich.text import Text

    app = replay_app()
    async with running(app, (80, 24)) as pilot:
        await into_the_storm(pilot)
        tabs = app.screen.query_one("#side-tabs", TabbedContent)
        tabs.active = "tab-surge"
        await settle(pilot)
        monkeypatch.setattr("eyewall.ui.format.surge_panel", lambda store, selected: Text("\n "))
        app.screen.refresh_selection()
        await settle(pilot)
        assert tabs.get_tab("tab-surge").display is False
        assert tabs.active != "tab-surge"
        assert tabs.active
        assert not _stacked(app)["surge"].display
