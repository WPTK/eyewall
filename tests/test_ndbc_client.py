from pathlib import Path

import pytest
import respx

from eyewall.ndbc.client import (
    LATEST_OBS_URL,
    STATIONS_URL,
    NdbcClient,
    five_day_url,
    monthly_url,
    previous_month_url,
    realtime_url,
    yearly_url,
)
from eyewall.net import HttpError, new_client, user_agent

FIXTURES = Path(__file__).parent / "fixtures" / "ndbc"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_station_file_urls():
    assert five_day_url("41010") == "https://www.ndbc.noaa.gov/data/5day2/41010_5day.txt"
    assert five_day_url("trdf1", "supl") == "https://www.ndbc.noaa.gov/data/5day2/TRDF1_5day.supl"
    assert five_day_url("41010", "spec").endswith("/41010_5day.spec")
    assert realtime_url("trdf1") == "https://www.ndbc.noaa.gov/data/realtime2/TRDF1.txt"


def test_historical_urls_use_lower_case_ids():
    assert yearly_url("41025", 2025) == "https://www.ndbc.noaa.gov/data/historical/stdmet/41025h2025.txt.gz"
    assert yearly_url("TRDF1", 2025).endswith("/trdf1h2025.txt.gz")
    assert monthly_url("41010", 8, 2026) == "https://www.ndbc.noaa.gov/data/stdmet/Aug/4101082026.txt.gz"
    assert previous_month_url("41010", 9) == "https://www.ndbc.noaa.gov/data/stdmet/Sep/41010.txt"


@pytest.mark.parametrize("month", [0, 10, 11, 12, 13])
def test_monthly_names_that_have_not_been_observed_are_refused(month):
    with pytest.raises(ValueError, match="verified"):
        monthly_url("41010", month, 2026)


def test_previous_month_needs_a_real_month():
    with pytest.raises(ValueError, match="1 to 12"):
        previous_month_url("41010", 13)
    assert previous_month_url("41010", 12).endswith("/Dec/41010.txt")


@pytest.mark.parametrize("bad", ["", "../41010", "41010/x", "41 010", "a" * 11])
def test_odd_station_ids_never_reach_a_url(bad):
    with pytest.raises(ValueError, match="not an NDBC station id"):
        five_day_url(bad)


@respx.mock
async def test_latest_obs_parses_and_sends_the_eyewall_user_agent():
    route = respx.get(LATEST_OBS_URL).respond(
        200, content=fixture_bytes("latest_obs.txt"), headers={"ETag": '"abc"', "Last-Modified": "Sat, 31 Oct 2026"}
    )
    async with new_client() as http:
        response = await NdbcClient(http).latest_obs()
    assert response.status == 200
    assert response.value is not None
    assert len(response.value.items) == 19
    assert (response.etag, response.last_modified) == ('"abc"', "Sat, 31 Oct 2026")
    assert route.calls.last.request.headers["User-Agent"] == user_agent()


@respx.mock
async def test_a_conditional_request_that_comes_back_304_has_no_value_and_keeps_the_validators():
    route = respx.get(LATEST_OBS_URL).respond(304)
    async with new_client() as http:
        response = await NdbcClient(http).latest_obs(etag='"abc"', last_modified="Sat, 31 Oct 2026")
    assert response.not_modified
    assert response.value is None
    assert (response.etag, response.last_modified) == ('"abc"', "Sat, 31 Oct 2026")
    sent = route.calls.last.request.headers
    assert (sent["If-None-Match"], sent["If-Modified-Since"]) == ('"abc"', "Sat, 31 Oct 2026")


@respx.mock
async def test_the_station_catalog_parses():
    respx.get(STATIONS_URL).respond(200, content=fixture_bytes("activestations.xml"))
    async with new_client() as http:
        response = await NdbcClient(http).stations()
    assert response.value is not None
    assert len(response.value.items) == 20


