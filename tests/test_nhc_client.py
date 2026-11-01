import json
from dataclasses import replace

import httpx
import pytest
import respx

from eyewall.models.storm import AdvNum, Basin
from eyewall.net import HttpError, new_client, user_agent
from eyewall.providers.base import ParseError, StormProvider
from eyewall.providers.nhc import ids
from eyewall.providers.nhc.client import NhcClient
from eyewall.providers.nhc.current import parse_current_storms
from eyewall.providers.nhc.ids import ProductKind
from tests.nhc_fixtures import gis_bytes, nhc_bytes, nhc_text

AT5 = ids.parse_bin("AT5")


async def no_sleep(seconds: float) -> None:
    return None


@pytest.fixture
async def nhc():
    # A transport with TLS verification off skips loading the certificate bundle, which costs 0.25 s a test; respx
    # intercepts every request anyway. The User-Agent and timeouts still come from eyewall.net.
    async with new_client(transport=httpx.AsyncHTTPTransport(verify=False)) as http:
        yield NhcClient(http, retries=0, sleep=no_sleep)


def _erin():
    return parse_current_storms(nhc_bytes("current/populated.json")).by_id("al052025")


def _serve_erin_text(public="tcp/erin_030.txt"):
    respx.get(ids.tgftp_url(ProductKind.TCM, AT5)).respond(200, content=nhc_bytes("tcm/erin_030.txt"))
    respx.get(ids.tgftp_url(ProductKind.TCP, AT5)).respond(200, content=nhc_bytes(public))
    respx.get(ids.tgftp_url(ProductKind.TCD, AT5)).respond(200, content=nhc_bytes("tcd/erin_030.txt"))
    respx.get(ids.tgftp_url(ProductKind.PWS, AT5)).respond(200, content=nhc_bytes("pws/erin_030.txt"))


def _api_product(text: str, product_id: str = "abc-123") -> bytes:
    return json.dumps(
        {"id": product_id, "productCode": "TCM", "issuanceTime": "2026-10-30T02:31:00+00:00", "productText": text}
    ).encode()


async def test_the_client_satisfies_the_provider_protocol(nhc):
    provider: StormProvider = nhc
    assert provider.name == "NHC"


# ---- fetch layer --------------------------------------------------------------------------------------------------


@respx.mock
async def test_current_storms_are_parsed_and_sent_with_the_user_agent(nhc):
    route = respx.get(ids.CURRENT_STORMS_URL).respond(
        200, content=nhc_bytes("current/populated.json"), headers={"ETag": '"abc"', "Last-Modified": "Sat, 31 Oct 2026"}
    )
    response = await nhc.fetch_current_storms()
    assert [s.id for s in response.value.storms] == ["al052025", "al082024", "al062026", "ep152026"]
    assert response.fetched.etag == '"abc"'
    assert response.fetched.last_modified == "Sat, 31 Oct 2026"
    assert not response.not_modified and not response.missing
    assert route.calls.last.request.headers["User-Agent"] == user_agent()


@respx.mock
async def test_conditional_request_sends_validators_and_a_304_has_no_value(nhc):
    route = respx.get(ids.CURRENT_STORMS_URL).respond(304)
    response = await nhc.fetch_current_storms(etag='"abc"', last_modified="Sat, 31 Oct 2026")
    assert response.not_modified
    assert response.value is None
    sent = route.calls.last.request.headers
    assert sent["If-None-Match"] == '"abc"'
    assert sent["If-Modified-Since"] == "Sat, 31 Oct 2026"


@respx.mock
async def test_current_storms_error_is_raised_not_hidden(nhc):
    respx.get(ids.CURRENT_STORMS_URL).respond(503)
    with pytest.raises(HttpError):
        await nhc.fetch_current_storms()
    respx.get(ids.CURRENT_STORMS_URL).respond(404)
    with pytest.raises(HttpError):
        await nhc.fetch_current_storms()


@respx.mock
async def test_the_provider_level_storms_call_returns_an_empty_list_on_a_quiet_day(nhc):
    respx.get(ids.CURRENT_STORMS_URL).respond(200, content=nhc_bytes("current/empty.json"))
    assert (await nhc.storms()).storms == ()


@respx.mock
async def test_tgftp_text_is_returned_raw(nhc):
    respx.get(ids.tgftp_url(ProductKind.TCM, AT5)).respond(200, content=nhc_bytes("tcm/erin_030.txt"))
    response = await nhc.fetch_text(ProductKind.TCM, AT5)
    assert response.source == "tgftp"
    assert response.value == nhc_text("tcm/erin_030.txt")


