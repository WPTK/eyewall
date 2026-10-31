import json
from pathlib import Path

from eyewall.coops.stations import MET, WATER_LEVEL, merge_tide_stations, parse_tide_stations
from eyewall.models.obs import TideStation

FIXTURES = Path(__file__).parent / "fixtures" / "coops"


def listing(name: str, product: str):
    return parse_tide_stations((FIXTURES / name).read_bytes(), product)


def test_the_water_level_listing_parses_with_lng_as_the_longitude():
    parsed = listing("stations_waterlevels.json", WATER_LEVEL)
    assert parsed.skipped == 0
    assert parsed.message is None
    by_id = {s.id: s for s in parsed.items}
    assert len(by_id) == 10
    assert by_id["8721604"] == TideStation(
        id="8721604",
        name="Trident Pier, Port Canaveral",
        lat=28.4158,
        lon=-80.5931,
        state="FL",
        great_lakes=False,
        products=frozenset({"water_level"}),
    )


def test_great_lakes_gauges_are_flagged_because_they_have_no_mllw_datum():
    by_id = {s.id: s for s in listing("stations_waterlevels.json", WATER_LEVEL).items}
    assert by_id["8311030"].great_lakes is True
    assert [s.id for s in by_id.values() if s.great_lakes] == ["8311030"]


def test_the_met_listing_is_tagged_met():
    parsed = listing("stations_met.json", MET)
    assert {s.id for s in parsed.items} >= {"8721604", "1611400", "1612340"}
    assert all(s.products == frozenset({"met"}) for s in parsed.items)


def test_merging_listings_unions_products_and_keeps_each_station_once():
    merged = merge_tide_stations([listing("stations_waterlevels.json", WATER_LEVEL), listing("stations_met.json", MET)])
    by_id = {s.id: s for s in merged}
    assert len(merged) == len(by_id) == 12
    assert by_id["8721604"].products == frozenset({"water_level", "met"})
    assert by_id["8735523"].products == frozenset({"water_level"})  # East Fowl River Bridge has no anemometer
    assert by_id["1611400"].products == frozenset({"met"})
    assert merged[0].id == "8518750"  # first appearance order


def test_odd_entries_are_skipped_and_counted():
    payload = {
        "count": 5,
        "stations": [
            {"id": "8721604", "name": "Trident", "lat": 28.4, "lng": -80.6},
            {"id": "", "lat": 1, "lng": 2},
            {"id": "1", "lat": "north", "lng": 2},
            {"id": "2", "lat": 1},
            "not an object",
        ],
    }
    parsed = parse_tide_stations(json.dumps(payload), WATER_LEVEL)
    assert [s.id for s in parsed.items] == ["8721604"]
    assert parsed.skipped == 4


def test_numbers_as_strings_and_a_lon_field_are_tolerated():
    payload = {"stations": [{"id": 8721604, "lat": "28.4158", "lon": "-80.5931", "name": None, "greatlakes": "yes"}]}
    station = parse_tide_stations(json.dumps(payload)).items[0]
    assert (station.id, station.lat, station.lon, station.name) == ("8721604", 28.4158, -80.5931, "")
    assert station.great_lakes is False  # only a real true counts


def test_not_json_or_no_station_list_gives_a_message():
    assert parse_tide_stations("<html>", WATER_LEVEL).message == "invalid station JSON"
    assert parse_tide_stations("{}", WATER_LEVEL).message == "station JSON has no station list"
    assert parse_tide_stations("[1]", WATER_LEVEL).message == "station JSON has no station list"
    assert parse_tide_stations("{}", WATER_LEVEL).items == ()
