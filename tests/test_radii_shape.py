"""The wind radii polygon: geodesic arcs, wedges for empty quadrants, and one valid shape across the antimeridian."""

from __future__ import annotations

import itertools
import math

import pytest
import shapely
from hypothesis import given, settings
from hypothesis import strategies as st
from pyproj import Geod
from shapely.geometry import MultiPolygon, Polygon

from eyewall.radii_shape import MAX_RADIUS_NM, radii_lines, radii_shape

GEOD = Geod(ellps="WGS84")
NM = 1852.0


def distance_nm(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Geodesic distance in nautical miles between two (lat, lon) points."""
    return GEOD.inv(a[1], a[0], b[1], b[0])[2] / NM


def parts(shape: Polygon | MultiPolygon) -> list[Polygon]:
    return list(shape.geoms) if isinstance(shape, MultiPolygon) else [shape]


def test_every_ring_vertex_sits_at_a_geodesic_radius_between_its_quadrants():
    center = (25.0, -70.0)
    radii = (200.0, 160.0, 120.0, 180.0)
    distances = [distance_nm(center, point) for point in radii_lines(center, radii)[0]]
    assert min(distances) == pytest.approx(120.0, abs=0.01)
    assert max(distances) == pytest.approx(200.0, abs=0.01)
    for radius in radii:
        assert sum(abs(d - radius) < 0.01 for d in distances) >= 13  # the whole arc, twelve steps and both ends


def test_the_arcs_follow_the_ellipsoid_not_a_sphere():
    center = (60.0, 10.0)
    shape = radii_shape(center, (300.0, 300.0, 300.0, 300.0))
    due_north = GEOD.fwd(center[1], center[0], 0.0, 300.0 * NM)[1]
    assert shape.bounds[3] == pytest.approx(due_north, abs=1e-6)
    assert due_north - center[0] == pytest.approx(4.9851, abs=0.0005)  # a sphere gives 4.9967


def test_a_quadrant_of_zero_or_none_leaves_a_wedge():
    for empty in (0.0, None):
        shape = radii_shape((25.0, -70.0), (120.0, empty, empty, empty))
        assert isinstance(shape, Polygon)
        assert shape.is_valid
        assert shape.contains(shapely.Point(-70.0 + 0.5, 25.0 + 0.5))  # inside the NE quadrant
        assert not shape.contains(shapely.Point(-70.0 - 0.5, 25.0 - 0.5))  # the SW quadrant is empty


def test_no_radius_in_any_quadrant_is_no_shape():
    assert radii_shape((25.0, -70.0), (0.0, 0.0, 0.0, 0.0)) is None
    assert radii_shape((25.0, -70.0), (None, None, None, None)) is None
    assert radii_lines((25.0, -70.0), (0.0, None, 0.0, None)) == ()


def test_bad_radii_count_as_none():
    assert radii_shape((25.0, -70.0), (-5.0, math.nan, math.inf, -math.inf)) is None


def test_a_ring_on_the_antimeridian_splits_in_two_with_every_longitude_in_range():
    shape = radii_shape((20.0, 179.5), (200.0, 200.0, 200.0, 200.0))
    assert isinstance(shape, MultiPolygon)
    assert len(shape.geoms) == 2
    west, east = sorted(shape.geoms, key=lambda g: g.bounds[0])
    assert west.bounds[0] == -180.0 and west.bounds[2] < -170
    assert east.bounds[2] == 180.0 and east.bounds[0] > 170
    assert shape.is_valid
    # the two halves together are as big as one unbroken ring would be (area in degrees, so compare to a far-off copy)
    away = radii_shape((20.0, 0.0), (200.0, 200.0, 200.0, 200.0))
    assert shape.area == pytest.approx(away.area, rel=1e-3)


@pytest.mark.parametrize("lon", [-180.0, 180.0, 179.99, -179.99, 540.0])
def test_a_center_on_the_dateline_gives_a_valid_shape_either_way_round(lon):
    shape = radii_shape((-15.0, lon), (150.0, 100.0, 80.0, 120.0))
    assert shape is not None and shape.is_valid
    minx, _, maxx, _ = shape.bounds
    assert -180.0 <= minx <= maxx <= 180.0


def test_the_radii_are_capped_short_of_the_pole():
    shape = radii_shape((89.0, 0.0), (MAX_RADIUS_NM,) * 4)
    assert shape is not None and shape.is_valid
    assert shape.bounds[3] < 90.0
    assert radii_shape((90.0, 0.0), (100.0,) * 4) is None


finite_radius = st.one_of(st.none(), st.floats(min_value=0.0, max_value=5000.0, allow_nan=False))


@settings(max_examples=300, deadline=None)
@given(
    lat=st.floats(min_value=-85.0, max_value=85.0),
    lon=st.one_of(st.floats(min_value=-180.0, max_value=180.0), st.sampled_from([-180.0, 180.0, 179.999, -179.999])),
    radii=st.tuples(finite_radius, finite_radius, finite_radius, finite_radius),
)
def test_any_center_and_radii_give_a_valid_finite_in_range_shape(lat, lon, radii):
    shape = radii_shape((lat, lon), radii)
    if not any(r is not None and r >= 0.01 for r in radii):
        assert shape is None
        return
    assert shape is not None
    assert shape.is_valid and not shape.is_empty
    minx, miny, maxx, maxy = shape.bounds
    assert all(math.isfinite(v) for v in (minx, miny, maxx, maxy))
    assert -180.0 <= minx <= maxx <= 180.0
    assert -90.0 <= miny <= maxy <= 90.0
    for part in parts(shape):
        assert part.exterior.is_simple
        assert not part.interiors or all(r.is_ccw is not None for r in part.interiors)
    for line in radii_lines((lat, lon), radii):
        assert len(line) > 1
        assert all(-90.0 <= la <= 90.0 and -180.0 <= lo <= 180.0 for la, lo in line)


def edges(lines):
    return {frozenset(pair) for line in lines for pair in itertools.pairwise(line)}


@pytest.mark.parametrize("lon", [180.0, -180.0])
def test_a_storm_centered_on_the_dateline_keeps_its_radial_edges(lon):
    lines = radii_lines((20.0, lon), (100.0, None, None, None))
    assert len(lines) == 1 and lines[0][0] == lines[0][-1]  # a quarter disc east of 180: one closed outline
    on_meridian = sorted({p for p in lines[0] if p[1] == -180.0})
    assert on_meridian[0] == (20.0, -180.0)
    assert on_meridian[-1][0] == pytest.approx(20.0 + 100.0 / 60.0, abs=0.02)
    drawn = edges(lines)
    for a, b in itertools.pairwise(on_meridian):  # the radial edge up the meridian is drawn, whole
        assert frozenset((a, b)) in drawn
    assert (20.0, -180.0) in {p for edge in drawn for p in edge}
    assert any(p[1] > -180.0 for p in lines[0])


def test_a_ring_cut_by_the_antimeridian_has_no_line_along_the_cut():
    lines = radii_lines((20.0, 179.5), (200.0, 200.0, 200.0, 200.0))
    assert len(lines) == 1 or all(line[0] != line[-1] for line in lines)
    for line in lines:
        for a, b in itertools.pairwise(line):
            assert not (abs(a[1]) == abs(b[1]) == 180.0 and a[1] == b[1])


def test_the_lines_are_cached_and_equal_across_calls():
    first = radii_lines((25.0, -70.0), (100.0, 80.0, 60.0, 90.0))
    assert radii_lines((25.0, -70.0), [100.0, 80.0, 60.0, 90.0]) is first
