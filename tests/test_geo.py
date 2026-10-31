import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from eyewall.geo import (
    bearing_deg,
    compass_point,
    destination,
    distance_to_polyline_nm,
    distance_to_segment_nm,
    haversine_nm,
    interpolate,
    normalize_lon,
)

DEGREE_NM = 60.0405  # one degree of arc on the mean-radius sphere

lats = st.floats(min_value=-80, max_value=80)
lons = st.floats(min_value=-180, max_value=180)


def test_one_degree_of_arc():
    assert haversine_nm((0, 0), (0, 1)) == pytest.approx(DEGREE_NM, abs=0.01)
    assert haversine_nm((0, 0), (1, 0)) == pytest.approx(DEGREE_NM, abs=0.01)


def test_distance_across_the_antimeridian():
    assert haversine_nm((0, 179), (0, -179)) == pytest.approx(2 * DEGREE_NM, abs=0.02)


def test_distance_is_zero_for_the_same_point_and_symmetric():
    assert haversine_nm((25.7, -80.2), (25.7, -80.2)) == 0
    a, b = (25.7, -80.2), (32.3, -64.7)
    assert haversine_nm(a, b) == pytest.approx(haversine_nm(b, a))


def test_cardinal_bearings():
    assert bearing_deg((0, 0), (1, 0)) == pytest.approx(0)
    assert bearing_deg((0, 0), (0, 1)) == pytest.approx(90)
    assert bearing_deg((0, 0), (-1, 0)) == pytest.approx(180)
    assert bearing_deg((0, 0), (0, -1)) == pytest.approx(270)


def test_destination_due_north_and_east():
    lat, lon = destination((0, 0), 0, DEGREE_NM)
    assert (lat, lon) == pytest.approx((1.0, 0.0), abs=1e-3)
    lat, lon = destination((0, 0), 90, DEGREE_NM)
    assert (lat, lon) == pytest.approx((0.0, 1.0), abs=1e-3)


def test_destination_wraps_longitude():
    _, lon = destination((0, 179.5), 90, DEGREE_NM)
    assert lon == pytest.approx(-179.5, abs=1e-3)


@given(lats, lons, st.floats(min_value=0, max_value=360), st.floats(min_value=1, max_value=3000))
def test_destination_then_distance_round_trips(lat, lon, bearing, distance):
    end = destination((lat, lon), bearing, distance)
    assert haversine_nm((lat, lon), end) == pytest.approx(distance, rel=1e-6, abs=1e-6)


def test_normalize_lon():
    assert normalize_lon(190) == -170
    assert normalize_lon(-190) == 170
    assert normalize_lon(0) == 0
    assert normalize_lon(-180) == -180
    assert normalize_lon(180) == -180


def test_interpolate_endpoints_and_midpoint():
    a, b = (0.0, 0.0), (0.0, 10.0)
    assert interpolate(a, b, 0) == pytest.approx(a, abs=1e-9)
    assert interpolate(a, b, 1) == pytest.approx(b, abs=1e-9)
    assert interpolate(a, b, 0.5) == pytest.approx((0.0, 5.0), abs=1e-9)
    assert interpolate(a, a, 0.5) == a


def test_distance_to_segment_beside_the_middle():
    assert distance_to_segment_nm((1, 5), (0, 0), (0, 10)) == pytest.approx(DEGREE_NM, abs=0.01)


def test_distance_to_segment_beyond_an_end_uses_the_endpoint():
    assert distance_to_segment_nm((0, 15), (0, 0), (0, 10)) == pytest.approx(5 * DEGREE_NM, abs=0.05)


def test_distance_to_a_zero_length_segment():
    assert distance_to_segment_nm((1, 0), (0, 0), (0, 0)) == pytest.approx(DEGREE_NM, abs=0.01)


def test_distance_to_polyline():
    track = [(0.0, 0.0), (0.0, 10.0), (10.0, 10.0)]
    # The last leg runs along the 10th meridian; (5N, 11E) is 1 degree of longitude off it.
    off_meridian = math.degrees(math.asin(math.cos(math.radians(5)) * math.sin(math.radians(1)))) * 60.0405
    assert distance_to_polyline_nm((5, 11), track) == pytest.approx(off_meridian, abs=0.01)
    assert distance_to_polyline_nm((1, 5), [(0.0, 0.0)]) == pytest.approx(haversine_nm((1, 5), (0, 0)))
    assert distance_to_polyline_nm((1, 5), []) == math.inf


@given(lats, lons, lats, lons, lats, lons)
def test_segment_distance_never_exceeds_the_nearer_endpoint(plat, plon, alat, alon, blat, blon):
    point, a, b = (plat, plon), (alat, alon), (blat, blon)
    nearest_end = min(haversine_nm(point, a), haversine_nm(point, b))
    assert distance_to_segment_nm(point, a, b) <= nearest_end + 1e-6


def test_compass_point():
    assert compass_point(0) == "N"
    assert compass_point(11.2) == "N"
    assert compass_point(11.25) == "NNE"
    assert compass_point(90) == "E"
    assert compass_point(225) == "SW"
    assert compass_point(359) == "N"
    assert compass_point(-90) == "W"
