import json
from datetime import UTC, datetime

import pytest

from eyewall.palette import WatchWarning
from eyewall.providers.base import ParseError
from eyewall.providers.nhc.alerts import parse_alerts, parse_product, parse_product_list
from tests.nhc_fixtures import nhc_bytes


def test_no_active_alerts_is_an_empty_feature_collection():
    # The recorded live answer on a day with no tropical alerts.
    result = parse_alerts(nhc_bytes("api/alerts_active_none.json"))
    assert result.alerts == ()
    assert result.skipped == 0
    assert result.updated is not None and result.updated.tzinfo is UTC


def test_tropical_alerts_with_and_without_geometry():
    result = parse_alerts(nhc_bytes("api/alerts_populated.json"))
    assert len(result.alerts) == 2
    assert result.skipped == 1  # the feature with no event
    assert result.updated == datetime(2025, 8, 18, 21, 5, tzinfo=UTC)
    watch, surge = result.alerts

    assert watch.event == "Tropical Storm Watch"
    assert watch.kind is WatchWarning.TROPICAL_STORM_WATCH
    assert watch.area_desc == "Eastern Carteret; Pamlico"
    assert (watch.severity, watch.urgency, watch.certainty) == ("Moderate", "Future", "Possible")
    assert (watch.status, watch.message_type) == ("Actual", "Alert")
    assert watch.sender_name == "NWS Newport/Morehead City NC"
    assert watch.effective == datetime(2025, 8, 19, 1, 0, tzinfo=UTC)  # 9 PM EDT on the 18th
    assert watch.onset == datetime(2025, 8, 20, 12, 0, tzinfo=UTC)
    assert watch.expires == datetime(2025, 8, 19, 7, 0, tzinfo=UTC)
    assert watch.zones == (
        "https://api.weather.gov/zones/forecast/NCZ196",
        "https://api.weather.gov/zones/forecast/NCZ095",
    )
    assert watch.same_codes == ("037031", "037137")
    assert watch.headline.startswith("Tropical Storm Watch issued August 18")
    assert watch.instruction == "Monitor the progress of the storm and finalize preparations."
    assert len(watch.rings) == 1
    assert watch.rings[0][0] == (34.69, -76.67)  # (lat, lon) from GeoJSON [lon, lat]
    assert watch.rings[0][0] == watch.rings[0][-1]

    assert surge.kind is WatchWarning.SURGE_WATCH
    assert surge.rings == ()  # geometry null: the alert is described by its zones only


def test_real_alerts_of_other_events_parse_with_zones_and_codes_but_no_tropical_kind():
    # Real api.weather.gov alerts recorded on 2026-10-31 (frost and freeze), for the shape of a live alert.
    result = parse_alerts(nhc_bytes("api/alerts_real_shape.json"))
    assert result.skipped == 0
    assert [a.event for a in result.alerts] == [
        "Frost Advisory",
        "Frost Advisory",
        "Freeze Warning",
        "Frost Advisory",
        "Frost Advisory",
    ]
    assert all(a.kind is None for a in result.alerts)
    first = result.alerts[0]
    assert first.id.startswith("urn:oid:2.49.0.1.840.0.")
    assert first.status == "Actual" and first.message_type in {"Alert", "Update"}
    assert first.area_desc
    assert first.zones and all(zone.startswith("https://api.weather.gov/zones/") for zone in first.zones)
    assert first.same_codes and all(code.isdigit() for code in first.same_codes)
    assert first.effective is not None and first.expires is not None and first.effective < first.expires
    assert first.sender_name and first.headline and first.description


def test_unknown_events_have_no_kind_and_missing_fields_are_none():
    document = {
        "features": [
            {"properties": {"event": "Tropical Cyclone Statement", "id": "abc"}},
            {"properties": {"event": "Hurricane Warning", "id": "def", "geocode": None, "expires": "garbage"}},
        ]
    }
    first, second = parse_alerts(json.dumps(document)).alerts
    assert first.event == "Tropical Cyclone Statement"
    assert first.kind is None
    assert (first.headline, first.severity, first.effective, first.zones, first.rings) == (None, None, None, (), ())
    assert second.kind is WatchWarning.HURRICANE_WARNING
    assert second.expires is None
    assert second.same_codes == ()


def test_multipolygon_geometry_gives_every_ring_and_wraps_the_dateline():
    document = {
        "features": [
            {
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [
                        [[[-179.5, 20.0], [-178.5, 20.0], [-178.5, 21.0], [-179.5, 20.0]]],
                        [[[181.0, 10.0], [182.0, 10.0], [182.0, 11.0], [181.0, 10.0]]],
                    ],
                },
                "properties": {"event": "Hurricane Watch"},
            }
        ]
    }
    (alert,) = parse_alerts(json.dumps(document)).alerts
    assert len(alert.rings) == 2
    assert alert.rings[1][0] == (10.0, pytest.approx(-179.0))


@pytest.mark.parametrize("payload", [b"", b"<html>503</html>", b"[]", b"3"])
def test_alerts_payloads_that_are_not_a_json_object_raise(payload):
    with pytest.raises(ParseError):
        parse_alerts(payload)


def test_a_feature_collection_without_features_is_empty():
    assert parse_alerts(b'{"type": "FeatureCollection"}').alerts == ()
    assert parse_alerts(b'{"features": null}').alerts == ()


# ---- product by bin: the text fallback ----------------------------------------------------------------------------


def test_product_list_is_newest_first_and_names_the_office():
    listing = parse_product_list(nhc_bytes("api/products_tcm_ep2.json"))
    assert len(listing) == 25
    newest = listing[0]
    assert newest.id == "cb19ea7f-e12e-49d6-ad66-8e64a538f4e2"
    assert (newest.code, newest.office, newest.wmo_id) == ("TCM", "KNHC", "WTPZ22")
    assert newest.name == "Marine/Aviation Tropical Cyclone Advisory"
    assert newest.issued == datetime(2026, 10, 30, 2, 31, tzinfo=UTC)
    assert [item.issued for item in listing] == sorted((item.issued for item in listing), reverse=True)


def test_an_empty_product_list_is_empty():
    assert parse_product_list(b'{"@graph": []}') == ()
    assert parse_product_list(b"{}") == ()


def test_single_product_carries_its_text():
    product = parse_product(nhc_bytes("api/product_two_at.json"))
    assert product.id == "3ae4e478-d4e6-4c83-b209-60fbef9a5e73"
    assert (product.code, product.office, product.wmo_id) == ("TWO", "KNHC", "ABNT20")
    assert product.issued == datetime(2026, 10, 31, 5, 7, tzinfo=UTC)
    assert "Tropical cyclone formation is not expected during the next 7 days." in product.text
    assert product.text.startswith("\n000\nABNT20 KNHC 310507")


@pytest.mark.parametrize("payload", [b"{}", b'{"id": "x"}', b"nope", b"[]"])
def test_a_payload_without_product_text_raises(payload):
    with pytest.raises(ParseError):
        parse_product(payload)


@pytest.mark.parametrize("payload", [b"nope", b"[]"])
def test_product_list_errors(payload):
    with pytest.raises(ParseError):
        parse_product_list(payload)
