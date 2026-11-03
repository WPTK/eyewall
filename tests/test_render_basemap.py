"""The base map: detail levels, layer switches, caching and golden renderings."""

import pytest

from eyewall.render.basemap import (
    DETAIL_SWITCH,
    BasemapStyle,
    basemap_canvas,
    draw_basemap,
    ensure_matches,
    is_detailed,
)
from eyewall.render.canvas import Canvas, Mode
from eyewall.render.projection import Viewport
from tests.render_support import assert_golden

# The Gulf of Mexico and the Caribbean in a 120 by 40 cell terminal.
GULF = Viewport(20.0, -80.5, 0.16, 120, 40)
# The same region for the ASCII mode, whose cells hold 1 by 2 dots, so each dot spans more ground.
GULF_ASCII = Viewport(20.0, -80.0, 0.29, 120, 40, dots_x=1, dots_y=2)
# The Central Pacific across the antimeridian: Hawaii, Midway and the Marshall Islands.
PACIFIC = Viewport(20.0, -178.0, 0.2, 120, 40)


def count_dots(canvas: Canvas) -> int:
    return sum(canvas.dot(x, y) for y in range(canvas.height) for x in range(canvas.width))


def colors(canvas: Canvas) -> set[str | None]:
    """Every foreground and background color on the canvas."""
    cells = [canvas.cell(c, r)[1] for r in range(canvas.rows) for c in range(canvas.cols)]
    return {s.fg for s in cells} | {s.bg for s in cells}


def test_detail_follows_the_zoom():
    assert is_detailed(GULF)
    assert is_detailed(Viewport(25.0, -75.0, DETAIL_SWITCH - 0.01, 100, 30))
    assert not is_detailed(Viewport(25.0, -75.0, DETAIL_SWITCH, 100, 30))
    assert not is_detailed(Viewport(30.0, -150.0, 1.0, 120, 40))  # the whole Pacific basin
    assert is_detailed(Viewport(25.0, -60.0, 0.25, 120, 40))  # a regional view is still the 10 m data


def test_each_layer_can_be_switched_off():
    style = BasemapStyle(land="#111111", coast="#222222", border="#333333", state="#444444")
    everything = basemap_canvas(GULF, style=style)
    assert colors(everything) >= {"#111111", "#222222", "#333333"}
    no_land = basemap_canvas(GULF, land=False, style=style)
    assert "#111111" not in colors(no_land)
    no_coast = basemap_canvas(GULF, coast=False, style=style)
    assert "#222222" not in colors(no_coast)
    no_borders = basemap_canvas(GULF, borders=False, style=style)
    assert not colors(no_borders) & {"#333333", "#444444"}
    nothing = basemap_canvas(GULF, land=False, coast=False, borders=False)
    assert count_dots(nothing) == 0


