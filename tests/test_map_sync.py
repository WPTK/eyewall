"""The map and the list agree on the selected storm; the full-screen map and outlook areas have a mouse route."""

from __future__ import annotations

from dataclasses import replace

from textual.pilot import Pilot

from eyewall.render.hits import Mark
from eyewall.state.store import StormState
from eyewall.ui.chrome import FooterBar
from eyewall.ui.screens.main import MainScreen
from eyewall.ui.screens.storm import StormScreen
from eyewall.ui.widgets.map_view import MapView
from tests.test_map_marks import reversed_columns
from tests.ui_support import into_the_storm, press, replay_app, running, screen_text, scripted_app, settle


def underlined_columns(view: MapView) -> list[tuple[int, int]]:
    """The cells drawn bold and underlined (the selected storm), as (column, row)."""
    out = []
    for row in range(view.size.height):
        col = 0
        for seg in view.render_line(row):
            if seg.style is not None and seg.style.underline and seg.style.bold:
                out.extend((col + i, row) for i in range(len(seg.text)))
            col += len(seg.text)
    return out


async def two_storms(pilot: Pilot[None]) -> tuple[MainScreen, MapView, Mark, Mark]:
    """The replay storm and a copy of it far to the east, so each has a mark of its own."""
    app = pilot.app
    await into_the_storm(pilot)
    state = next(iter(app.store.storms.values()))
    other = replace(state.storm, id="al092025", name="FERNANDA", lat=state.storm.lat + 3.0, lon=state.storm.lon + 12.0)
    app.store.storms[other.id] = StormState(other, state.advisories)
    screen = app.screen
    assert isinstance(screen, MainScreen)
    screen.refresh_data()
    await settle(pilot)
    view = screen.map_view
    return screen, view, Mark("storm", state.storm.id), Mark("storm", other.id)


async def test_clicking_a_storm_mark_selects_its_card_and_the_next_click_opens_it() -> None:
    async with running(replay_app(), (140, 45)) as pilot:
        _, view, first, second = await two_storms(pilot)
        assert pilot.app.selected == first.id
        col, row = view.hits.cell_of(second) or (-1, -1)
        await pilot.click(MapView, offset=(col, row))
        await settle(pilot)
        assert isinstance(pilot.app.screen, MainScreen)  # the click selected; it did not leave the screen
        assert pilot.app.selected == second.id
        assert view.selected_mark == second and (col, row) in underlined_columns(view)
        assert (col, row) not in reversed_columns(view)  # the selection is not the focus ring
        await pilot.click(MapView, offset=(col, row))
        await settle(pilot)
        assert isinstance(pilot.app.screen, StormScreen) and pilot.app.screen.storm_id == second.id


async def test_selecting_a_storm_in_the_list_highlights_its_mark_and_it_survives_a_refresh() -> None:
    async with running(replay_app(), (140, 45)) as pilot:
        screen, view, first, second = await two_storms(pilot)
        assert view.selected_mark == first
        await press(pilot, "j")
        assert pilot.app.selected == second.id and view.selected_mark == second
        assert view.hits.cell_of(second) in underlined_columns(view)
        screen.refresh_data()
        await settle(pilot)
        assert view.selected_mark == second and view.hits.cell_of(second) in underlined_columns(view)


async def test_one_storm_has_no_selected_mark_and_a_click_opens_it() -> None:
    async with running(replay_app(), (140, 45)) as pilot:
        await into_the_storm(pilot)
        view = pilot.app.screen.query_one(MapView)
        assert view.selected_mark is None
        col, row = view.hits.cell_of(Mark("storm", pilot.app.selected)) or (-1, -1)
        await pilot.click(MapView, offset=(col, row))
        await settle(pilot)
        assert isinstance(pilot.app.screen, StormScreen)


# ---- the full-screen map -----------------------------------------------------------------------------------------


async def test_the_full_screen_map_has_a_footer_cell_and_a_menu_entry() -> None:
    app = replay_app()
    async with running(app, (140, 45)) as pilot:
        await into_the_storm(pilot)
        bar = app.screen.query_one(FooterBar)
        target = next(t for t in bar.row.targets if t.action == "key:M")
        await pilot.click(FooterBar, offset=(target.start + 1, 0))
        await settle(pilot)
        assert app.screen.has_class("full-map")
        await press(pilot, "escape", "ctrl+p")
        await pilot.press(*"full")
        await pilot.pause(0.6)
        assert "Full-screen map" in "\n".join(s.text for s in app.screen._compositor.render_strips())
        await pilot.press("enter")
        await settle(pilot)
        assert app.screen.has_class("full-map")


# ---- outlook areas outside the view ------------------------------------------------------------------------------


async def test_w_centres_the_map_on_an_outlook_area_in_another_basin() -> None:
    app = scripted_app()
    async with running(app, (120, 40)) as pilot:
        view = app.screen.query_one(MapView)
        before = view.viewport
        assert before is not None and before.center_lon > -110  # the Atlantic view
        await press(pilot, "w")
        after = view.viewport
        assert after is not None and after.center_lon < -135  # the Central Pacific area, which the Atlantic view omits
        assert not view.auto_fit


