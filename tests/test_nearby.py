"""Nearby-station selection, checked against distances worked out by hand.

The geometry is chosen so the answers are exact. One degree of arc is DEG nautical miles on the geo module's Earth.
Meridians and the equator are great circles, so a station N degrees north of an equatorial track is exactly N degrees
of arc from it, and a storm moving along the equator at constant speed reaches a given longitude at a given hour.
"""

import math

import pytest

from eyewall.config import NearbyConfig
from eyewall.geo import EARTH_RADIUS_NM
from eyewall.models.obs import Station, TideStation
from eyewall.state.nearby import NearbyStation, TrackFix, hourly_track, nearby_stations

DEG = EARTH_RADIUS_NM * math.pi / 180  # nautical miles in one degree of arc
CENTER = (0.0, 0.0)
EAST = [TrackFix(24, 0.0, 6.0), TrackFix(48, 0.0, 12.0)]  # 15 kt along the equator: 3 degrees every 12 hours
CFG = NearbyConfig(radius_now_nm=200, radius_track_nm=100, track_hours=72, max_stations=40)


def st(station_id: str, lat: float, lon: float) -> Station:
    return Station(id=station_id, name=station_id, lat=lat, lon=lon)


def ids(found: list[NearbyStation[Station]]) -> list[str]:
    return [n.station.id for n in found]


def by_id(found: list[NearbyStation[Station]]) -> dict[str, NearbyStation[Station]]:
    return {n.station.id: n for n in found}


# --- the hourly path --------------------------------------------------------------------------------------------


def test_the_path_is_sampled_hourly_along_the_great_circle():
    points = hourly_track(CENTER, EAST, 72)
    assert len(points) == 49  # hours 0 to 48: the path ends at the last fix, not at track_hours
    assert points[0] == CENTER
    assert points[12][0] == pytest.approx(0.0, abs=1e-9)
    assert points[12][1] == pytest.approx(3.0)
    assert points[24][1] == pytest.approx(6.0)
    assert points[48][1] == pytest.approx(12.0)


def test_the_path_stops_at_track_hours():
    points = hourly_track(CENTER, EAST, 10)
    assert len(points) == 11
    assert points[10][1] == pytest.approx(2.5)


def test_fixes_in_any_order_and_fixes_at_or_before_now_are_handled():
    shuffled = [EAST[1], TrackFix(0, 5.0, 5.0), TrackFix(-6, 9.0, 9.0), EAST[0]]
    assert hourly_track(CENTER, shuffled, 72) == hourly_track(CENTER, EAST, 72)


def test_a_repeated_hour_keeps_the_last_fix():
    twice = [TrackFix(24, 9.0, 9.0), TrackFix(24, 0.0, 6.0)]
    assert hourly_track(CENTER, twice, 72)[24][1] == pytest.approx(6.0)


def test_no_forecast_means_a_path_of_just_the_center():
    assert hourly_track((10.0, -50.0), [], 72) == [(10.0, -50.0)]


# --- now, track and the way they combine ------------------------------------------------------------------------


def test_distance_and_bearing_to_the_current_center_are_exact_on_a_meridian_and_the_equator():
    found = by_id(
        nearby_stations(
            CENTER,
            [],
            [st("N", 2, 0), st("E", 0, 3), st("S", -1, 0), st("W", 0, -4), st("FAR", 5, 5)],
            config=CFG,
        )
    )
    assert set(found) == {"N", "E", "S"}  # W is 240 nm away, beyond the 200 nm circle
    assert found["N"].distance_nm == pytest.approx(2 * DEG)
    assert found["N"].bearing_deg == pytest.approx(0.0)
    assert found["E"].distance_nm == pytest.approx(3 * DEG)
    assert found["E"].bearing_deg == pytest.approx(90.0)
    assert found["S"].distance_nm == pytest.approx(DEG)
    assert found["S"].bearing_deg == pytest.approx(180.0)


