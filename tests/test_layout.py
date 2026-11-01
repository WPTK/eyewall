"""Layout facts at the two sizes that matter: 140x45 with a storm selected, and 80x24. Nothing may be pushed out of view,
cut off or clipped; widget regions are checked against the screen rather than pictures."""

from __future__ import annotations

from textual.widgets import DataTable, SelectionList, Switch

from eyewall.ui.screens.detail import TABS
from tests.ui_support import into_the_storm, press, replay_app, running, screen_text, scripted_app, wait_until


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


async def test_a_quiet_main_screen_says_the_outlook_once() -> None:
    app = scripted_app()
    async with running(app, (140, 45)):
        flat = " ".join(screen_text(app).split())
        assert flat.count("NHC is watching 1 area") == 1
        assert "No tropical storms in the Atlantic" in flat
        assert "start the replay" in flat and "YOUR STATIONS" in flat