@respx.mock
async def test_a_tgftp_failure_falls_back_to_api_weather_gov_by_bin(nhc):
    ep2 = ids.parse_bin("EP2")
    respx.get(ids.tgftp_url(ProductKind.TCM, ep2)).respond(503)
    listing = respx.get(ids.api_products_url(ProductKind.TCM, "EP2")).respond(
        200, content=nhc_bytes("api/products_tcm_ep2.json")
    )
    product = respx.get(ids.api_product_url("cb19ea7f-e12e-49d6-ad66-8e64a538f4e2")).respond(
        200, content=_api_product(nhc_text("tcm/vance_035.txt"), "cb19ea7f-e12e-49d6-ad66-8e64a538f4e2")
    )
    response = await nhc.fetch_text(ProductKind.TCM, ep2)
    assert response.source == "api"
    assert response.value == nhc_text("tcm/vance_035.txt")
    assert listing.called and product.called  # the newest product in the list, not the first by luck


@respx.mock
async def test_a_missing_tgftp_file_also_falls_back(nhc):
    respx.get(ids.tgftp_url(ProductKind.TCM, AT5)).respond(404)
    respx.get(ids.api_products_url(ProductKind.TCM, "AT5")).respond(200, content=b'{"@graph": []}')
    response = await nhc.fetch_text(ProductKind.TCM, AT5)
    assert response.value is None
    assert response.source == "api"


@respx.mock
async def test_an_empty_tgftp_file_falls_back(nhc):
    respx.get(ids.tgftp_url(ProductKind.TCM, AT5)).respond(200, content=b"  \n")
    respx.get(ids.api_products_url(ProductKind.TCM, "AT5")).respond(200, content=b'{"@graph": []}')
    assert (await nhc.fetch_text(ProductKind.TCM, AT5)).source == "api"


@respx.mock
async def test_without_fallback_a_failure_raises_and_a_404_is_missing(nhc):
    route = respx.get(ids.tgftp_url(ProductKind.TCM, AT5)).respond(503)
    with pytest.raises(HttpError):
        await nhc.fetch_text(ProductKind.TCM, AT5, fallback=False)
    route.respond(404)
    response = await nhc.fetch_text(ProductKind.TCM, AT5, fallback=False)
    assert response.missing and response.value is None


@respx.mock
async def test_a_304_from_tgftp_does_not_trigger_the_fallback(nhc):
    respx.get(ids.tgftp_url(ProductKind.TCM, AT5)).respond(304)
    response = await nhc.fetch_text(ProductKind.TCM, AT5, etag='"x"')
    assert response.not_modified
    assert response.source == "tgftp"


@respx.mock
async def test_outlook_text_uses_the_basin_location_on_fallback(nhc):
    respx.get(ids.outlook_url(Basin.AL)).respond(503)
    respx.get(ids.api_products_url(ProductKind.TWO, "AT")).respond(200, content=nhc_bytes("api/products_two_at.json"))
    respx.get(ids.api_product_url("3ae4e478-d4e6-4c83-b209-60fbef9a5e73")).respond(
        200, content=nhc_bytes("api/product_two_at.json")
    )
    response = await nhc.fetch_outlook_text(Basin.AL)
    assert response.source == "api"
    assert "formation is not expected" in response.value


@respx.mock
async def test_alerts_request_lists_the_tropical_events(nhc):
    route = respx.get(ids.alerts_url()).respond(200, content=nhc_bytes("api/alerts_populated.json"))
    response = await nhc.fetch_alerts()
    assert len(response.value.alerts) == 2
    sent = route.calls.last.request.url.params["event"]
    assert sent.split(",")[0] == "Hurricane Warning"
    assert "Storm Surge Watch" in sent