def test_a_station_inside_the_circle_is_near_now_and_its_flags_say_why():
    near = nearby_stations(CENTER, [], [st("A", 1, 0)], config=CFG)[0]
    assert (near.near_now, near.near_track, near.watchlisted) == (True, True, False)


def test_a_station_on_the_forecast_track_far_from_the_center_is_included_with_its_eta():
    # 1 degree north of the equator at longitude 9: exactly 1 degree of arc from the track, reached at hour 36
    found = nearby_stations(CENTER, EAST, [st("AHEAD", 1, 9)], config=CFG)
    assert ids(found) == ["AHEAD"]
    ahead = found[0]
    assert ahead.near_now is False
    assert ahead.near_track is True
    assert ahead.closest_approach_nm == pytest.approx(DEG)
    assert ahead.eta_hours == pytest.approx(36.0, abs=1e-3)
    expected_now = math.acos(math.cos(math.radians(1)) * math.cos(math.radians(9)))
    assert ahead.distance_nm == pytest.approx(expected_now * EARTH_RADIUS_NM)


def test_a_station_beside_the_track_but_outside_the_track_radius_is_left_out():
    # 2 degrees (120 nm) off the track is beyond the 100 nm track radius, and beyond 200 nm from the center
    assert nearby_stations(CENTER, EAST, [st("WIDE", 2, 9)], config=CFG) == []
    wider = NearbyConfig(radius_now_nm=200, radius_track_nm=130, track_hours=72, max_stations=40)
    assert ids(nearby_stations(CENTER, EAST, [st("WIDE", 2, 9)], config=wider)) == ["WIDE"]


def test_the_track_ends_at_the_last_fix():
    # (1 N, 12.5 E) is 67 nm from the last fix (0, 12) at hour 48; (1 N, 14 E) is 134 nm from it
    found = by_id(nearby_stations(CENTER, EAST, [st("END", 1, 12.5), st("PAST", 1, 14)], config=CFG))
    assert set(found) == {"END"}
    assert found["END"].eta_hours == pytest.approx(48.0, abs=1e-6)
    assert found["END"].closest_approach_nm == pytest.approx(math.hypot(1, 0.5) * DEG, rel=2e-3)


def test_track_hours_limits_how_far_ahead_the_track_counts():
    short = NearbyConfig(radius_now_nm=200, radius_track_nm=100, track_hours=24, max_stations=40)
    assert nearby_stations(CENTER, EAST, [st("LATER", 0, 9)], config=short) == []
    assert ids(nearby_stations(CENTER, EAST, [st("LATER", 0, 9)], config=CFG)) == ["LATER"]
    assert ids(nearby_stations(CENTER, EAST, [st("SOONER", 0, 5)], config=short)) == ["SOONER"]


def test_a_storm_moving_away_is_closest_now():
    west = [TrackFix(24, 0.0, -6.0)]
    near = nearby_stations(CENTER, west, [st("BEHIND", 1, 3)], config=CFG)[0]
    assert near.near_now is True
    assert near.near_track is False  # the track runs the other way
    assert near.eta_hours == 0.0
    assert near.closest_approach_nm == pytest.approx(near.distance_nm)


def test_without_a_track_the_closest_approach_is_the_current_distance():
    near = nearby_stations(CENTER, [], [st("A", 0, 2)], config=CFG)[0]
    assert (near.eta_hours, near.closest_approach_nm) == (0.0, pytest.approx(2 * DEG))


def test_results_are_ranked_by_current_distance_with_ties_by_id():
    stations = [st("C", 0, 3), st("A", 0, 1), st("B", 0, -1), st("D", 2, 0)]
    assert ids(nearby_stations(CENTER, [], stations, config=CFG)) == ["A", "B", "D", "C"]  # 1, 1, 2 and 3 degrees


