import copy
import json
from datetime import UTC, datetime

import pytest

from eyewall.models.storm import AdvNum, Basin, Classification, ProductRef
from eyewall.providers.base import ParseError
from eyewall.providers.nhc.current import parse_current_storms
from eyewall.providers.nhc.ids import text_is_current
from tests.nhc_fixtures import nhc_bytes


def _populated():
    return json.loads(nhc_bytes("current/populated.json"))


def _storm(document, index=0):
    return parse_current_storms(json.dumps(document)).storms[index]


def test_a_quiet_day_is_an_empty_list():
    # The recorded live answer on 2026-10-31, a day with no active storms.
    result = parse_current_storms(nhc_bytes("current/empty.json"))
    assert result.storms == ()
    assert result.skipped == 0


def test_populated_file_lists_four_storms_keyed_by_lower_case_id():
    result = parse_current_storms(nhc_bytes("current/populated.json"))
    assert [s.id for s in result.storms] == ["al052025", "al082024", "al062026", "ep152026"]
    assert result.by_id("AL052025") is result.storms[0]
    assert result.by_id("al999999") is None


def test_string_numbers_become_numbers_and_movement_stays_in_mph():
    erin = parse_current_storms(nhc_bytes("current/populated.json")).by_id("al052025")
    assert erin.name == "Erin"
    assert erin.bin_number == "AT5"
    assert erin.classification is Classification.HU
    assert erin.intensity_kt == 120  # "120" in the feed
    assert erin.pressure_mb == 937  # "937" in the feed
    assert (erin.lat, erin.lon) == (24.0, -71.3)
    assert erin.movement_dir_deg == 310
    assert erin.movement_speed_mph == 10.0
    assert erin.last_update == datetime(2025, 8, 19, 0, 0, tzinfo=UTC)


def test_movement_speed_as_a_string_is_still_a_number():
    ptc = parse_current_storms(nhc_bytes("current/populated.json")).by_id("al082024")
    assert ptc.movement_speed_mph == 7.0  # "7" in the feed


def test_product_references_carry_the_intermediate_suffix():
    erin = parse_current_storms(nhc_bytes("current/populated.json")).by_id("al052025")
    assert erin.forecast_advisory.adv_num == AdvNum(30)
    assert erin.public_advisory.adv_num == AdvNum(30, "A")
    assert erin.public_advisory.adv_num.intermediate
    assert erin.public_advisory.issued == datetime(2025, 8, 19, 0, 0, tzinfo=UTC)
    assert erin.public_advisory.updated == datetime(2025, 8, 18, 23, 55, 40, 2000, tzinfo=UTC)
    assert erin.public_advisory.url == "https://www.nhc.noaa.gov/text/MIATCPAT5.shtml"
    assert erin.adv_num == AdvNum(30)  # the forecast advisory's number wins
    assert erin.forecast_track.adv_num == AdvNum(30, "A")
    assert erin.forecast_track.zip_url.endswith("al052025_5day_030A.zip")
    assert erin.forecast_track.kmz_url.endswith("AL052025_030Aadv_TRACK.kmz")
    assert erin.forecast_wind_radii.zip_url.endswith("al052025_fcst_030.zip")
    assert erin.best_track.zip_url.endswith("/gis/best_track/al052025_best_track.zip")
    assert erin.best_track.adv_num is None  # the best track has no advisory number
    assert erin.peak_surge.kml_url.endswith("AL052025_PeakStormSurge_030adv.kml")


def test_wind_probability_gis_has_one_url_per_file():
    erin = parse_current_storms(nhc_bytes("current/populated.json")).by_id("al052025")
    gis = erin.wind_speed_probabilities_gis
    assert gis.zip_5km_url.endswith("_wsp_120hr5km.zip")
    assert gis.zip_half_degree_url.endswith("_wsp_120hrhalfDeg.zip")
    assert gis.kmz_34kt_url.endswith("wsp34knt120hr_5km.kmz")
    assert gis.kmz_64kt_url.endswith("wsp64knt120hr_5km.kmz")


def test_a_potential_tropical_cyclone_has_missing_products():
    ptc = parse_current_storms(nhc_bytes("current/populated.json")).by_id("al082024")
    assert ptc.classification is Classification.PTC
    assert ptc.is_potential
    assert ptc.name == "Eight"
    assert ptc.wind_speed_probabilities is None
    assert ptc.best_track is None
    assert ptc.wind_speed_probabilities_gis is None
    assert ptc.forecast_track is not None
    assert ptc.public_advisory.adv_num == AdvNum(1)