@respx.mock
async def test_gis_floater_and_index_fetches(nhc):
    zip_url = "https://www.nhc.noaa.gov/gis/forecast/archive/al052025_5day_030.zip"
    respx.get(zip_url).respond(200, content=gis_bytes("erin_5day_030.zip"))
    respx.get("https://www.nhc.noaa.gov/gis/forecast/archive/al052025_fcst_030.zip").respond(
        200, content=gis_bytes("erin_fcst_030.zip")
    )
    respx.get(ids.best_track_zip_url("al052025")).respond(200, content=gis_bytes("erin_best_track.zip"))
    respx.get(ids.BTK_INDEX_URL).respond(200, content=nhc_bytes("atcf/btk_index.html"))
    respx.get(ids.bdeck_url("al052025")).respond(200, content=nhc_bytes("atcf/bal052025.dat.gz"))
    respx.get(ids.floater_url()).respond(200, content=nhc_bytes("graphics/floater_root.html"))
    respx.get(ids.floater_url("cp032026")).respond(200, content=nhc_bytes("graphics/floater_cp032026.html"))
    respx.get(ids.floater_url("cp032026", "GEOCOLOR")).respond(
        200, content=nhc_bytes("graphics/floater_cp032026_geocolor.html")
    )
    assert len((await nhc.fetch_forecast_gis(zip_url)).value.cone[0]) == 2088
    assert (
        len(
            (
                await nhc.fetch_radii_gis("https://www.nhc.noaa.gov/gis/forecast/archive/al052025_fcst_030.zip")
            ).value.forecast
        )
        == 25
    )
    assert len((await nhc.fetch_best_track_gis(ids.best_track_zip_url("al052025"))).value.points) == 68
    assert len((await nhc.fetch_bdeck_index()).value) == 35
    assert len((await nhc.fetch_bdeck("al052025")).value.fixes) == 68
    assert len((await nhc.fetch_floater_storms()).value) == 35
    assert "GEOCOLOR" in (await nhc.fetch_floater_products("CP032026")).value
    assert (await nhc.fetch_floater_product("CP032026", "GEOCOLOR")).value.loop_url.endswith(
        "CP032026-GEOCOLOR-1000x1000.gif"
    )


@respx.mock
async def test_a_404_for_a_zip_is_a_missing_response(nhc):
    respx.get("https://www.nhc.noaa.gov/gis/forecast/archive/al052025_5day_031.zip").respond(404)
    response = await nhc.fetch_forecast_gis("https://www.nhc.noaa.gov/gis/forecast/archive/al052025_5day_031.zip")
    assert response.missing and response.value is None


# ---- provider layer -----------------------------------------------------------------------------------------------


@respx.mock
async def test_advisory_returns_every_product_that_matches_the_storms_advisory(nhc):
    _serve_erin_text()
    erin = _erin()
    # The recorded TCP is advisory 30, but this storm's public advisory is already the intermediate 30A.
    advisory = await nhc.advisory(erin)
    assert advisory.forecast.adv_num == AdvNum(30)
    assert advisory.discussion.adv_num == AdvNum(30)
    assert advisory.wind_probabilities.adv_num == AdvNum(30)
    assert advisory.public is None  # stale: 30 is not 30A
    assert advisory.adv_num == AdvNum(30)


@respx.mock
async def test_advisory_includes_the_public_advisory_when_its_number_matches(nhc):
    _serve_erin_text()
    erin = _erin()
    current = replace(erin, public_advisory=replace(erin.public_advisory, adv_num=AdvNum(30)))
    advisory = await nhc.advisory(current)
    assert advisory.public.adv_num == AdvNum(30)
    assert advisory.public.headline.startswith("TROPICAL STORM AND STORM SURGE WATCHES")


@respx.mock
async def test_a_finished_storms_last_advisory_is_never_applied_to_a_live_storm(nhc):
    # tgftp keeps the previous storm's last advisory in the bin: Fay's text is served for the AT5 bin.
    respx.get(ids.tgftp_url(ProductKind.TCM, AT5)).respond(200, content=nhc_bytes("tcm/fay_039.txt"))
    respx.get(ids.tgftp_url(ProductKind.TCP, AT5)).respond(200, content=nhc_bytes("tcp/fay_039.txt"))
    respx.get(ids.tgftp_url(ProductKind.TCD, AT5)).respond(200, content=nhc_bytes("tcd/fay_039.txt"))
    respx.get(ids.tgftp_url(ProductKind.PWS, AT5)).respond(200, content=nhc_bytes("pws/fay_039.txt"))
    advisory = await nhc.advisory(_erin())
    assert (advisory.forecast, advisory.public, advisory.discussion, advisory.wind_probabilities) == (
        None,
        None,
        None,
        None,
    )
    assert advisory.adv_num is None


@respx.mock
async def test_advisory_degrades_per_product_when_fetches_or_parses_fail(nhc):
    respx.get(ids.tgftp_url(ProductKind.TCM, AT5)).respond(200, content=nhc_bytes("tcm/erin_030.txt"))
    respx.get(ids.tgftp_url(ProductKind.TCP, AT5)).respond(503)
    respx.get(ids.api_products_url(ProductKind.TCP, "AT5")).respond(503)
    respx.get(ids.tgftp_url(ProductKind.TCD, AT5)).respond(200, content=b"<html>not a discussion</html>")
    respx.get(ids.tgftp_url(ProductKind.PWS, AT5)).respond(404)
    respx.get(ids.api_products_url(ProductKind.PWS, "AT5")).respond(200, content=b'{"@graph": []}')
    advisory = await nhc.advisory(_erin())
    assert advisory.forecast is not None
    assert (advisory.public, advisory.discussion, advisory.wind_probabilities) == (None, None, None)