def test_works_across_the_dateline():
    center = (0.0, 179.0)
    track = [TrackFix(24, 0.0, -175.0)]  # 6 degrees of arc east, across 180
    found = by_id(nearby_stations(center, track, [st("ACROSS", 0.5, -178), st("BACK", 0, 170)], config=CFG))
    assert set(found) == {"ACROSS"}
    expected = math.acos(math.cos(math.radians(0.5)) * math.cos(math.radians(3))) * EARTH_RADIUS_NM
    assert found["ACROSS"].distance_nm == pytest.approx(expected)
    assert found["ACROSS"].bearing_deg == pytest.approx(
        math.degrees(math.atan2(3, 0.5)), abs=0.1
    )  # east and a little north
    assert found["ACROSS"].eta_hours == pytest.approx(12.0, abs=0.1)


# --- watchlist and the cap --------------------------------------------------------------------------------------


def test_watchlist_stations_are_always_in_whatever_their_distance():
    far = st("TRDF1", 40, 100)
    found = by_id(nearby_stations(CENTER, EAST, [far, st("A", 0, 1)], config=CFG, watchlist=["trdf1"]))
    assert set(found) == {"TRDF1", "A"}
    assert (found["TRDF1"].watchlisted, found["TRDF1"].near_now, found["TRDF1"].near_track) == (True, False, False)
    assert found["TRDF1"].closest_approach_nm > 1000
    assert found["A"].watchlisted is False


def test_a_watchlisted_station_that_is_also_close_keeps_its_near_flags():
    found = nearby_stations(CENTER, [], [st("A", 0, 1)], config=CFG, watchlist=["A"])
    assert (found[0].watchlisted, found[0].near_now) == (True, True)


def test_the_cap_keeps_the_nearest_stations():
    stations = [st(f"S{n}", 0, n * 0.5) for n in range(1, 7)]
    capped = NearbyConfig(radius_now_nm=200, radius_track_nm=100, track_hours=72, max_stations=3)
    assert ids(nearby_stations(CENTER, [], stations, config=capped)) == ["S1", "S2", "S3"]


def test_the_cap_never_drops_a_watchlist_station_and_trims_the_rest_instead():
    stations = [st(f"S{n}", 0, n * 0.5) for n in range(1, 7)] + [st("FARWATCH", 50, 50)]
    capped = NearbyConfig(radius_now_nm=200, radius_track_nm=100, track_hours=72, max_stations=3)
    found = nearby_stations(CENTER, [], stations, config=capped, watchlist=["FARWATCH"])
    assert ids(found) == ["S1", "S2", "FARWATCH"]  # two slots left for the others


def test_a_watchlist_longer_than_the_cap_squeezes_everyone_else_out():
    stations = [st("W1", 30, 30), st("W2", 31, 31), st("NEAR", 0, 1)]
    capped = NearbyConfig(radius_now_nm=200, radius_track_nm=100, track_hours=72, max_stations=1)
    found = nearby_stations(CENTER, [], stations, config=capped, watchlist=["W1", "W2"])
    assert ids(found) == ["W1", "W2"]


def test_the_default_config_is_the_one_in_eyewall_config():
    # 300 nm now and 150 nm from the track, at most 40 stations
    found = nearby_stations(CENTER, EAST, [st("IN", 0, 4.9), st("OUT", 0, -5.1), st("TRACK", 2, 9)])
    assert ids(found) == ["IN", "TRACK"]  # IN is 294 nm away; OUT 306 nm; TRACK 120 nm off the track at hour 36


def test_no_stations_gives_an_empty_list():
    assert nearby_stations(CENTER, EAST, []) == []


def test_stations_of_any_kind_with_an_id_and_a_position_work():
    gauge = TideStation(id="8721604", name="Trident Pier", lat=0.5, lon=1.0)
    found = nearby_stations(CENTER, [], [gauge], config=CFG, watchlist=["8721604"])
    assert found[0].station is gauge
