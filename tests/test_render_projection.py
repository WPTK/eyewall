"""Viewport projection: round trips, scaling, panning, zooming, fitting and the antimeridian."""

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from eyewall.render.projection import MAX_CENTER_LAT, MIN_DEG_PER_DOT, Bounds, Viewport, bounds_of

GULF = Viewport(24.0, -85.0, 0.15, 120, 40)


def test_center_maps_to_the_middle_of_the_grid():
    assert GULF.width == 240 and GULF.height == 160
    assert GULF.to_dot(24.0, -85.0) == (120.0, 80.0)
    assert GULF.dot_at(24.0, -85.0) == (120, 80)


def test_north_is_up_and_east_is_right():
    x0, y0 = GULF.to_dot(24.0, -85.0)
    x1, y1 = GULF.to_dot(25.0, -84.0)
    assert x1 > x0 and y1 < y0


def test_a_degree_of_latitude_is_one_over_deg_per_dot_dots():
    _, y0 = GULF.to_dot(24.0, -85.0)
    _, y1 = GULF.to_dot(25.0, -85.0)
    assert y0 - y1 == pytest.approx(1.0 / 0.15)


def test_longitude_is_scaled_by_the_cosine_of_the_center_latitude():
    x0, _ = GULF.to_dot(24.0, -85.0)
    x1, _ = GULF.to_dot(24.0, -84.0)
    assert x1 - x0 == pytest.approx(math.cos(math.radians(24.0)) / 0.15, rel=1e-8)


def test_a_square_patch_of_sea_is_square_in_dots():
    view = Viewport(60.0, 0.0, 0.1, 80, 30)  # far from the equator, where the scaling matters
    (x0, y0), (x1, y1) = view.to_dot(60.0, 0.0), view.to_dot(60.5, 0.5 / math.cos(math.radians(60.0)))
    assert (x1 - x0) == pytest.approx(y0 - y1, rel=1e-6)


def test_the_longitude_scale_is_rounded_so_it_cannot_depend_on_the_platform():
    scale = GULF.lon_scale
    assert scale == round(scale, 9)
    assert scale == pytest.approx(math.cos(math.radians(24.0)), abs=1e-9)


@settings(max_examples=200, deadline=None)
@given(
    lat=st.floats(-80, 80),
    lon=st.floats(-180, 180),
    center_lat=st.floats(-70, 70),
    center_lon=st.floats(-180, 180),
    deg_per_dot=st.floats(0.01, 2.0),
)
def test_to_geo_inverts_to_dot_wherever_the_view_sits(lat, lon, center_lat, center_lon, deg_per_dot):
    view = Viewport(center_lat, center_lon, deg_per_dot, 100, 30)
    back_lat, back_lon = view.to_geo(*view.to_dot(lat, lon))
    assert back_lat == pytest.approx(lat, abs=1e-6)
    # Longitudes compare on the circle: -180 and 180 are the same place.
    assert abs((back_lon - lon + 180.0) % 360.0 - 180.0) < 1e-6


def test_center_longitude_is_normalized_and_latitude_and_zoom_are_clamped():
    view = Viewport(95.0, 190.0, 0.0, 10, 10)
    assert view.center_lon == -170.0
    assert view.center_lat == MAX_CENTER_LAT
    assert view.deg_per_dot == MIN_DEG_PER_DOT


@pytest.mark.parametrize("cols, rows", [(0, 10), (10, 0), (-1, 5)])
def test_a_viewport_needs_at_least_one_cell(cols, rows):
    with pytest.raises(ValueError):
        Viewport(0.0, 0.0, 0.1, cols, rows)


def test_half_block_viewports_have_fewer_dots_per_cell():
    view = Viewport(0.0, 0.0, 0.1, 10, 5, dots_x=1, dots_y=2)
    assert (view.width, view.height) == (10, 10)


# ----------------------------------------------------------------------------------------------- the antimeridian


def test_a_view_centered_on_the_antimeridian_puts_both_sides_in_place():
    view = Viewport(15.0, 180.0, 0.1, 100, 30)
    x_west_of_line, _ = view.to_dot(15.0, 179.0)
    x_east_of_line, _ = view.to_dot(15.0, -179.0)
    assert x_west_of_line < view.width / 2 < x_east_of_line
    assert (x_east_of_line - view.width / 2) == pytest.approx(view.width / 2 - x_west_of_line)
    assert view.to_dot(15.0, 180.0)[0] == view.to_dot(15.0, -180.0)[0] == view.width / 2