@respx.mock
async def test_the_shared_files_are_not_allowed_to_404():
    respx.get(LATEST_OBS_URL).respond(404)
    async with new_client() as http:
        with pytest.raises(HttpError) as raised:
            await NdbcClient(http).latest_obs()
    assert raised.value.status == 404


@respx.mock
async def test_a_station_series_parses():
    route = respx.get("https://www.ndbc.noaa.gov/data/5day2/41010_5day.txt").respond(
        200, content=fixture_bytes("41010_5day.txt")
    )
    async with new_client() as http:
        response = await NdbcClient(http).series("41010")
    assert response.value is not None
    assert response.value.reporting
    assert len(response.value.observations) == 704
    assert route.call_count == 1


@respx.mock
async def test_the_longer_file_is_fetched_only_when_asked_for():
    route = respx.get("https://www.ndbc.noaa.gov/data/realtime2/41010.txt").respond(
        200, content=fixture_bytes("41010_5day.txt")
    )
    async with new_client() as http:
        response = await NdbcClient(http).series("41010", window="realtime")
    assert route.call_count == 1
    assert response.value is not None
    assert response.value.station_id == "41010"


@respx.mock
async def test_a_dark_buoys_404_is_not_reporting_not_an_error():
    route = respx.get("https://www.ndbc.noaa.gov/data/5day2/42040_5day.txt").respond(404)
    async with new_client() as http:
        response = await NdbcClient(http).series("42040")
    assert route.call_count == 1  # a 404 is final: no retries, no hammering
    assert response.missing
    assert response.value is not None
    assert response.value.station_id == "42040"
    assert response.value.observations == ()
    assert not response.value.reporting


@respx.mock
async def test_a_lower_case_cman_id_asks_for_the_upper_case_file():
    route = respx.get("https://www.ndbc.noaa.gov/data/5day2/TRDF1_5day.txt").respond(404)
    async with new_client() as http:
        response = await NdbcClient(http).series("trdf1")
    assert route.call_count == 1
    assert response.value is not None
    assert response.value.station_id == "TRDF1"


@respx.mock
async def test_supplemental_and_wave_files_parse_and_404_to_empty():
    respx.get("https://www.ndbc.noaa.gov/data/5day2/41010_5day.supl").respond(
        200, content=fixture_bytes("41010_5day.supl")
    )
    respx.get("https://www.ndbc.noaa.gov/data/5day2/41010_5day.spec").respond(
        200, content=fixture_bytes("41010_5day.spec")
    )
    respx.get("https://www.ndbc.noaa.gov/data/5day2/42040_5day.supl").respond(404)
    respx.get("https://www.ndbc.noaa.gov/data/5day2/42040_5day.spec").respond(404)
    async with new_client() as http:
        client = NdbcClient(http)
        supl, spec = await client.supplemental("41010"), await client.waves("41010")
        dark_supl, dark_spec = await client.supplemental("42040"), await client.waves("42040")
    assert supl.value is not None and len(supl.value.items) == 704
    assert spec.value is not None and len(spec.value.items) == 225
    for dark in (dark_supl, dark_spec):
        assert dark.missing
        assert dark.value is not None
        assert dark.value.items == ()


@respx.mock
async def test_historical_files_parse_and_a_missing_month_is_empty():
    respx.get("https://www.ndbc.noaa.gov/data/historical/stdmet/41025h2025.txt.gz").respond(
        200, content=fixture_bytes("41025h2025_erin_week.txt.gz")
    )
    respx.get("https://www.ndbc.noaa.gov/data/stdmet/Sep/4101092026.txt.gz").respond(404)
    async with new_client() as http:
        client = NdbcClient(http)
        year = await client.historical_year("41025", 2025)
        month = await client.historical_month("41010", 9, 2026)
    assert year.value is not None
    assert len(year.value.observations) == 1153
    assert month.missing
    assert month.value is not None
    assert not month.value.reporting