def test_a_post_tropical_storm_is_classified_pc():
    fay = parse_current_storms(nhc_bytes("current/populated.json")).by_id("al062026")
    assert fay.classification is Classification.PC
    assert fay.classification_text == "PC"
    assert fay.wind_watches_warnings is None
    assert fay.intensity_kt == 25
    assert fay.pressure_mb == 1011


def test_an_ep_id_in_a_cp_bin_keeps_the_ep_basin():
    nolo = parse_current_storms(nhc_bytes("current/populated.json")).by_id("ep152026")
    assert nolo.bin_number == "CP2"
    assert nolo.basin is Basin.EP
    assert nolo.bin_basin is Basin.CP
    assert nolo.lon == 180.0  # "180.0E" at the dateline
    assert nolo.public_advisory.url == "https://www.nhc.noaa.gov/text/HFOTCPCP2.shtml"


def test_atlantic_bins_map_to_the_al_basin():
    erin = parse_current_storms(nhc_bytes("current/populated.json")).by_id("al052025")
    assert erin.basin is Basin.AL
    assert erin.bin_basin is Basin.AL


# ---- staleness: text is only applied to the advisory CurrentStorms lists ------------------------------------------


def _erin():
    return parse_current_storms(nhc_bytes("current/populated.json")).by_id("AL052025")


def test_text_is_current_compares_each_product_with_its_own_reference():
    erin = _erin()
    # The public advisory is at the intermediate 30A while the forecast advisory is still 30.
    assert erin.public_advisory.adv_num == AdvNum(30, "A")
    assert text_is_current(erin, erin.forecast_advisory, storm_id="al052025", adv_num=AdvNum(30))
    assert text_is_current(erin, erin.public_advisory, storm_id="AL052025", adv_num=AdvNum(30, "A"))
    assert not text_is_current(erin, erin.public_advisory, storm_id="al052025", adv_num=AdvNum(30))


def test_text_from_another_storm_or_advisory_is_stale():
    erin = _erin()
    assert not text_is_current(erin, erin.forecast_advisory, storm_id="al062026", adv_num=AdvNum(30))
    assert not text_is_current(erin, erin.forecast_advisory, storm_id="al052025", adv_num=AdvNum(29))
    assert not text_is_current(erin, erin.forecast_advisory, storm_id="al052025", adv_num=None)
    # With no reference the storm's newest advisory number (the forecast advisory's) is used.
    assert text_is_current(erin, None, storm_id=None, adv_num=AdvNum(30))
    assert not text_is_current(erin, ProductRef(), storm_id=None, adv_num=AdvNum(31))


# ---- tolerance ----------------------------------------------------------------------------------------------------


def test_entries_without_an_id_are_skipped_and_counted():
    document = _populated()
    del document["activeStorms"][1]["id"]
    document["activeStorms"].append("not an object")
    result = parse_current_storms(json.dumps(document))
    assert [s.id for s in result.storms] == ["al052025", "al062026", "ep152026"]
    assert result.skipped == 2


def test_a_storm_with_only_an_id_still_parses():
    storm = _storm({"activeStorms": [{"id": "AL012027"}]})
    assert storm.id == "al012027"
    assert storm.name == ""
    assert storm.classification is Classification.UNKNOWN
    assert storm.intensity_kt is None
    assert storm.lat is None
    assert storm.last_update is None
    assert storm.public_advisory is None
    assert storm.adv_num is None


def test_unknown_classification_is_kept_as_text():
    document = _populated()
    document["activeStorms"][0]["classification"] = "XYZ"
    storm = _storm(document)
    assert storm.classification is Classification.UNKNOWN
    assert storm.classification_text == "XYZ"