async def test_w_is_offered_only_with_an_area_to_go_to() -> None:
    app = replay_app()
    async with running(app, (120, 40)):
        screen = app.screen
        assert isinstance(screen, MainScreen)
        app.store.outlook = None
        assert screen.check_action("area", ()) is False


async def test_m_on_a_station_page_highlights_that_stations_mark_on_the_map() -> None:
    app = replay_app()
    async with running(app, (140, 45)) as pilot:
        await into_the_storm(pilot)
        view = app.screen.query_one(MapView)
        buoy = next(m for m in view.hits.order if m.kind == "buoy")
        app.open_station("ndbc", buoy.id)
        await settle(pilot)
        await press(pilot, "m")
        await settle(pilot)
        assert isinstance(app.screen, MainScreen)
        assert app.screen.map_view.focused_mark == buoy
        assert app.screen.map_view.hits.cell_of(buoy) in reversed_columns(app.screen.map_view)


async def test_a_storm_the_basin_filter_hides_opens_on_the_first_click() -> None:
    async with running(replay_app(), (140, 45)) as pilot:
        screen, view, _, _ = await two_storms(pilot)
        state = next(iter(pilot.app.store.storms.values()))
        lat, lon = view.viewport.to_geo(*view._dot_of(10, 5))  # type: ignore[union-attr]
        pacific = replace(state.storm, id="ep092025", name="GIL", lat=lat, lon=lon)
        pilot.app.store.storms[pacific.id] = StormState(pacific, state.advisories)
        pilot.app.basin_filter = "AL"  # the Pacific storm is on the map but not in the list
        screen.refresh_data()
        await settle(pilot)
        mark = Mark("storm", pacific.id)
        assert mark not in {Mark("storm", s.storm.id) for s in screen.states} and mark.id not in view.selectable
        col, row = view.hits.cell_of(mark) or (-1, -1)
        assert col >= 0, "the unlisted storm is drawn"
        await pilot.click(MapView, offset=(col, row))
        await settle(pilot)
        assert isinstance(pilot.app.screen, StormScreen) and pilot.app.screen.storm_id == pacific.id


async def test_going_from_two_storms_to_one_clears_the_highlight() -> None:
    async with running(replay_app(), (140, 45)) as pilot:
        screen, view, first, second = await two_storms(pilot)
        assert view.selected_mark == first
        del pilot.app.store.storms[second.id]
        screen.refresh_data()
        await settle(pilot)
        assert view.selected_mark is None and not view.selectable


async def test_a_click_on_overlapping_marks_asks_which_and_then_selects() -> None:
    async with running(replay_app(), (140, 45)) as pilot:
        screen, view, first, second = await two_storms(pilot)
        state = pilot.app.store.storms[second.id]
        first_state = pilot.app.store.storms[first.id]
        pilot.app.store.storms[second.id] = StormState(
            replace(state.storm, lat=first_state.storm.lat, lon=first_state.storm.lon), state.advisories
        )
        screen.refresh_data()
        await settle(pilot)
        col, row = view.hits.cell_of(first) or (-1, -1)
        await pilot.click(MapView, offset=(col, row))
        await settle(pilot)
        assert type(pilot.app.screen).__name__ == "MarkChooser"
        await press(pilot, "down", "enter")
        assert isinstance(pilot.app.screen, MainScreen) and view.selected_mark is not None


async def test_w_wraps_around_and_follows_the_outlook_it_is_given() -> None:
    app = scripted_app()
    async with running(app, (120, 40)) as pilot:
        screen = app.screen
        assert isinstance(screen, MainScreen)
        areas = screen._areas()
        assert areas
        centres = []
        for _ in range(len(areas) + 1):
            await press(pilot, "w")
            centres.append(screen.map_view.viewport.center_lon)  # type: ignore[union-attr]
        assert centres[0] == centres[-1]  # the round trip came back to the first area
        app.store.outlook = None
        assert screen.check_action("area", ()) is False


async def test_w_is_in_the_menu_when_there_is_an_area_and_never_in_the_footer() -> None:
    app = scripted_app()
    async with running(app, (120, 40)) as pilot:
        assert "next area" not in bottom_text(app)
        await press(pilot, "ctrl+p")
        await pilot.pause(0.6)
        assert "Centre the map on an outlook area" in screen_text(app)


def bottom_text(app: object) -> str:
    return screen_text(app).splitlines()[-1]  # type: ignore[arg-type]


def test_an_outlook_area_across_the_antimeridian_is_centred_in_its_middle() -> None:
    from eyewall.models.outlook import Outlook, OutlookGis, OutlookSystem
    from eyewall.ui.adapt import outlook_centres

    ring = ((10.0, 175.0), (10.0, -175.0), (20.0, -175.0), (20.0, 175.0), (12.0, 179.0))  # a boomerang's corner points
    system = OutlookSystem("Pacific", "1", 10, "low", 40, "medium", polygons=(ring,))
    ((label, (lat, lon)),) = outlook_centres(Outlook((), OutlookGis(None, (system,)), ()))
    assert label == "Pacific area 1" and lat == 15.0 and abs(abs(lon) - 180.0) < 1e-9
