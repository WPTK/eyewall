"""Map and coastline resolution (#152, #155, #156): the tier each quiet-day size draws, the quiet window against the
edge of the vendored data, and the part-cell shore, all read from the real screens and the real build constants."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from eyewall.mapdata import loader
from eyewall.palette import COAST
from eyewall.render.basemap import DETAIL_SWITCH, MID_SWITCH, basemap_canvas, tier_suffix
from eyewall.render.projection import Viewport
from eyewall.ui import adapt
from tests.test_quiet_home import square
from tests.test_render_basemap import QUIET_SIZES
from tests.ui_support import ScriptedSource, quiet_outlook, running, scripted_app

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "build_mapdata.py"
TERMINALS = {"80x24": (80, 24), "100x40": (100, 40), "120x30": (120, 30), "200x50": (200, 50)}
LINECAST_BAR_DEG = 0.009  # about 1 km: what linecast draws, and the owner's bar for the coastline (#152)


@pytest.fixture(scope="module")
def build():
    spec = importlib.util.spec_from_file_location("build_mapdata", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_mapdata"] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop("build_mapdata", None)


async def quiet_views() -> dict[str, Viewport]:
    views = {}
    for name, size in TERMINALS.items():
        app = scripted_app(ScriptedSource(quiet_outlook()))
        async with running(app, size):
            views[name] = app.screen.map_view.viewport
    return views


async def test_the_quiet_map_sizes_the_tests_assume_are_the_screens_sizes() -> None:
    views = await quiet_views()
    assert {name: (v.cols, v.rows) for name, v in views.items()} == QUIET_SIZES


def tolerance_drawn(build, view: Viewport) -> float:
    """How far the data tier a view draws may sit from the true line, from the build script's own constants."""
    return {"": build.FULL_TOLERANCE, "_mid": build.MID_TOLERANCE, "_lo": build.LO_TOLERANCE}[tier_suffix(view)]


async def test_the_tier_each_quiet_size_draws_is_a_small_part_of_a_dot(build) -> None:
    for name, view in (await quiet_views()).items():
        tolerance = tolerance_drawn(build, view)
        assert view.deg_per_dot <= 0.5, name
        assert tolerance <= 0.1 * view.deg_per_dot, name


async def test_every_quiet_size_meets_the_linecast_bar(build) -> None:
    for name, view in (await quiet_views()).items():
        assert tolerance_drawn(build, view) <= LINECAST_BAR_DEG, name


def test_the_linecast_bar_holds_for_every_zoom_up_to_a_quiet_map(build) -> None:
    for step in range(1, 51):
        view = Viewport(25.0, -60.0, step / 100.0, 100, 30)  # 0.01 to 0.5 degrees a dot
        assert tolerance_drawn(build, view) <= LINECAST_BAR_DEG, view.deg_per_dot


def test_the_tiers_are_in_order_and_the_bar_tier_reaches_the_coarsest_quiet_map(build) -> None:
    assert build.FULL_TOLERANCE < build.MID_TOLERANCE <= LINECAST_BAR_DEG < build.LO_TOLERANCE
    assert DETAIL_SWITCH < MID_SWITCH and MID_SWITCH > adapt.QUIET_MAX_DEG_PER_DOT


def test_each_coarser_tier_is_fewer_vertices() -> None:
    for name in ("coast", "land", "lakes"):
        counts = [loader.load_layer(name + suffix).vertex_count for suffix in ("", "_mid", "_lo")]
        assert counts[0] > counts[1] > counts[2], name