def test_land_is_a_flat_background_and_coast_is_drawn_over_it():
    style = BasemapStyle(land="#111111", coast="#222222")
    canvas = Canvas(GULF.cols, GULF.rows)
    draw_basemap(canvas, GULF, borders=False, style=style)
    x, y = GULF.dot_at(19.5, -89.0)  # inland on the Yucatan
    assert not canvas.dot(x, y)  # no fill dots: the land is a tint, so it cannot speckle
    assert canvas.cell(x // 2, y // 4)[1].bg == "#111111"
    sea = GULF.dot_at(25.0, -90.0)  # open Gulf
    assert canvas.cell(sea[0] // 2, sea[1] // 4)[1].bg is None
    cape = GULF.dot_at(28.46, -80.53)  # Cape Canaveral: land meets sea, and the coast line sits on the land
    assert canvas.cell(cape[0] // 2, cape[1] // 4)[1].fg == "#222222"


def test_state_lines_appear_only_when_zoomed_in():
    style = BasemapStyle(state="#abcdef")
    near = basemap_canvas(Viewport(33.0, -85.0, 0.1, 100, 30), style=style)
    far = basemap_canvas(Viewport(33.0, -85.0, 0.6, 100, 30), style=style)
    assert "#abcdef" in colors(near)
    assert "#abcdef" not in colors(far)


def test_the_canvas_must_match_the_viewport():
    with pytest.raises(ValueError, match="viewport is 120x40"):
        ensure_matches(Canvas(100, 40), GULF)
    with pytest.raises(ValueError):
        ensure_matches(Canvas(120, 40, Mode.HALF), GULF)
    with pytest.raises(ValueError):
        draw_basemap(Canvas(10, 10), GULF)
    ensure_matches(Canvas(120, 40), GULF)


def test_the_raster_is_cached_but_every_caller_gets_its_own_canvas():
    first = basemap_canvas(GULF)
    first.text(0, 0, "scribble", "#ffffff")
    second = basemap_canvas(GULF)
    assert second is not first
    assert "scribble" not in second.to_text()
    assert second.to_text() == basemap_canvas(GULF).to_text()
    other = basemap_canvas(GULF.pan_dots(40, 0))
    assert other.to_text() != second.to_text()


def test_the_gulf_and_caribbean_are_recognisable():
    canvas = basemap_canvas(GULF)
    # The coast turns up where the geography says it should, and the open water between stays empty.
    for name, lat, lon in [
        ("Florida Keys", 24.9, -80.9),
        ("Cabo Catoche", 21.6, -87.05),
        ("Cape San Antonio", 21.87, -84.95),
        ("Mississippi delta", 29.1, -89.2),
        ("Puerto Rico", 18.3, -66.4),
        ("Colombia", 11.0, -74.8),
    ]:
        x, y = GULF.dot_at(lat, lon)
        assert any(canvas.dot(x + dx, y + dy) for dx in range(-4, 5) for dy in range(-4, 5)), name
    for lat, lon in [(25.0, -90.0), (15.0, -75.0), (13.0, -68.0)]:
        x, y = GULF.dot_at(lat, lon)
        assert not any(canvas.dot(x + dx, y + dy) for dx in range(-3, 4) for dy in range(-3, 4)), (lat, lon)


def test_gulf_and_caribbean_golden():
    assert_golden("gulf_caribbean_120x40.txt", basemap_canvas(GULF).to_text())


@pytest.mark.parametrize("mode", [Mode.HALF, Mode.ASCII])
def test_gulf_golden_in_the_simpler_modes(mode):
    text = basemap_canvas(GULF_ASCII, mode).to_text()
    if mode is Mode.ASCII:
        assert text.isascii()
    assert_golden(f"gulf_caribbean_{mode.value}.txt", text)


def test_the_central_pacific_straddles_the_antimeridian():
    canvas = basemap_canvas(PACIFIC)
    for name, lat, lon in [
        ("Hawaii", 21.3, -157.85),
        ("Midway", 28.2, -177.4),  # just east of the line, to the right of the center
        ("Majuro", 7.1, 171.2),  # west of the line, to the left of the center
    ]:
        assert PACIFIC.bounds().contains(lat, lon), name
        x, y = PACIFIC.dot_at(lat, lon)
        assert any(canvas.dot(x + dx, y + dy) for dx in range(-5, 6) for dy in range(-5, 6)), name
    assert PACIFIC.dot_at(28.2, -177.4)[0] > PACIFIC.width // 2 > PACIFIC.dot_at(7.1, 171.2)[0]


def test_central_pacific_golden():
    assert_golden("central_pacific_120x40.txt", basemap_canvas(PACIFIC).to_text())


def test_a_view_of_the_whole_basin_uses_the_coarse_data_and_keeps_the_atolls():
    basin = Viewport(27.0, -145.0, 0.95, 120, 40)
    canvas = basemap_canvas(basin)
    assert count_dots(canvas) > 500
    assert not is_detailed(basin)
    for name, lat, lon in [("Majuro", 7.1, 171.2), ("Midway", 28.2, -177.35), ("Wake", 19.3, 166.6)]:
        x, y = basin.dot_at(lat, lon)
        assert any(canvas.dot(x + dx, y + dy) for dx in range(-2, 3) for dy in range(-2, 3)), name


def test_lakes_are_holes_in_the_land_with_a_shoreline():
    style = BasemapStyle(land="#111111", coast="#222222")
    view = Viewport(45.0, -84.0, 0.05, 120, 40)  # Lake Huron and Lake Michigan
    canvas = Canvas(view.cols, view.rows)
    draw_basemap(canvas, view, coast=False, borders=False, style=style)  # land fill alone, so no shoreline helps
    x, y = view.dot_at(44.8, -82.3)  # open water in Lake Huron
    assert canvas.cell(x // 2, y // 4)[1].bg is None
    x, y = view.dot_at(46.2, -84.6)  # Michigan's Upper Peninsula
    assert canvas.cell(x // 2, y // 4)[1].bg == "#111111"


def test_a_view_with_nothing_in_it_is_blank():
    middle_of_nowhere = Viewport(-30.0, -120.0, 0.1, 80, 24)  # the South Pacific, south of the data
    assert count_dots(basemap_canvas(middle_of_nowhere)) == 0


def test_a_basin_view_draws_no_borders_and_no_small_lakes():
    style = BasemapStyle(land="#111111", coast="#222222", border="#333333", state="#444444")
    basin = Viewport(35.0, -88.0, 0.35, 120, 40)  # the Gulf and the eastern United States, at basin scale
    canvas = basemap_canvas(basin, style=style)
    assert not colors(canvas) & {"#333333", "#444444"}
    x, y = basin.dot_at(46.0, -87.0)  # Lake Superior, wide enough to keep
    assert canvas.cell(x // 2, y // 4)[1].bg is None
    x, y = basin.dot_at(27.0, -80.85)  # Lake Okeechobee, under a cell across: land, not a pinprick hole
    assert canvas.cell(x // 2, y // 4)[1].bg == "#111111"
    far = Viewport(30.0, -90.0, 0.05, 120, 40)  # zoomed in, the borders are back
    assert "#444444" in colors(basemap_canvas(far, style=style))


# ---- #152: the data resolution holds at every terminal size; #155: a shore cell follows the shore to the dot -----------

QUIET_BOX = [(5.0, -98.0), (44.0, -14.0)]
QUIET_FOCUS = (22.0, -68.0)
# Map widget sizes (cols, rows) the quiet screen gets at 80x24, 100x40, 120x30 and 200x50 (tests/test_map_resolution.py
# reads them off the screen and checks these are still right).
QUIET_SIZES = {"80x24": (80, 15), "100x40": (66, 36), "120x30": (86, 26), "200x50": (150, 46)}


def test_a_shore_cell_shows_the_dots_on_the_land_side_not_a_whole_tinted_cell():
    # A straight north-south shore half way through a cell: land to the right of x = 1 dot.
    shore = [(1.0, -1.0), (1.0, 9.0), (9.0, 9.0), (9.0, -1.0)]
    canvas = Canvas(3, 2)
    canvas.tint_polygon([shore], "#land", "#edge")
    glyph, style = canvas.cell(0, 0)
    assert glyph == "⢸"  # the right-hand column of dots only
    assert (style.fg, style.bg) == ("#edge", None)
    assert canvas.cell(1, 0)[1].bg == "#land"  # a cell wholly inside is the flat tint


def test_a_shore_cell_keeps_a_track_drawn_over_it():
    canvas = Canvas(2, 1)
    canvas.tint_polygon([[(1.0, -1.0), (1.0, 5.0), (9.0, 5.0), (9.0, -1.0)]], "#land", "#edge")
    canvas.line(0, 0, 1, 3, "#track", 70)
    glyph, style = canvas.cell(0, 0)
    assert style.fg == "#track"
    assert glyph != "⢸"


def test_the_coastline_off_leaves_no_edge_dots():
    view = Viewport(25.0, -80.0, 0.05, 40, 20)
    canvas = basemap_canvas(view, coast=False)
    assert "#9fb3c8" not in colors(canvas)


@pytest.mark.parametrize("name", ["100x40", "120x30", "200x50"])
def test_the_quiet_coastline_golden(name):
    cols, rows = QUIET_SIZES[name]
    view = Viewport.fit_points(QUIET_BOX, cols, rows, max_deg_per_dot=0.5, focus=QUIET_FOCUS)
    assert_golden(f"quiet_atlantic_{name}.txt", basemap_canvas(view).to_text())


@pytest.mark.parametrize("mode", [Mode.BRAILLE, Mode.HALF, Mode.ASCII])
def test_a_part_covered_cell_in_every_mode(mode):
    # Land to the right of x = 1: in braille half of every cell's dots, in the 1 by 2 dot modes the whole cell.
    shore = [(1.0, -1.0), (1.0, 9.0), (9.0, 9.0), (9.0, -1.0)]
    canvas = Canvas(3, 2, mode)
    canvas.tint_polygon([shore], "#land", "#edge")
    glyph, style = canvas.cell(0, 0)
    if mode is Mode.BRAILLE:
        assert (glyph, style.fg, style.bg) == ("⢸", "#edge", None)
    else:
        assert glyph == " " and style.bg is None  # x = 0 is outside; a 1 dot wide cell is all or nothing
    assert canvas.cell(1, 0)[1].bg == "#land"


def test_a_half_block_cell_shows_the_land_half():
    canvas = Canvas(1, 1, Mode.HALF)
    canvas.tint_polygon([[(-1.0, 1.0), (2.0, 1.0), (2.0, 3.0), (-1.0, 3.0)]], "#land", "#edge")
    assert canvas.cell(0, 0) == ("▄", canvas.cell(0, 0)[1]) and canvas.cell(0, 0)[1].fg == "#edge"


def test_a_cell_nearly_all_land_is_land_tint_not_a_dotted_patch():
    # Seven dots of eight inside: a small hole takes the top-left one.
    canvas = Canvas(1, 1)
    land = [(-1.0, -1.0), (3.0, -1.0), (3.0, 5.0), (-1.0, 5.0)]
    hole = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    canvas.tint_polygon([land, hole], "#land", "#edge")
    assert canvas.cell(0, 0)[1].bg == "#land"


def test_a_cell_on_the_cut_of_the_data_keeps_the_whole_cell_rule():
    # Land down to y = 6 where the data is cut; the cell holding y = 6 is half land and must be a tint, not edge dots.
    canvas = Canvas(1, 2)
    canvas.tint_polygon(
        [[(-1.0, -1.0), (3.0, -1.0), (3.0, 6.0), (-1.0, 6.0)]], "#land", "#edge", cut=(-50.0, 6.0, 99.0)
    )
    assert canvas.cell(0, 1)[1].bg == "#land" and canvas.cell(0, 1)[1].fg is None