def test_a_point_just_across_the_line_is_close_not_a_world_away():
    view = Viewport(15.0, -178.0, 0.1, 100, 30)
    x_here, _ = view.to_dot(15.0, -178.0)
    x_there, _ = view.to_dot(15.0, 178.0)  # four degrees west of the center, across the line
    assert x_here - x_there == pytest.approx(4.0 * view.lon_scale / 0.1, rel=1e-6)
    assert x_there > 0


def test_to_geo_wraps_back_into_range():
    view = Viewport(15.0, 179.0, 0.1, 100, 30)
    _, lon = view.to_geo(view.width, 0)  # the right edge, east of 180
    assert -180.0 <= lon < 0.0


def test_a_path_across_the_antimeridian_stays_in_one_piece():
    view = Viewport(15.0, 180.0, 0.1, 100, 30)
    path = view.project_path([(15.0, 178.0), (15.0, 179.5), (15.0, -179.5), (15.0, -178.0)])
    xs = [x for x, _ in path]
    assert xs == sorted(xs)
    assert xs[-1] - xs[0] == pytest.approx(4.0 * view.lon_scale / 0.1, rel=1e-6)


def test_a_path_that_wanders_west_across_the_line_keeps_going_west():
    view = Viewport(15.0, -175.0, 0.1, 100, 30)
    path = view.project_path([(15.0, -178.0), (15.0, 179.0), (15.0, 176.0)])
    xs = [x for x, _ in path]
    assert xs == sorted(xs, reverse=True)


def test_project_path_agrees_with_to_dot_for_a_single_point():
    view = Viewport(15.0, 180.0, 0.1, 100, 30)
    assert view.project_path([(12.0, -170.0)])[0] == view.to_dot(12.0, -170.0)


def test_bounds_of_a_viewport_on_the_line_cross_it():
    view = Viewport(15.0, 180.0, 0.5, 100, 30)
    bounds = view.bounds()
    assert bounds.contains(15.0, 179.0) and bounds.contains(15.0, -179.0)
    assert not bounds.contains(15.0, 0.0)
    assert bounds.west > 0 > bounds.east


def test_bounds_of_points_on_both_sides_of_the_line_take_the_short_way():
    bounds = bounds_of([(10.0, 170.0), (20.0, -170.0), (15.0, 179.0)])
    assert bounds.west == 170.0 and bounds.east == -170.0
    assert bounds.lon_span == pytest.approx(20.0)
    assert (bounds.south, bounds.north) == (10.0, 20.0)
    assert bounds.center == (15.0, -180.0)


def test_bounds_of_one_point_and_of_nothing():
    assert bounds_of([(5.0, -40.0)]) == Bounds(5.0, -40.0, 5.0, 0.0)
    with pytest.raises(ValueError):
        bounds_of([])


def test_bounds_from_corners_that_wrap():
    bounds = Bounds.of(10.0, 170.0, 20.0, -170.0)
    assert bounds.lon_span == pytest.approx(20.0)
    assert Bounds.of(20.0, -90.0, 10.0, -80.0).south == 10.0  # corners may come in any vertical order


def test_bounds_intersection_works_across_the_line():
    a = Bounds(0.0, 170.0, 10.0, 20.0)  # 170 E to 170 W
    assert a.intersects(Bounds(5.0, -175.0, 8.0, 3.0))
    assert not a.intersects(Bounds(5.0, -100.0, 8.0, 3.0))
    assert not a.intersects(Bounds(20.0, 175.0, 30.0, 3.0))  # same longitudes, other latitudes
    assert Bounds(0.0, 0.0, 10.0, 360.0).intersects(Bounds(5.0, 100.0, 8.0, 3.0))


# ---------------------------------------------------------------------------------------- panning, zooming, fitting


def test_panning_by_dots_moves_the_map_under_the_view():
    moved = GULF.pan_dots(20, 0)  # the view moves east, so a fixed place shifts left
    assert moved.center_lon > GULF.center_lon
    assert moved.to_dot(24.0, -85.0)[0] == pytest.approx(GULF.width / 2 - 20)
    assert moved.pan_dots(-20, 0).center_lon == pytest.approx(GULF.center_lon)


def test_panning_south_and_by_cells():
    moved = GULF.pan_cells(0, 2)
    assert moved.center_lat == pytest.approx(24.0 - 8 * 0.15)
    assert moved.pan_degrees(1.0, 0.0).center_lat == pytest.approx(moved.center_lat + 1.0)


def test_panning_east_over_the_antimeridian_wraps_the_center():
    view = Viewport(10.0, 175.0, 0.1, 100, 30).pan_degrees(0.0, 10.0)
    assert view.center_lon == pytest.approx(-175.0)