@respx.mock
async def test_a_storm_without_a_bin_or_references_makes_no_requests(nhc):
    storm = replace(_erin(), bin_number=None)
    advisory = await nhc.advisory(storm)
    assert advisory.forecast is None
    assert respx.calls.call_count == 0
    bare = replace(_erin(), forecast_track=None, track_cone=None)
    assert await nhc.forecast_gis(bare) is None
    assert respx.calls.call_count == 0


@respx.mock
async def test_forecast_gis_follows_the_storms_zip_url(nhc):
    erin = _erin()
    assert erin.forecast_track.zip_url.endswith("_5day_030A.zip")
    respx.get(erin.forecast_track.zip_url).respond(200, content=gis_bytes("erin_5day_030A.zip"))
    gis = await nhc.forecast_gis(erin)
    assert gis.adv_num == AdvNum(30, "A")


@respx.mock
async def test_forecast_gis_fails_when_the_zip_is_missing_or_broken(nhc):
    """A failure is raised, not hidden as None, so the poller asks again."""
    erin = _erin()
    route = respx.get(erin.forecast_track.zip_url).respond(404)
    with pytest.raises(HttpError):
        await nhc.forecast_gis(erin)
    route.respond(200, content=b"<html>oops</html>")
    with pytest.raises(ParseError):
        await nhc.forecast_gis(erin)
    route.respond(503)
    with pytest.raises(HttpError):
        await nhc.forecast_gis(erin)


@respx.mock
async def test_track_is_the_storms_bdeck_keyed_by_id(nhc):
    nolo = parse_current_storms(nhc_bytes("current/populated.json")).by_id("ep152026")
    route = respx.get("https://ftp.nhc.noaa.gov/atcf/btk/bep152026.dat").respond(
        200, content=nhc_bytes("atcf/bep222026.dat")
    )
    track = await nhc.track(nolo)
    assert route.called
    assert track.number == 22  # whatever the file holds; the URL is built from the ep id, not the CP bin
    route.respond(404)
    with pytest.raises(HttpError):  # linked but not posted yet: the poller asks again
        await nhc.track(nolo)


@respx.mock
async def test_outlook_text_collects_the_basins_and_a_failed_one_raises_instead_of_being_left_out(nhc):
    respx.get(ids.outlook_url(Basin.AL)).respond(200, content=nhc_bytes("two/at_20261031.txt"))
    respx.get(ids.outlook_url(Basin.EP)).respond(200, content=nhc_bytes("two/ep_20261031.txt"))
    cp = respx.get(ids.outlook_url(Basin.CP)).respond(404)
    outlooks = await nhc.outlook_text()
    assert len(outlooks) == 2  # a basin NOAA has no text for is no outlook
    assert outlooks[0].quiet
    assert outlooks[1].areas[0].chance_7d.percent == 40
    cp.respond(200, content=b"<html>garbage</html>")  # a partial outlook would replace the good one
    with pytest.raises(ParseError):
        await nhc.outlook_text()


@respx.mock
async def test_outlook_gis_is_empty_for_a_missing_zip_and_a_failed_download_raises(nhc):
    route = respx.get(ids.GTWO_ZIP_URL).respond(200, content=gis_bytes("gtwo_20250919.zip"))
    assert len((await nhc.outlook_gis()).systems) == 3
    route.respond(404)
    assert (await nhc.outlook_gis()).empty
    route.respond(500)
    with pytest.raises(HttpError):
        await nhc.outlook_gis()


@respx.mock
async def test_graphics_uses_the_landing_url_from_the_storm_and_falls_back_to_the_bin(nhc):
    erin = _erin()
    assert erin.forecast_graphics.url == "https://www.nhc.noaa.gov/graphics_at5.shtml"
    route = respx.get(erin.forecast_graphics.url).respond(
        200, content=nhc_bytes("graphics/landing_active_modelled.html")
    )
    links = await nhc.graphics(erin)
    assert len(links) == 10
    assert route.call_count == 1
    without_url = replace(erin, forecast_graphics=None)
    await nhc.graphics(without_url)
    assert route.call_count == 2  # the bin gives the same graphics_at5 URL
    assert await nhc.graphics(replace(erin, forecast_graphics=None, bin_number=None)) == ()


@respx.mock
async def test_graphics_failure_is_raised(nhc):
    erin = _erin()
    respx.get(erin.forecast_graphics.url).respond(500)
    with pytest.raises(HttpError):
        await nhc.graphics(erin)
