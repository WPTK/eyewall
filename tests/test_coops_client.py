from datetime import UTC, datetime
from pathlib import Path

import pytest
import respx

from eyewall.coops.client import STATIONS_URL, CoopsClient
from eyewall.coops.data import DATAGETTER_URL
from eyewall.net import HttpError, new_client, user_agent

FIXTURES = Path(__file__).parent / "fixtures" / "coops"


def raw(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


@respx.mock
async def test_water_level_makes_one_request_with_datum_and_application():
    route = respx.get(DATAGETTER_URL).respond(200, content=raw("water_level_recent.json"))
    async with new_client() as http:
        parsed = await CoopsClient(http).water_level("8721604", date="recent")
    assert route.call_count == 1
    params = route.calls.last.request.url.params
    assert dict(params) == {
        "product": "water_level",
        "station": "8721604",
        "units": "english",
        "time_zone": "gmt",
        "format": "json",
        "application": "eyewall",
        "datum": "MLLW",
        "date": "recent",
    }
    assert route.calls.last.request.headers["User-Agent"] == user_agent()
    assert len(parsed.items) == 720
    assert sum(1 for r in parsed.items if r.level_ft is None) == 2


@respx.mock
async def test_the_latest_reading_is_the_default_window():
    route = respx.get(DATAGETTER_URL).respond(200, content=raw("water_level_latest.json"))
    async with new_client() as http:
        parsed = await CoopsClient(http).water_level("8721604")
    assert route.calls.last.request.url.params["date"] == "latest"
    assert len(parsed.items) == 1


@respx.mock
async def test_great_lakes_gauges_can_name_another_datum():
    route = respx.get(DATAGETTER_URL).respond(200, content=raw("water_level_latest.json"))
    async with new_client() as http:
        await CoopsClient(http).water_level("9063063", datum="IGLD")
    assert route.calls.last.request.url.params["datum"] == "IGLD"


@respx.mock
async def test_predictions_default_to_todays_high_and_low_tides():
    route = respx.get(DATAGETTER_URL).respond(200, content=raw("predictions_hilo.json"))
    async with new_client() as http:
        parsed = await CoopsClient(http).predictions("8721604")
    params = route.calls.last.request.url.params
    assert (params["product"], params["interval"], params["date"], params["datum"]) == (
        "predictions",
        "hilo",
        "today",
        "MLLW",
    )
    assert "range" not in params
    assert [p.kind for p in parsed.items][:2] == ["H", "L"]


@respx.mock
async def test_predictions_can_look_ahead_from_a_moment_in_six_minute_steps():
    route = respx.get(DATAGETTER_URL).respond(200, content=raw("predictions_interval.json"))
    begin = datetime(2026, 10, 31, 0, 0, tzinfo=UTC)
    async with new_client() as http:
        parsed = await CoopsClient(http).predictions("8721604", interval=None, begin=begin, hours=6)
    params = route.calls.last.request.url.params
    assert (params["begin_date"], params["range"]) == ("20261031 00:00", "6")
    assert "interval" not in params
    assert "date" not in params
    assert len(parsed.items) == 61


@respx.mock
async def test_wind_and_pressure_are_separate_single_requests():
    route = respx.get(DATAGETTER_URL)
    route.side_effect = [
        respx.MockResponse(200, content=raw("wind_recent.json")),
        respx.MockResponse(200, content=raw("air_pressure_recent.json")),
    ]
    async with new_client() as http:
        client = CoopsClient(http)
        wind = await client.wind("8721604", hours=3)
        pressure = await client.air_pressure("8721604", hours=3)
    assert route.call_count == 2
    assert route.calls[0].request.url.params["product"] == "wind"
    assert route.calls[1].request.url.params["product"] == "air_pressure"
    assert "datum" not in route.calls[0].request.url.params
    assert wind.items[0].speed_kt == 7.58
    assert pressure.items[0].pressure_mb == 1018.4


@respx.mock
async def test_a_gauge_without_the_product_is_an_empty_result_with_a_message_not_an_error():
    respx.get(DATAGETTER_URL).respond(200, content=raw("wind_no_data.json"))
    async with new_client() as http:
        parsed = await CoopsClient(http).wind("8735523", date="latest")
    assert parsed.items == ()
    assert parsed.message is not None
    assert parsed.message.startswith("No data was found")


@respx.mock
async def test_a_400_for_a_missing_datum_raises_with_the_status():
    respx.get(DATAGETTER_URL).respond(400, content=raw("error_no_datum.json"))
    async with new_client() as http:
        with pytest.raises(HttpError) as raised:
            await CoopsClient(http).water_level("8721604")
    assert raised.value.status == 400


@respx.mock
async def test_station_listings_ask_for_their_type_and_tag_the_stations():
    route = respx.get(STATIONS_URL)
    route.side_effect = [
        respx.MockResponse(200, content=raw("stations_waterlevels.json")),
        respx.MockResponse(200, content=raw("stations_met.json")),
    ]
    async with new_client() as http:
        client = CoopsClient(http)
        gauges = (await client.stations()).value
        met = (await client.stations("met")).value
    assert [call.request.url.params["type"] for call in route.calls] == ["waterlevels", "met"]
    assert all(s.products == {"water_level"} for s in gauges.items)
    assert all(s.products == {"met"} for s in met.items)


@respx.mock
async def test_all_stations_merges_both_listings_with_two_requests():
    route = respx.get(STATIONS_URL)
    route.side_effect = [
        respx.MockResponse(200, content=raw("stations_waterlevels.json")),
        respx.MockResponse(200, content=raw("stations_met.json")),
    ]
    async with new_client() as http:
        merged = await CoopsClient(http).all_stations()
    assert route.call_count == 2
    by_id = {s.id: s for s in merged}
    assert by_id["8721604"].products == {"water_level", "met"}
    assert by_id["8735523"].products == {"water_level"}


async def test_an_unknown_listing_is_refused_before_any_request():
    async with new_client() as http:
        with pytest.raises(ValueError, match="unknown station listing"):
            await CoopsClient(http).stations("currents")


async def test_a_bad_station_id_is_refused_before_any_request():
    async with new_client() as http:
        with pytest.raises(ValueError, match="not a CO-OPS station id"):
            await CoopsClient(http).wind("8721604&x=1")


@respx.mock
async def test_a_conditional_station_listing_that_comes_back_304_has_no_value_and_keeps_the_validators():
    route = respx.get(STATIONS_URL).respond(304)
    async with new_client() as http:
        response = await CoopsClient(http).stations(etag='"abc"', last_modified="Sat, 31 Oct 2026")
    assert response.not_modified
    assert response.value is None
    assert (response.etag, response.last_modified) == ('"abc"', "Sat, 31 Oct 2026")
    sent = route.calls.last.request.headers
    assert (sent["If-None-Match"], sent["If-Modified-Since"]) == ('"abc"', "Sat, 31 Oct 2026")


@respx.mock
async def test_a_station_listing_returns_the_validators_it_was_sent():
    respx.get(STATIONS_URL).respond(
        200, content=raw("stations_waterlevels.json"), headers={"ETag": '"v2"', "Last-Modified": "Sun, 01 Nov 2026"}
    )
    async with new_client() as http:
        response = await CoopsClient(http).stations()
    assert response.value is not None and response.value.items
    assert (response.etag, response.last_modified) == ('"v2"', "Sun, 01 Nov 2026")
