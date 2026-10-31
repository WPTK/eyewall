from pathlib import Path

import pytest

from eyewall.models.obs import Station
from eyewall.ndbc.stations import parse_stations

FIXTURES = Path(__file__).parent / "fixtures" / "ndbc"


@pytest.fixture(scope="module")
def catalog() -> dict[str, Station]:
    parsed = parse_stations((FIXTURES / "activestations.xml").read_bytes())
    assert parsed.skipped == 0
    assert parsed.message is None
    return {s.id: s for s in parsed.items}


def test_the_recorded_catalog_parses_completely(catalog):
    assert len(catalog) == 20


def test_a_reporting_buoy_has_everything(catalog):
    assert catalog["41010"] == Station(
        id="41010",
        name="CANAVERAL EAST - 120NM East of Cape Canaveral",
        lat=28.86,
        lon=-78.478,
        type="buoy",
        owner="NDBC",
        program="NDBC Meteorological/Ocean",
        elevation_m=0.0,
        met=True,
        currents=False,
        water_quality=False,
        dart=False,
    )


def test_listed_buoys_that_stopped_reporting_have_met_false(catalog):
    for dark in ("42040", "42003", "42019", "41001", "41002"):
        assert catalog[dark].met is False, dark
    assert all(catalog[working].met for working in ("41010", "41025", "41047", "41048", "42001"))


def test_cman_ids_are_normalised_to_the_upper_case_used_in_file_names(catalog):
    assert {"TRDF1", "FWYF1", "SSBN7", "18CI3"} <= catalog.keys()
    assert not any(station_id != station_id.upper() for station_id in catalog)
    assert catalog["TRDF1"].type == "fixed"
    assert catalog["TRDF1"].elevation_m == 3.5


def test_ids_can_be_seven_characters(catalog):
    assert catalog["1801589"].type == "usv"


def test_a_station_without_the_flags_gives_none_not_false(catalog):
    tao = catalog["32303"]
    assert (tao.met, tao.currents, tao.water_quality, tao.dart) == (None, None, None, None)


def test_a_missing_elevation_is_none_and_entities_are_decoded(catalog):
    assert catalog["62114"].elevation_m is None
    assert catalog["62114"].name == 'Tartan "A" AWS'


def test_blank_names_are_kept_blank(catalog):
    assert catalog["15008"].name == ""


def test_stations_without_an_id_or_a_position_are_skipped_and_counted():
    xml = (
        '<?xml version="1.0" encoding="utf-8"?><stations>'
        '<station id="41010" lat="28.86" lon="-78.478" met="y"/>'
        '<station lat="1" lon="2"/>'
        '<station id="41011" lat="oops" lon="2"/>'
        '<station id="41012" lat="1"/>'
        "</stations>"
    )
    parsed = parse_stations(xml)
    assert [s.id for s in parsed.items] == ["41010"]
    assert parsed.skipped == 3


def test_text_with_an_xml_declaration_parses_like_bytes():
    xml = '<?xml version="1.0" encoding="utf-8"?><stations><station id="abc" lat="1" lon="2"/></stations>'
    assert parse_stations(xml).items == parse_stations(xml.encode()).items
    assert parse_stations(xml).items[0].id == "ABC"


def test_unknown_attributes_and_elements_are_ignored():
    xml = '<stations><note>hi</note><station id="41010" lat="1" lon="2" newthing="x"><child/></station></stations>'
    assert len(parse_stations(xml).items) == 1


def test_broken_xml_gives_a_message_not_an_exception():
    parsed = parse_stations("<stations><station id=")
    assert parsed.items == ()
    assert parsed.message is not None
    assert parsed.message.startswith("invalid station XML")


def test_a_document_type_declaration_is_refused():
    bomb = '<!DOCTYPE x [<!ENTITY a "aaaa">]><stations><station id="&a;" lat="1" lon="2"/></stations>'
    parsed = parse_stations(bomb)
    assert parsed.items == ()
    assert parsed.message == "station XML has a DTD; refusing to parse it"
