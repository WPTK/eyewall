"""Pure helpers behind the interface: coordinate text and the map's fit points."""

from eyewall.ui.adapt import basin_points
from eyewall.ui.products import fmt_lat, fmt_lon


def test_coordinates_carry_hemisphere_letters():
    assert fmt_lat(25.1) == "25.1N"
    assert fmt_lat(-3.0) == "3.0S"
    assert fmt_lon(-75.25) in {"75.2W", "75.3W"}
    assert fmt_lon(170.0) == "170.0E"


def test_basin_points_fit_one_basin_or_all():
    assert len(basin_points(("AL",))) == 2
    assert len(basin_points(())) == len(basin_points(("AL", "EP", "CP")))
