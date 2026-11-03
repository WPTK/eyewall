"""Map and coastline resolution (#152, #155, #156): the tier each quiet-day size draws, the quiet window against the
edge of the vendored data, and the part-cell shore, all read from the real screens and the real build constants."""

from __future__ import annotations

import importlib.util
import sys
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace

import pytest

from eyewall.mapdata import loader
from eyewall.palette import COAST
from eyewall.render import basemap
from eyewall.render.basemap import DETAIL_SWITCH, MID_SWITCH, basemap_canvas, tier_suffix
from eyewall.render.canvas import Canvas
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


def drawn(view: Viewport, suffix: str, monkeypatch) -> Canvas:
    """The base map of a view with the data tier forced, from the real committed files."""
    monkeypatch.setattr(basemap, "tier_suffix", lambda _view: suffix)
    canvas = Canvas(view.cols, view.rows)
    basemap.draw_basemap(canvas, view)
    return canvas


def differing_cells(a: Canvas, b: Canvas, cols: range | None = None) -> tuple[int, int]:
    cols = cols or range(a.cols)
    pairs = [(a.cell(col, row), b.cell(col, row)) for col in cols for row in range(a.rows)]
    return sum(x != y for x, y in pairs), len(pairs)


@pytest.mark.parametrize("name", list(QUIET_SIZES))
async def test_the_1km_map_is_the_full_map_to_within_a_few_cells_at_every_quiet_size(name, monkeypatch) -> None:
    view = (await quiet_views())[name]
    mid, full = drawn(view, "_mid", monkeypatch), drawn(view, "", monkeypatch)
    differing, total = differing_cells(mid, full)
    assert differing <= 0.03 * total, (name, differing, total)  # measured 0.4 to 1.0 percent of the cells


@pytest.mark.parametrize("lon", [-75.0, -80.0])
@pytest.mark.parametrize("deg_per_dot", [0.1, 0.25, 0.5])
def test_a_5_degree_tile_seam_is_no_rougher_than_the_rest_of_the_1km_map(lon, deg_per_dot, monkeypatch) -> None:
    # Land is cut on a 5 degree grid and each tile simplified on its own; -75 and -80 are grid lines.
    view = Viewport(30.0, lon, deg_per_dot, 100, 30)
    mid, full = drawn(view, "_mid", monkeypatch), drawn(view, "", monkeypatch)
    seam_col = view.cols // 2
    seam = range(seam_col - 2, seam_col + 3)
    differing, total = differing_cells(mid, full, seam)
    overall, cells = differing_cells(mid, full)
    assert differing / total <= max(0.05, 3 * overall / cells), (differing, total, overall, cells)


def points_of(name: str, stride: int) -> list[tuple[float, float]]:
    return [point for path in loader.load_layer(name).paths for point in path.points[::stride]]


def segment_index(name: str) -> dict[tuple[int, int], list]:
    """The segments of a layer in a grid of 0.1 degree buckets, each filed in every bucket it passes through."""
    buckets: dict[tuple[int, int], list] = {}
    layer = loader.load_layer(name)
    for path in layer.paths:
        points = list(path.points)
        if layer.rings:
            points.append(points[0])
        for a, b in pairwise(points):
            lat0, lat1 = sorted((a[0], b[0]))
            lon0, lon1 = sorted((a[1], b[1]))
            for i in range(int(lat0 * 10) - 1, int(lat1 * 10) + 2):
                for j in range(int(lon0 * 10) - 1, int(lon1 * 10) + 2):
                    buckets.setdefault((i, j), []).append((a, b))
    return buckets


@pytest.mark.parametrize("stem", ["coast", "land", "lakes"])
def test_the_committed_1km_files_stay_within_the_bar_of_the_full_ones(stem, build) -> None:
    """Every vertex of the full layer lies within MID_TOLERANCE (plus a stored unit of rounding) of the 1 km layer."""
    index = segment_index(stem + "_mid")
    limit = (build.MID_TOLERANCE + 2.0 / build.UNITS) ** 2
    worst = 0.0
    for lat, lon in points_of(stem, 9):
        near = index.get((int(lat * 10), int(lon * 10)), [])
        best = min((build._segment_distance_squared((lat, lon), a, b) for a, b in near), default=float("inf"))
        worst = max(worst, best)
        assert best <= limit, (stem, lat, lon, best**0.5)
    assert worst > 0.0  # the files really are simplified


def test_a_tier_that_will_not_load_falls_back_to_the_next_coarser_one(monkeypatch, caplog) -> None:
    real = basemap.load_layer

    def broken(name: str):
        if name.endswith("_mid"):
            raise ValueError("truncated")
        return real(name)

    monkeypatch.setattr(basemap, "load_layer", broken)
    basemap._indexed.cache_clear()
    basemap.usable_tier.cache_clear()
    try:
        view = Viewport(25.0, -75.0, 0.4, 80, 24)
        assert tier_suffix(view) == "_mid"
        with caplog.at_level("WARNING", logger=basemap.log.name):
            canvas = Canvas(view.cols, view.rows)
            basemap.draw_basemap(canvas, view)  # no exception
        assert any("cannot be read" in record.message for record in caplog.records)
        assert basemap.usable_tier("_mid") == "_lo"
        assert basemap.usable_tier("") == ""  # the full tier is untouched
        assert any(canvas.cell(col, row)[1].bg for col in range(canvas.cols) for row in range(canvas.rows))
    finally:
        basemap._indexed.cache_clear()
        basemap.usable_tier.cache_clear()


def test_with_no_tier_readable_the_error_is_raised(monkeypatch) -> None:
    def broken(name: str):
        raise ValueError("truncated")

    monkeypatch.setattr(basemap, "load_layer", broken)
    basemap._indexed.cache_clear()
    basemap.usable_tier.cache_clear()
    try:
        with pytest.raises(ValueError, match="truncated"):
            basemap.usable_tier("")
    finally:
        basemap._indexed.cache_clear()
        basemap.usable_tier.cache_clear()


def test_the_committed_map_data_is_what_the_build_script_makes(build) -> None:
    """Runs `build_mapdata.py --check` when the Natural Earth sources are cached (`python scripts/build_mapdata.py`
    downloads them into cache/); a clone without them skips it."""
    if not (build.DEFAULT_CACHE / f"{build.PLACES_SOURCE}.geojson").exists():
        pytest.skip("the Natural Earth sources are not cached")
    assert build.main(["--check"]) == 0


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
