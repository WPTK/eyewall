"""Map layers: what gets drawn, in which color, in which order, plus golden renderings of an Erin-like storm."""

import ast
import itertools
from dataclasses import replace
from pathlib import Path

import pytest

import eyewall
from eyewall.geo import destination, haversine_nm
from eyewall.palette import (
    CATEGORY_COLORS,
    NEUTRAL,
    WATCH_WARNING_COLORS,
    Category,
    WatchWarning,
    category_color,
    risk_color,
    wind_band_color,
)
from eyewall.render import layers
from eyewall.render.canvas import Canvas, Mode, Shade
from eyewall.render.layers import (
    ForecastPoint,
    MapOptions,
    MapScene,
    MapStyle,
    OutlookArea,
    StationMark,
    StormScene,
    TrackPoint,
    WarningSegment,
    WindRadii,
    draw_scene,
    render_map,
    scene_bounds,
)
from eyewall.render.projection import Viewport
from tests.render_support import assert_golden, erin_like_scene

ERIN_VIEW = Viewport(32.0, -66.0, 0.16, 120, 40)
ERIN_VIEW_ASCII = Viewport(32.0, -66.0, 0.29, 120, 40, dots_x=1, dots_y=2)
STYLE = MapStyle()


def cell_of(canvas: Canvas, view: Viewport, lat: float, lon: float):
    x, y = view.dot_at(lat, lon)
    return canvas.cell(x // canvas.dots_x, y // canvas.dots_y)


def colors(canvas: Canvas) -> set[str | None]:
    return {canvas.cell(c, r)[1].fg for r in range(canvas.rows) for c in range(canvas.cols)}


def dot_count(canvas: Canvas) -> int:
    return sum(canvas.dot(x, y) for y in range(canvas.height) for x in range(canvas.width))


def blank(view: Viewport, mode: Mode = Mode.BRAILLE) -> Canvas:
    return Canvas(view.cols, view.rows, mode)


def only(storm: StormScene, **kwargs) -> MapScene:
    return MapScene(storms=(replace(storm, **kwargs),) if kwargs else (storm,))


# -------------------------------------------------------------------------------------------------- architecture


def test_the_render_and_map_data_packages_do_not_import_textual():
    root = Path(eyewall.__file__).parent
    offenders = []
    for path in [*(root / "render").glob("*.py"), *(root / "mapdata").glob("*.py")]:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else []
            if isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
            offenders += [f"{path.name}: {n}" for n in names if n == "textual" or n.startswith("textual.")]
    assert offenders == []


def test_layers_need_none_of_the_nhc_models():
    source = Path(layers.__file__).read_text(encoding="utf-8")
    assert "eyewall.models" not in source and "eyewall.providers" not in source


# ---------------------------------------------------------------------------------------------------- goldens


def test_erin_like_storm_golden():
    canvas = render_map(ERIN_VIEW, erin_like_scene())
    assert_golden("erin_like_120x40.txt", canvas.to_text())


def test_erin_like_storm_golden_in_ascii():
    canvas = render_map(ERIN_VIEW_ASCII, erin_like_scene(), Mode.ASCII)
    assert canvas.to_text().isascii()
    assert_golden("erin_like_ascii.txt", canvas.to_text())


def test_the_storm_name_may_hold_characters_ascii_cannot_draw():
    scene = only(replace(erin_like_scene().storms[0], name="ÑANDÚ"))
    assert "?AND?" in render_map(ERIN_VIEW_ASCII, scene, Mode.ASCII).to_text()


def test_every_mode_draws_the_storm():
    for mode in Mode:
        view = Viewport(32.0, -66.0, 0.16 * 2 / mode.dots_y * 2, 120, 40, mode.dots_x, mode.dots_y)
        text = render_map(view, erin_like_scene(), mode).to_text()
        assert "ERIN" in text and "12Z Fri" in text


# --------------------------------------------------------------------------------------- the storm and its track


def test_the_center_is_marked_in_the_color_of_its_category_and_named():
    canvas = render_map(ERIN_VIEW, erin_like_scene())
    glyph, style = cell_of(canvas, ERIN_VIEW, 23.6, -68.2)
    assert glyph == "◉" and style.fg == CATEGORY_COLORS[Category.H3] and style.bold
    assert "◉ERIN" in canvas.to_text()


def test_best_track_segments_take_the_color_of_the_intensity_they_reach():
    storm = erin_like_scene().storms[0]
    canvas = render_map(ERIN_VIEW, MapScene(storms=(replace(storm, radii=(), cone=()),)))
    (lat_a, lon_a), (lat_b, lon_b) = (storm.best_track[5].lat, storm.best_track[5].lon), (
        storm.best_track[6].lat, storm.best_track[6].lon)  # fmt: skip
    middle = cell_of(canvas, ERIN_VIEW, (lat_a + lat_b) / 2, (lon_a + lon_b) / 2)
    assert middle[1].fg == CATEGORY_COLORS[Category.H5]  # the second fix is 140 kt


def test_the_forecast_line_is_dashed_and_the_best_track_is_not():
    view = Viewport(29.0, -75.0, 0.05, 120, 40)
    past = StormScene(best_track=(TrackPoint(30.0, -77.0, 60.0), TrackPoint(30.0, -73.0, 60.0)))
    ahead = StormScene(center=TrackPoint(28.0, -77.0, 60.0), forecast=(ForecastPoint(28.0, -73.0, 60.0),))
    solid = render_map(view, MapScene(storms=(past,)), options=OPEN_SEA)
    dashed = render_map(view, MapScene(storms=(ahead,)), options=OPEN_SEA)
    markers = dot_count(solid) - sum(solid.dot(x, y) for y in range(view.height) for x in range(view.width) if False)
    assert dot_count(solid) > 60
    assert 0.55 < (dot_count(dashed) - 0) / dot_count(solid) < 0.85, markers  # four dots on, two off


def test_a_center_past_the_last_best_track_fix_is_joined_to_it_by_a_solid_line():
    view = Viewport(29.0, -75.0, 0.05, 120, 40)
    storm = StormScene(
        center=TrackPoint(28.0, -75.0, 140.0),  # category 5 colour, which nothing else in the scene uses
        best_track=(TrackPoint(28.0, -79.0, 60.0), TrackPoint(28.0, -77.0, 60.0)),
    )
    canvas = render_map(view, MapScene(storms=(storm,)), options=OPEN_SEA)
    y = view.dot_at(28.0, -76.0)[1]
    start, end = view.dot_at(28.0, -77.0)[0], view.dot_at(28.0, -75.0)[0]
    assert all(canvas.dot(x, y) for x in range(start + 3, end - 3))  # joined, and no dashes
    assert cell_of(canvas, view, 28.0, -76.0)[1].fg == CATEGORY_COLORS[Category.H5]


def test_track_and_warnings_outrank_the_cone_and_the_coast():
    scene = erin_like_scene()
    canvas = render_map(ERIN_VIEW, scene)
    storm = scene.storms[0]
    # A forecast marker sits inside the cone; the cone's own colors never take the cell.
    forecast_cell = cell_of(canvas, ERIN_VIEW, storm.forecast[3].lat, storm.forecast[3].lon)
    assert forecast_cell[1].fg == category_color(storm.forecast[3].wind_kt)
    outer_banks_end = storm.warnings[1].points[-1]  # only a hurricane watch reaches this far north
    assert cell_of(canvas, ERIN_VIEW, *outer_banks_end)[1].fg == WATCH_WARNING_COLORS[WatchWarning.HURRICANE_WATCH]
    assert STYLE.basemap.coast in colors(canvas) and STYLE.cone_edge in colors(canvas)


def test_a_warning_drawn_later_covers_a_watch_on_the_same_coast():
    scene = erin_like_scene()
    canvas = render_map(ERIN_VIEW, scene)
    storm = scene.storms[0]
    first_point = storm.warnings[2].points[0]  # covered by both a hurricane watch and a tropical storm warning
    assert cell_of(canvas, ERIN_VIEW, *first_point)[1].fg == WATCH_WARNING_COLORS[WatchWarning.TROPICAL_STORM_WARNING]


def test_hurricane_warnings_outrank_tropical_storm_warnings_whatever_the_input_order():
    line = ((30.0, -80.0), (30.0, -75.0))
    view = Viewport(30.0, -77.5, 0.05, 80, 20)
    for kinds in ([WatchWarning.HURRICANE_WARNING, WatchWarning.TROPICAL_STORM_WARNING],
                  [WatchWarning.TROPICAL_STORM_WARNING, WatchWarning.HURRICANE_WARNING]):  # fmt: skip
        scene = MapScene(storms=(StormScene(warnings=tuple(WarningSegment(k, line) for k in kinds)),))
        canvas = render_map(view, scene)
        assert cell_of(canvas, view, 30.0, -77.5)[1].fg == WATCH_WARNING_COLORS[WatchWarning.HURRICANE_WARNING]


def test_surge_lines_sit_below_coastal_warnings():
    line = ((30.0, -80.0), (30.0, -75.0))
    view = Viewport(30.0, -77.5, 0.05, 80, 20)
    scene = MapScene(storms=(StormScene(
        surge=(WarningSegment(WatchWarning.SURGE_WARNING, line),),
        warnings=(WarningSegment(WatchWarning.TROPICAL_STORM_WATCH, line),),
    ),))  # fmt: skip
    canvas = render_map(view, scene)
    assert cell_of(canvas, view, 30.0, -77.5)[1].fg == WATCH_WARNING_COLORS[WatchWarning.TROPICAL_STORM_WATCH]
    surge_only = render_map(view, MapScene(storms=(replace(scene.storms[0], warnings=()),)))
    assert cell_of(surge_only, view, 30.0, -77.5)[1].fg == WATCH_WARNING_COLORS[WatchWarning.SURGE_WARNING]


def test_warning_lines_are_two_dots_thick():
    line = ((30.0, -80.0), (30.0, -75.0))
    view = Viewport(30.0, -77.5, 0.05, 80, 20)
    canvas = render_map(view, MapScene(storms=(StormScene(warnings=(WarningSegment(WatchWarning.HURRICANE_WATCH, line),)),)),
                        options=MapOptions(land=False, coast=False, borders=False))  # fmt: skip
    x = view.width // 2
    assert sum(canvas.dot(x, y) for y in range(view.height)) == 2


# ---------------------------------------------------------------------------------------------------- options


@pytest.mark.parametrize(
    "option, change",
    [
        ("radii", {"radii": ()}),
        ("cone", {"cone": ()}),
        ("warnings", {"warnings": (), "surge": ()}),
        ("track", {"best_track": (), "forecast": ()}),
    ],
)
def test_a_layer_switched_off_is_a_layer_that_was_never_there(option, change):
    storm = erin_like_scene().storms[0]
    off = render_map(ERIN_VIEW, only(storm), options=MapOptions(**{option: False}))
    never = render_map(ERIN_VIEW, only(storm, **change))
    assert off.to_text() == never.to_text()
    assert off.to_text() != render_map(ERIN_VIEW, only(storm)).to_text()


def test_stations_and_the_outlook_can_be_switched_off():
    scene = erin_like_scene()
    off = render_map(ERIN_VIEW, scene, options=MapOptions(buoys=False, tide_gauges=False))
    assert off.to_text() == render_map(ERIN_VIEW, replace(scene, buoys=(), tide_gauges=())).to_text()
    area = OutlookArea(rings=(((30.0, -90.0), (30.0, -80.0), (25.0, -85.0)),), risk="high", label="70%")
    with_area = replace(scene, outlook=(area,))
    assert (
        render_map(ERIN_VIEW, with_area, options=MapOptions(outlook=False)).to_text()
        == render_map(ERIN_VIEW, scene).to_text()
    )
    assert render_map(ERIN_VIEW, with_area).to_text() != render_map(ERIN_VIEW, scene).to_text()


def test_base_map_layers_follow_the_options():
    scene = MapScene()
    assert STYLE.basemap.land not in colors(render_map(ERIN_VIEW, scene, options=MapOptions(land=False)))
    assert STYLE.basemap.coast not in colors(render_map(ERIN_VIEW, scene, options=MapOptions(coast=False)))
    assert STYLE.basemap.border not in colors(render_map(ERIN_VIEW, scene, options=MapOptions(borders=False)))


def test_labels_can_be_switched_off_and_station_labels_switched_on():
    scene = erin_like_scene()
    text = render_map(ERIN_VIEW, scene).to_text()
    assert "ERIN" in text and "12Z Tue" in text and "41047" not in text
    quiet = render_map(ERIN_VIEW, scene, options=MapOptions(labels=False)).to_text()
    assert "ERIN" not in quiet and "12Z" not in quiet
    assert "41047" in render_map(ERIN_VIEW, scene, options=MapOptions(station_labels=True)).to_text()


# ---------------------------------------------------------------------------------------------------- radii

CENTER = (25.0, -70.0)
RADII = WindRadii(
    *CENTER, kt34=(200.0, 160.0, 120.0, 180.0), kt50=(100.0, 80.0, 60.0, 90.0), kt64=(50.0, 40.0, 30.0, 45.0)
)
ZOOMED = Viewport(*CENTER, 0.03, 100, 40)
OPEN_SEA = MapOptions(land=False, coast=False, borders=False)


def test_each_wind_radius_ring_passes_through_its_quadrant_radius():
    canvas = render_map(ZOOMED, MapScene(storms=(StormScene(radii=(RADII,)),)), options=OPEN_SEA)
    for knots, quadrants in ((34, RADII.kt34), (50, RADII.kt50), (64, RADII.kt64)):
        for bearing, radius in zip((45.0, 135.0, 225.0, 315.0), quadrants, strict=True):
            x, y = ZOOMED.dot_at(*destination(CENTER, bearing, radius))
            nearby = {canvas.cell((x + i) // 2, (y + j) // 4)[1].fg for i in (-1, 0, 1) for j in (-1, 0, 1)}
            assert wind_band_color(knots) in nearby, (knots, bearing)


def test_the_34_knot_ring_is_dashed_and_the_others_are_solid():
    storm = StormScene(radii=(RADII,))
    dashed = render_map(ZOOMED, MapScene(storms=(storm,)), options=OPEN_SEA)
    solid = render_map(ZOOMED, MapScene(storms=(storm,)), options=OPEN_SEA, style=MapStyle(radii_dash=(1, 0)))

    def outer_dots(canvas):  # the 34 kt ring is the only thing beyond the 50 kt ring's largest radius
        cx, cy = ZOOMED.width // 2, ZOOMED.height // 2
        limit = (110 / 60 / 0.03) ** 2
        return sum(canvas.dot(x, y) for y in range(ZOOMED.height) for x in range(ZOOMED.width)
                   if (x - cx) ** 2 + (y - cy) ** 2 > limit)  # fmt: skip

    assert 0.35 < outer_dots(dashed) / outer_dots(solid) < 0.75


def test_a_quadrant_without_wind_collapses_to_the_center():
    storm = StormScene(radii=(WindRadii(*CENTER, kt34=(120.0, 0.0, 0.0, 0.0)),))
    canvas = render_map(ZOOMED, MapScene(storms=(storm,)), options=OPEN_SEA)
    cx, cy = ZOOMED.dot_at(*CENTER)
    far_sw = ZOOMED.dot_at(*destination(CENTER, 225.0, 100.0))
    assert not any(canvas.dot(far_sw[0] + i, far_sw[1] + j) for i in range(-2, 3) for j in range(-2, 3))
    ne = ZOOMED.dot_at(*destination(CENTER, 45.0, 120.0))
    assert any(canvas.dot(ne[0] + i, ne[1] + j) for i in range(-2, 3) for j in range(-2, 3))
    assert canvas.dot(cx, cy) or any(canvas.dot(cx + i, cy + j) for i in (-1, 0, 1) for j in (-1, 0, 1))


def test_missing_or_empty_radii_draw_nothing():
    for radii in (WindRadii(*CENTER), WindRadii(*CENTER, kt34=(0.0, 0.0, 0.0, 0.0))):
        canvas = render_map(ZOOMED, MapScene(storms=(StormScene(radii=(radii,)),)), options=OPEN_SEA)
        assert dot_count(canvas) == 0


def test_the_outline_stays_on_its_radii_and_closes():
    outline = layers._radii_outline(*CENTER, (200.0, 160.0, 120.0, 180.0))
    assert len(outline) == 4 * (layers._RING_STEPS + 1)
    for index, radius in enumerate((200.0, 160.0, 120.0, 180.0)):
        for point in outline[index * 13 : (index + 1) * 13]:
            assert haversine_nm(CENTER, point) == pytest.approx(radius, abs=0.05)
    assert all(round(v, 5) == v for point in outline for v in point)


# ------------------------------------------------------------------------------------- outlook, stations, labels


def test_outlook_areas_are_hatched_by_risk_and_labelled():
    ring = ((22.0, -95.0), (22.0, -85.0), (28.0, -85.0), (28.0, -95.0))
    view = Viewport(25.0, -90.0, 0.08, 100, 30)
    counts = {}
    for risk in ("low", "medium", "high"):
        canvas = render_map(view, MapScene(outlook=(OutlookArea((ring,), risk),)), options=OPEN_SEA)
        counts[risk] = dot_count(canvas)
        assert colors(canvas) - {None} == {risk_color(risk)}
    assert counts["low"] < counts["medium"] < counts["high"]
    labelled = render_map(view, MapScene(outlook=(OutlookArea((ring,), "High", "70%"),)), options=OPEN_SEA)
    assert "70%" in labelled.to_text()
    row = next(r for r, line in enumerate(labelled.lines()) if "70%" in line)
    col = labelled.lines()[row].index("70%")
    assert abs(col + 1 - 50) <= 2 and abs(row - 15) <= 1  # at the middle of the box
    assert labelled.cell(col, row)[1] == (risk_color("high"), None, True)


def test_unknown_risk_is_neutral_and_lightly_hatched():
    ring = ((22.0, -95.0), (22.0, -85.0), (28.0, -85.0))
    view = Viewport(25.0, -90.0, 0.08, 100, 30)
    canvas = render_map(view, MapScene(outlook=(OutlookArea((ring,), "???"),)), options=OPEN_SEA)
    assert colors(canvas) - {None} == {NEUTRAL}
    light = render_map(view, MapScene(outlook=(OutlookArea((ring,), "low"),)), options=OPEN_SEA)
    assert dot_count(canvas) == dot_count(light)


def test_the_centroid_of_a_box_is_its_middle():
    assert layers._centroid([(0.0, 0.0), (10.0, 0.0), (10.0, 4.0), (0.0, 4.0)]) == pytest.approx((5.0, 2.0))
    assert layers._centroid([(0.0, 0.0), (4.0, 4.0), (8.0, 8.0)]) == pytest.approx((4.0, 4.0))  # no area


def test_buoys_are_colored_by_wind_and_dim_when_stale():
    view = Viewport(30.0, -75.0, 0.1, 100, 30)
    buoys = (StationMark(30.0, -75.0, 50.0), StationMark(31.0, -75.0, 20.0), StationMark(32.0, -75.0, None),
             StationMark(29.0, -75.0, 70.0, stale=True))  # fmt: skip
    canvas = render_map(view, MapScene(buoys=buoys), options=OPEN_SEA)
    assert cell_of(canvas, view, 30.0, -75.0) == ("●", (wind_band_color(50.0), None, True))
    assert cell_of(canvas, view, 31.0, -75.0) == ("●", (STYLE.buoy, None, False))
    assert cell_of(canvas, view, 32.0, -75.0)[1].fg == STYLE.buoy
    assert cell_of(canvas, view, 29.0, -75.0) == ("●", (STYLE.stale, None, False))


def test_tide_gauges_have_their_own_glyph_and_color():
    view = Viewport(30.0, -75.0, 0.1, 100, 30)
    canvas = render_map(view, MapScene(tide_gauges=(StationMark(30.0, -75.0),)), options=OPEN_SEA)
    assert cell_of(canvas, view, 30.0, -75.0) == ("▲", (STYLE.tide_gauge, None, False))
    ascii_canvas = render_map(Viewport(30.0, -75.0, 0.2, 100, 30, 1, 2),
                              MapScene(tide_gauges=(StationMark(30.0, -75.0),), buoys=(StationMark(31.0, -75.0),)),
                              Mode.ASCII, OPEN_SEA)  # fmt: skip
    assert "^" in ascii_canvas.to_text() and "o" in ascii_canvas.to_text()


def test_markers_outside_the_view_are_skipped():
    view = Viewport(30.0, -75.0, 0.1, 100, 30)
    scene = MapScene(buoys=(StationMark(60.0, -75.0), StationMark(30.0, 40.0)), cursor=(0.0, 0.0))
    assert render_map(view, scene, options=OPEN_SEA).to_text().strip() == ""


def test_labels_move_aside_rather_than_cover_each_other():
    view = Viewport(30.0, -75.0, 0.1, 100, 30)
    forecast = (ForecastPoint(30.0, -75.0, 60.0, "AAAA"), ForecastPoint(30.0, -74.99, 60.0, "BBBB"),
                ForecastPoint(30.0, -74.98, 60.0, "CCCC"))  # fmt: skip
    text = render_map(view, MapScene(storms=(StormScene(forecast=forecast),)), options=OPEN_SEA).to_text()
    assert all(label in text for label in ("AAAA", "BBBB", "CCCC"))
    assert text.count("◆") == 1  # the three markers share one cell


def test_a_label_with_no_room_is_dropped_not_squeezed_in():
    view = Viewport(30.0, -75.0, 0.1, 10, 1)  # one row, narrower than the label on either side of the marker
    scene = MapScene(storms=(StormScene(forecast=(ForecastPoint(30.0, -75.0, 60.0, "LONGLABEL"),)),))
    text = render_map(view, scene, options=OPEN_SEA).to_text()
    assert "◆" in text and "LONG" not in text


def test_the_cursor_is_the_top_layer():
    view = Viewport(30.0, -75.0, 0.1, 100, 30)
    scene = MapScene(buoys=(StationMark(30.0, -75.0, 60.0),), cursor=(30.0, -75.0))
    assert cell_of(render_map(view, scene, options=OPEN_SEA), view, 30.0, -75.0) == ("┼", (STYLE.cursor, None, True))
    ascii_view = Viewport(30.0, -75.0, 0.2, 100, 30, 1, 2)
    assert "+" in render_map(ascii_view, MapScene(cursor=(30.0, -75.0)), Mode.ASCII, OPEN_SEA).to_text()


# ------------------------------------------------------------------------------------- the antimeridian, and misc


def test_a_central_pacific_storm_crosses_the_antimeridian_in_one_piece():
    view = Viewport(15.0, 180.0, 0.05, 120, 40)
    storm = StormScene(
        name="KAI",
        center=TrackPoint(14.0, 176.0, 80.0),
        forecast=(ForecastPoint(15.0, 178.0, 85.0, "12Z"), ForecastPoint(16.0, -178.0, 90.0, "00Z"),
                  ForecastPoint(17.0, -174.0, 90.0, "12Z")),
    )  # fmt: skip
    canvas = render_map(view, MapScene(storms=(storm,)), options=OPEN_SEA)
    glyph_cols = sorted(c for line in canvas.lines() for c, ch in enumerate(line) if ch == "◆")
    assert len(glyph_cols) == 3
    assert glyph_cols[0] < view.cols // 2 < glyph_cols[1]  # 178 E is left of the line, 178 W right of it
    # The dashes run on across the line: no gap between the two markers is wider than one dash gap.
    columns = sorted({x // 2 for x in range(view.width) for y in range(view.height) if canvas.dot(x, y)})
    between = [c for c in columns if glyph_cols[0] < c < glyph_cols[1]]
    assert between and between[0] - glyph_cols[0] <= 3 and glyph_cols[1] - between[-1] <= 3
    assert all(b - a <= 2 for a, b in itertools.pairwise(between))
    assert any(c < view.cols // 2 for c in between) and any(c > view.cols // 2 for c in between)


def test_the_extent_to_fit_is_the_cone_or_else_the_track():
    storm = erin_like_scene().storms[0]
    points = storm.extent()
    assert (storm.center.lat, storm.center.lon) in points
    assert all(p in points for p in storm.cone[0])
    assert (storm.best_track[0].lat, storm.best_track[0].lon) not in points  # the cone is what matters
    bare = StormScene(
        center=TrackPoint(20.0, -50.0), best_track=(TrackPoint(19.0, -52.0),), forecast=(ForecastPoint(22.0, -48.0),)
    )
    assert set(bare.extent()) == {(19.0, -52.0), (22.0, -48.0), (20.0, -50.0)}
    assert StormScene().extent() == []


def test_scene_bounds_cover_every_storm():
    scene = erin_like_scene()
    bounds = scene_bounds(scene)
    assert bounds is not None
    for storm in scene.storms:
        for lat, lon in storm.extent():
            assert bounds.contains(lat, lon)
    assert scene_bounds(MapScene()) is None
    view = Viewport.fit(bounds, 120, 40)
    assert all(0 <= view.to_dot(lat, lon)[0] <= view.width for lat, lon in scene.storms[0].extent())


def test_drawing_on_a_canvas_that_does_not_fit_the_viewport_is_refused():
    with pytest.raises(ValueError, match="viewport is"):
        draw_scene(Canvas(50, 20), ERIN_VIEW, erin_like_scene())


def test_an_empty_scene_is_just_the_base_map():
    from eyewall.render.basemap import basemap_canvas

    assert render_map(ERIN_VIEW).to_text() == basemap_canvas(ERIN_VIEW).to_text()


def test_the_cone_is_shaded_with_a_bright_edge():
    cone = ((30.0, -80.0), (30.0, -70.0), (20.0, -75.0))
    view = Viewport(25.0, -75.0, 0.1, 100, 30)
    scene = MapScene(storms=(StormScene(cone=(cone,)),))
    canvas = render_map(view, scene, options=OPEN_SEA)
    assert colors(canvas) - {None} == {STYLE.cone_fill, STYLE.cone_edge}
    shaded = render_map(view, scene, options=OPEN_SEA, style=MapStyle(cone_shade=Shade.SOLID))
    assert dot_count(shaded) > 2 * dot_count(canvas)
    inside = cell_of(canvas, view, 27.0, -75.0)
    assert inside[1].fg == STYLE.cone_fill