def test_the_thinned_1km_coast_keeps_every_island_and_the_shore_within_a_dot() -> None:
    view = Viewport(25.0, -75.0, 0.4, 120, 40)
    thin = basemap_canvas(view)
    assert tier_suffix(view) == "_mid"
    for name, lat, lon in [
        ("Florida", 27.0, -81.5),
        ("Cuba", 21.8, -79.0),
        ("Hispaniola", 19.0, -71.0),
        ("Bahamas", 24.5, -76.0),
    ]:
        x, y = view.dot_at(lat, lon)
        assert any(
            thin.dot(x + dx, y + dy) or thin.cell((x + dx) // 2, (y + dy) // 4)[1].bg
            for dx in range(-6, 7)
            for dy in range(-6, 7)
        ), name


def test_the_loaders_cut_lines_are_the_build_scripts(build) -> None:
    assert loader.DATA_SOUTH == build.SOUTH and loader.DATA_NORTH == build.NORTH
    assert build.BOXES[1][2] == loader.DATA_EAST


def test_the_vendored_data_really_stops_at_the_cut_lines() -> None:
    lats = [lat for name in ("land", "land_lo") for path in loader.load_layer(name).paths for lat, _ in path.points]
    assert min(lats) == pytest.approx(loader.DATA_SOUTH, abs=0.01)
    assert max(lats) <= loader.DATA_NORTH + 0.01


@pytest.mark.parametrize("basin", ["AL", "EP", "CP"])
async def test_no_flat_coast_line_is_drawn_where_the_data_is_cut(basin) -> None:
    for name, (cols, rows) in QUIET_SIZES.items():
        view = Viewport.fit_points(
            adapt.BASIN_BOUNDS[basin], cols, rows, max_deg_per_dot=0.5, focus=adapt.BASIN_FOCUS[basin]
        )
        south_y = view.to_dot(loader.DATA_SOUTH, view.center_lon)[1]
        if not 0 <= south_y < view.height:
            continue  # the cut is off this map
        canvas = basemap_canvas(view)
        row = int(south_y) // view.dots_y
        coast_cells = sum(canvas.cell(col, row)[1].fg == COAST for col in range(canvas.cols))
        assert coast_cells < canvas.cols // 4, (basin, name)  # a real coast crossing the cut, not a line along it


def outlook_at(lat: float, lon: float):
    from dataclasses import replace

    from eyewall.models.outlook import OutlookGis, OutlookSystem

    system = OutlookSystem("Atlantic", "1", 0, "low", 50, "medium", polygons=(square(lat, lon, 2.0),))
    return replace(quiet_outlook(), gis=OutlookGis(None, (system,)))


def storm_at(lat: float, lon: float):
    return SimpleNamespace(storm=SimpleNamespace(lat=lat, lon=lon))


def test_the_focus_is_the_basins_busy_spot_with_nothing_to_look_at() -> None:
    assert adapt.quiet_focus(("AL",)) == adapt.BASIN_FOCUS["AL"]
    store = SimpleNamespace(storms={}, outlook=None)
    assert adapt.quiet_focus(("AL",), store) == adapt.BASIN_FOCUS["AL"]  # type: ignore[arg-type]


def test_the_focus_follows_an_outlook_area_off_the_cape_verde_islands() -> None:
    store = SimpleNamespace(storms={}, outlook=outlook_at(12.0, -25.0))
    assert adapt.quiet_focus(("AL",), store) == pytest.approx((12.0, -25.0), abs=0.5)  # type: ignore[arg-type]


def test_the_focus_is_the_middle_of_storms_and_areas_inside_the_basin() -> None:
    store = SimpleNamespace(
        storms={"a": storm_at(20.0, -80.0), "b": storm_at(30.0, -60.0), "pacific": storm_at(12.0, -150.0)},
        outlook=None,
    )
    assert adapt.quiet_focus(("AL",), store) == (25.0, -70.0)  # type: ignore[arg-type]


def test_a_cape_verde_area_is_on_the_quiet_map_at_100x40() -> None:
    focus = adapt.quiet_focus(("AL",), SimpleNamespace(storms={}, outlook=outlook_at(12.0, -25.0)))  # type: ignore[arg-type]
    view = Viewport.fit_points(adapt.BASIN_BOUNDS["AL"], 66, 36, max_deg_per_dot=0.5, focus=focus)
    assert view.bounds().contains(12.0, -25.0) and view.deg_per_dot == 0.5


@pytest.mark.parametrize("basin", ["EP", "CP"])
def test_other_basins_slide_to_stay_inside_their_box(basin) -> None:
    box = adapt.BASIN_BOUNDS[basin]
    near_west = Viewport.fit_points(box, 40, 20, max_deg_per_dot=0.25, focus=(box[0][0] + 1, box[0][1]))
    near_east = Viewport.fit_points(box, 40, 20, max_deg_per_dot=0.25, focus=(box[1][0] - 1, box[1][1]))
    assert near_west.deg_per_dot == near_east.deg_per_dot == 0.25
    assert near_west.bounds().contains(box[0][0] + 1, box[0][1] + 1)
    assert near_east.bounds().contains(box[1][0] - 1, box[1][1] - 1)
    assert near_west.center_lon != near_east.center_lon


def test_the_central_pacific_box_across_the_antimeridian_slides_to_its_ends() -> None:
    box = ((4.0, 170.0), (30.0, -150.0))  # 40 degrees wide, across 180
    west = Viewport.fit_points(box, 30, 30, max_deg_per_dot=0.25, focus=(15.0, 172.0))
    east = Viewport.fit_points(box, 30, 30, max_deg_per_dot=0.25, focus=(15.0, -152.0))
    assert west.bounds().contains(15.0, 172.0) and east.bounds().contains(15.0, -152.0)
    assert not west.bounds().contains(15.0, -152.0) and not east.bounds().contains(15.0, 172.0)
    assert west.center_lon > 0 > east.center_lon or abs(west.center_lon) > 160  # each stays on its own side of 180


def test_a_window_taller_than_the_box_is_centered_on_it() -> None:
    box = [(10.0, -60.0), (20.0, -20.0)]
    view = Viewport.fit_points(box, 60, 60, max_deg_per_dot=0.1, focus=(11.0, -58.0))
    assert view.center_lat == pytest.approx(15.0)
