"""The base map: detail levels, layer switches, caching and golden renderings."""

import pytest

from eyewall.render.basemap import (
    DETAIL_SWITCH,
    BasemapStyle,
    basemap_canvas,
    detail_for,
    draw_basemap,
    ensure_matches,
)
from eyewall.render.canvas import Canvas, Mode, Priority, Shade
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
    return {canvas.cell(c, r)[1].fg for r in range(canvas.rows) for c in range(canvas.cols)}


def test_detail_follows_the_zoom():
    assert detail_for(GULF) == 50
    assert detail_for(Viewport(25.0, -75.0, DETAIL_SWITCH - 0.01, 100, 30)) == 50
    assert detail_for(Viewport(25.0, -75.0, DETAIL_SWITCH, 100, 30)) == 110
    assert detail_for(Viewport(30.0, -150.0, 1.0, 120, 40)) == 110  # the whole basin


def test_each_layer_can_be_switched_off():
    style = BasemapStyle(land="#111111", coast="#222222", border="#333333", state="#444444")
    everything = basemap_canvas(GULF, style=style)
    assert colors(everything) >= {"#111111", "#222222", "#333333"}
    no_land = basemap_canvas(GULF, land=False, style=style)
    assert "#111111" not in colors(no_land) and count_dots(no_land) < count_dots(everything)
    no_coast = basemap_canvas(GULF, coast=False, style=style)
    assert "#222222" not in colors(no_coast)
    no_borders = basemap_canvas(GULF, borders=False, style=style)
    assert not colors(no_borders) & {"#333333", "#444444"}
    nothing = basemap_canvas(GULF, land=False, coast=False, borders=False)
    assert count_dots(nothing) == 0


def test_land_is_dim_and_coast_is_drawn_over_it():
    style = BasemapStyle(land="#111111", coast="#222222", land_shade=Shade.SOLID)
    canvas = Canvas(GULF.cols, GULF.rows)
    draw_basemap(canvas, GULF, borders=False, style=style)
    x, y = GULF.dot_at(19.5, -89.0)  # inland on the Yucatan
    assert canvas.dot(x, y)
    cell = (x // 2, y // 4)
    assert canvas.cell(*cell)[1].fg == "#111111"
    cape = GULF.dot_at(28.46, -80.53)  # Cape Canaveral: land meets sea, and the coast outranks the land
    assert canvas.cell(cape[0] // 2, cape[1] // 4)[1].fg == "#222222"
    assert Priority.COAST > Priority.LAND


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
        ("Tarawa", 1.4, 173.0),
    ]:
        if not PACIFIC.bounds().contains(lat, lon):
            continue
        x, y = PACIFIC.dot_at(lat, lon)
        assert any(canvas.dot(x + dx, y + dy) for dx in range(-5, 6) for dy in range(-5, 6)), name
    assert PACIFIC.dot_at(28.2, -177.4)[0] > PACIFIC.width // 2 > PACIFIC.dot_at(7.1, 171.2)[0]


def test_central_pacific_golden():
    assert_golden("central_pacific_120x40.txt", basemap_canvas(PACIFIC).to_text())


def test_a_view_of_the_whole_basin_uses_the_coarse_data_and_draws_quickly():
    basin = Viewport(27.0, -145.0, 0.95, 120, 40)
    canvas = basemap_canvas(basin)
    assert count_dots(canvas) > 500
    assert detail_for(basin) == 110


def test_a_view_with_nothing_in_it_is_blank():
    middle_of_nowhere = Viewport(-30.0, -120.0, 0.1, 80, 24)  # the South Pacific, south of the data
    assert count_dots(basemap_canvas(middle_of_nowhere)) == 0