def test_panning_cannot_leave_the_map():
    assert GULF.pan_degrees(100.0, 0.0).center_lat == MAX_CENTER_LAT


def test_zooming_in_halves_the_degrees_per_dot():
    assert GULF.zoom(2.0).deg_per_dot == pytest.approx(0.075)
    assert GULF.zoom(0.5).deg_per_dot == pytest.approx(0.3)
    with pytest.raises(ValueError):
        GULF.zoom(0.0)


def test_zoom_is_clamped():
    assert GULF.zoom(1e9).deg_per_dot == MIN_DEG_PER_DOT
    assert GULF.zoom(1e-9).deg_per_dot == 4.0


def test_zooming_about_an_anchor_keeps_the_anchor_in_place():
    anchor = (50.0, 30.0)
    lat, lon = GULF.to_geo(*anchor)
    for factor in (2.0, 0.5, 4.0):
        zoomed = GULF.zoom(factor, anchor)
        x, y = zoomed.to_dot(lat, lon)
        assert (x, y) == (pytest.approx(anchor[0], abs=1e-3), pytest.approx(anchor[1], abs=1e-3))


def test_resizing_keeps_the_center_and_zoom():
    bigger = GULF.resized(200, 60)
    assert (bigger.center_lat, bigger.center_lon, bigger.deg_per_dot) == (24.0, -85.0, 0.15)
    assert (bigger.cols, bigger.rows) == (200, 60)


def test_fit_shows_the_whole_box_with_a_margin():
    box = Bounds.of(10.0, -100.0, 30.0, -60.0)
    view = Viewport.fit(box, 120, 40, margin=0.05)
    for lat, lon in [(10.0, -100.0), (30.0, -60.0), (10.0, -60.0), (30.0, -100.0)]:
        x, y = view.to_dot(lat, lon)
        assert 0.05 * view.width * 0.99 <= x <= 0.95 * view.width * 1.01
        assert 0.05 * view.height * 0.99 <= y <= 0.95 * view.height * 1.01
    assert view.center_lat == pytest.approx(20.0)
    assert view.center_lon == pytest.approx(-80.0)


def test_fit_is_limited_by_whichever_side_is_tighter():
    wide = Viewport.fit(Bounds.of(20.0, -100.0, 22.0, -40.0), 100, 40)
    tall = Viewport.fit(Bounds.of(0.0, -80.0, 50.0, -78.0), 100, 40)
    x_west, _ = wide.to_dot(21.0, -100.0)
    x_east, _ = wide.to_dot(21.0, -40.0)
    assert x_east - x_west == pytest.approx(0.9 * wide.width, rel=0.02)
    _, y_north = tall.to_dot(50.0, -79.0)
    _, y_south = tall.to_dot(0.0, -79.0)
    assert y_south - y_north == pytest.approx(0.9 * tall.height, rel=0.02)


def test_fit_across_the_antimeridian():
    view = Viewport.fit_points([(18.0, 172.0), (22.0, -172.0)], 100, 30)
    assert view.center_lon == pytest.approx(180.0) or view.center_lon == pytest.approx(-180.0)
    for lat, lon in [(18.0, 172.0), (22.0, -172.0)]:
        x, y = view.to_dot(lat, lon)
        assert 0 < x < view.width and 0 < y < view.height


def test_fit_a_single_point_does_not_divide_by_zero():
    view = Viewport.fit_points([(25.0, -80.0)], 80, 24)
    assert view.dot_at(25.0, -80.0) == (view.width // 2, view.height // 2)


def test_fit_a_single_point_shows_a_window_of_at_least_two_degrees():
    view = Viewport.fit_points([(25.0, -80.0)], 80, 24)
    south, west, north, east = view.bounds().south, view.bounds().west, view.bounds().north, view.bounds().east
    assert north - south >= 2.0
    assert east - west >= 2.0


def test_viewport_bounds_contain_the_edges_of_the_view():
    bounds = GULF.bounds()
    assert bounds.contains(*GULF.to_geo(1, 1))
    assert bounds.contains(*GULF.to_geo(GULF.width - 1, GULF.height - 1))
    assert not bounds.contains(0.0, -85.0)


def test_centering_on_a_place_puts_it_in_the_middle():
    view = GULF.centered_on(35.0, 170.0)
    assert view.to_dot(35.0, 170.0) == (view.width / 2, view.height / 2)
    assert (view.cols, view.rows, view.deg_per_dot) == (120, 40, 0.15)