@pytest.mark.parametrize("value", ["", "--", None, "n/a", "  "])
def test_unusable_numbers_become_none(value):
    document = _populated()
    document["activeStorms"][0]["intensity"] = value
    document["activeStorms"][0]["pressure"] = value
    document["activeStorms"][0]["movementSpeed"] = value
    storm = _storm(document)
    assert (storm.intensity_kt, storm.pressure_mb, storm.movement_speed_mph) == (None, None, None)


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), 10**400, "inf", "nan", "1e999"])
def test_numbers_that_are_not_finite_become_none(value):
    document = _populated()
    document["activeStorms"][0]["intensity"] = value
    document["activeStorms"][0]["latitudeNumeric"] = value
    document["activeStorms"][0]["latitude"] = "nonsense"
    storm = parse_current_storms(json.dumps(document, default=str, allow_nan=True)).storms[0]
    assert storm.intensity_kt is None
    assert storm.lat is None


def test_numbers_may_arrive_as_numbers_or_padded_strings():
    document = _populated()
    document["activeStorms"][0]["intensity"] = 115
    document["activeStorms"][0]["pressure"] = " 940 "
    document["activeStorms"][0]["movementDir"] = "305"
    storm = _storm(document)
    assert (storm.intensity_kt, storm.pressure_mb, storm.movement_dir_deg) == (115, 940, 305)


def test_position_falls_back_to_the_text_when_the_numeric_twin_is_missing():
    document = _populated()
    for entry in document["activeStorms"]:
        entry.pop("latitudeNumeric")
        entry.pop("longitudeNumeric")
    document["activeStorms"][0]["latitude"] = "22.0S"
    document["activeStorms"][0]["longitude"] = "71.3W"
    result = parse_current_storms(json.dumps(document))
    assert (result.storms[0].lat, result.storms[0].lon) == (-22.0, -71.3)
    assert (result.storms[3].lat, result.storms[3].lon) == (24.2, 180.0)


def test_longitudes_beyond_the_dateline_wrap():
    document = _populated()
    document["activeStorms"][3]["longitudeNumeric"] = 182.5
    assert _storm(document, 3).lon == pytest.approx(-177.5)


def test_null_missing_and_wrong_typed_products_are_none():
    document = copy.deepcopy(_populated())
    erin = document["activeStorms"][0]
    erin["publicAdvisory"] = None
    erin["forecastAdvisory"] = "oops"
    del erin["forecastDiscussion"]
    erin["forecastTrack"] = []
    storm = _storm(document)
    assert storm.public_advisory is None
    assert storm.forecast_advisory is None
    assert storm.forecast_discussion is None
    assert storm.forecast_track is None
    assert storm.adv_num is None


def test_bad_advisory_numbers_and_times_inside_a_product_are_none():
    document = _populated()
    erin = document["activeStorms"][0]
    erin["forecastAdvisory"]["advNum"] = "soon"
    erin["forecastAdvisory"]["issuance"] = "yesterday"
    storm = _storm(document)
    assert storm.forecast_advisory.adv_num is None
    assert storm.forecast_advisory.issued is None
    assert storm.forecast_advisory.url is not None


def test_extra_fields_are_ignored():
    document = _populated()
    document["activeStorms"][0]["somethingNew"] = {"a": 1}
    document["extraTopLevel"] = True
    assert len(parse_current_storms(json.dumps(document)).storms) == 4


@pytest.mark.parametrize("payload", [b"{}", b'{"other": 1}', b'{"activeStorms": null}', b'{"activeStorms": {}}'])
def test_a_document_without_a_storm_list_raises_instead_of_meaning_no_storms(payload):
    with pytest.raises(ParseError):
        parse_current_storms(payload)


def test_an_empty_storm_list_is_a_quiet_season():
    assert parse_current_storms(b'{"activeStorms": []}').storms == ()


@pytest.mark.parametrize("payload", [b"", b"<html>maintenance</html>", b"[1, 2]", b"null", b"\xff\xfe"])
def test_a_payload_that_is_not_a_json_object_raises(payload):
    with pytest.raises(ParseError):
        parse_current_storms(payload)


def test_str_input_is_accepted_too():
    assert parse_current_storms(nhc_bytes("current/empty.json").decode()).storms == ()


def test_a_repeated_id_keeps_the_first_entry_and_counts_the_rest_as_skipped():
    document = _populated()
    first = document["activeStorms"][0]
    repeat = {**first, "name": "Again", "id": first["id"].upper()}
    document["activeStorms"].append(repeat)
    result = parse_current_storms(json.dumps(document))
    assert [s.id for s in result.storms] == [s.id for s in parse_current_storms(json.dumps(_populated())).storms]
    assert result.storms[0].name != "Again"
    assert result.skipped == 1
