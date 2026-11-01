"""Feed failures that used to be hidden: what the poller, the live source and the cache do when NOAA answers badly."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from eyewall.clock import VirtualClock
from eyewall.config import Config
from eyewall.models.obs import TideStation
from eyewall.models.storm import CurrentStorms
from eyewall.net import FetchError, HttpError, NetworkError, RateLimited
from eyewall.poll import MAX_TIDE_GAUGES, Poller, no_sleep
from eyewall.providers.base import ParseError
from eyewall.providers.nhc.client import NhcClient
from eyewall.providers.nhc.current import parse_current_storms
from eyewall.sources import protocol
from eyewall.sources.cache import Cache, CachingTransport
from eyewall.sources.live import LiveSource
from eyewall.state.alerts import AlertEngine
from eyewall.state.store import Store
from tests.nhc_fixtures import nhc_bytes
from tests.state_support import T0, FakeSource, advisories, gauge, make_storm, obs, series, station

NOW = datetime(2026, 9, 29, 22, tzinfo=UTC)
FIXTURES = Path(__file__).parent / "fixtures"


def build(source=None):
    clock = VirtualClock(T0)
    source = source or FakeSource(clock)
    source.clock = clock
    config = Config()
    store = Store(config)
    got = []
    poller = Poller(
        source, store, AlertEngine(config.alerts), config.poll, clock=clock, sleep=no_sleep, on_events=got.extend
    )
    return poller, source, store, clock, got


# ---- the poller ---------------------------------------------------------------------------------------------------


async def test_only_the_product_answered_from_the_disk_cache_is_asked_for_again():
    poller, source, store, clock, _ = build()
    source.set_storm("1")
    source.texts["1"] = advisories("1")
    source.cached_products.add("forecast_gis")  # the cone came from the cache; the radii, track and graphics did not
    await poller.tick()
    assert store.storms["al012026"].fetched_key is None
    source.cached_products.clear()
    clock.advance(300)
    await poller.tick()
    assert store.storms["al012026"].fetched_key is not None
    assert source.count("forecast_gis") == 2
    assert source.count("radii_gis") == source.count("track") == source.count("graphics") == 1


class PerGauge(FakeSource):
    """Each gauge answers with its own HTTP status."""

    statuses: dict[str, int] = {}

    async def coops_series(self, station, datum):
        raise HttpError("fake://coops", self.statuses[station.id])


@pytest.mark.parametrize(
    ("statuses", "down"),
    [
        ({"8000001": 400, "8000002": 503}, True),  # a mix of a permanent answer and an outage is an outage
        ({"8000001": 403, "8000002": 403}, True),  # NOAA blocking us is not a station's answer
        ({"8000001": 401, "8000002": 408}, True),
        ({"8000001": 400, "8000002": 404}, False),  # every gauge answered for good
        ({"8000001": 410, "8000002": 400}, False),
    ],
)
async def test_which_http_failures_make_the_tide_feed_down(statuses, down):
    PerGauge.statuses = statuses
    poller, source, *_ = build(PerGauge(VirtualClock(T0)))
    source.tide_stations = (gauge("8000001", 25.5, -75.5), gauge("8000002", 25.6, -75.6))
    source.set_storm("1")
    await poller.poll_feed(protocol.STORMS)
    result = await poller.poll_feed(protocol.TIDES)
    assert result.ok is not down


class AllSeriesFail(FakeSource):
    async def ndbc_series(self, station_id):
        raise FetchError("fake://ndbc", "network down")

    async def satellite(self, storm):
        raise FetchError("fake://satellite", "network down")

    async def coops_series(self, station, datum):
        raise FetchError("fake://coops", "network down")


async def test_a_feed_whose_every_request_failed_reports_the_failure_and_backs_off():
    poller, source, *_ = build(AllSeriesFail(VirtualClock(T0)))
    source.stations = (station("41047", 26.0, -75.5),)
    source.tide_stations = (gauge("8000001", 25.5, -75.5),)
    source.set_storm("1")
    source.texts["1"] = advisories("1")
    await poller.tick()
    for feed in (protocol.BUOYS, protocol.TIDES, protocol.SATELLITE):
        fresh = poller.freshness(feed)
        assert fresh.failures == 1, feed
        assert poller.delay(feed) > poller.interval(feed)


async def test_buoys_read_from_the_cache_raise_no_stopped_reporting_alert():
    poller, source, _store, clock, got = build()
    source.stations = (station("41047", 26.0, -75.5),)
    source.buoy_series["41047"] = series("41047", obs(T0, 40))
    source.set_storm("1")
    source.texts["1"] = advisories("1")
    source.cached.add(protocol.BUOYS)
    clock.advance(4 * 3600)  # the newest row is hours old: a live buoy this quiet would be reported as silent
    source.current = CurrentStorms((make_storm("1", updated=clock.now()),))
    await poller.poll_feed(protocol.STORMS)
    got.clear()
    result = await poller.poll_feed(protocol.BUOYS)
    assert result.events == ()
    assert not any(e.kind.value == "buoy_silent" for e in got)


async def test_each_storm_gets_gauges_when_the_first_storm_alone_could_fill_the_cap():
    poller, source, store, _clock, _ = build()
    source.tide_stations = (
        *(gauge(f"80000{i:02d}", 25.0 + i * 0.01, -75.0) for i in range(MAX_TIDE_GAUGES + 4)),
        gauge("9000001", 40.0, -60.0),
    )
    source.current = CurrentStorms(
        (make_storm("1"), make_storm("1", storm_id="al022026", name="Bea", lat=40.0, lon=-60.5))
    )
    await poller.poll_feed(protocol.STORMS)
    await poller.poll_feed(protocol.TIDES)
    assert "9000001" in store.tide_series
    assert len(store.tide_series) == MAX_TIDE_GAUGES


async def test_a_buoy_that_falls_out_of_the_series_cap_loses_its_frozen_series(monkeypatch):
    monkeypatch.setattr("eyewall.poll.MAX_BUOY_SERIES", 1)
    poller, source, store, _clock, _ = build()
    source.stations = (station("99991", 26.0, -75.5), station("99992", 26.5, -75.5))
    for sid in ("99991", "99992"):
        source.buoy_series[sid] = series(sid, obs(T0, 40))
    source.current = CurrentStorms((make_storm("1", lat=26.45, lon=-75.5),))
    await poller.poll_feed(protocol.STORMS)
    await poller.poll_feed(protocol.BUOYS)
    assert set(store.series) == {"99992"}  # the nearer one only
    source.current = CurrentStorms((make_storm("1", lat=26.05, lon=-75.5, updated=T0 + timedelta(hours=1)),))
    await poller.poll_feed(protocol.STORMS)
    await poller.poll_feed(protocol.BUOYS)
    assert set(store.series) == {"99991"}  # the other is no longer refreshed, so it is not kept to go "silent"


# ---- the client ---------------------------------------------------------------------------------------------------


async def tgftp_behind_api_current(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "tgftp" in url:
        return httpx.Response(200, content=nhc_bytes("tcm/erin_046.txt"))  # the previous advisory's text
    if url.startswith("https://api.weather.gov/products/types/"):
        return httpx.Response(200, content=nhc_bytes("api/products_tcm_ep2.json"))
    return httpx.Response(
        200, content=json.dumps({"id": "x", "productText": nhc_bytes("tcm/erin_030.txt").decode()}).encode()
    )


async def test_the_api_copy_is_asked_for_when_tgftp_serves_the_previous_advisory():
    storm = parse_current_storms(nhc_bytes("current/populated.json")).by_id("al052025")
    async with httpx.AsyncClient(transport=httpx.MockTransport(tgftp_behind_api_current)) as http:
        nhc = NhcClient(http, retries=0, sleep=no_sleep)
        assert (await nhc.advisory(storm)).forecast is None  # no fallback: the old text is not current, so not used
        found = await nhc.advisory(storm, fallback=True)
    assert found.forecast is not None
    assert found.forecast.adv_num.number == 30


async def test_a_feed_supplied_zip_address_off_noaa_is_not_fetched():
    storm = parse_current_storms(nhc_bytes("current/populated.json")).by_id("al052025")
    assert storm.forecast_track is not None
    seen = []

    def handler(request):
        seen.append(request.url)
        return httpx.Response(200, content=b"")

    from dataclasses import replace

    off = replace(storm.forecast_track, zip_url="https://example.com/big.zip")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(FetchError):
            await NhcClient(http, retries=0, sleep=no_sleep).forecast_gis(replace(storm, forecast_track=off))
    assert seen == []


async def test_a_feed_supplied_zip_that_is_too_big_is_refused(monkeypatch):
    from eyewall.net import TooLarge
    from eyewall.providers.nhc import client

    monkeypatch.setattr(client, "MAX_ZIP_BYTES", 1000)
    storm = parse_current_storms(nhc_bytes("current/populated.json")).by_id("al052025")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * 5000))
    ) as http:
        with pytest.raises(TooLarge):
            await NhcClient(http, retries=0, sleep=no_sleep).forecast_gis(storm)


# ---- the live source ----------------------------------------------------------------------------------------------


def live(handler, tmp_path):
    return LiveSource(cache_dir=tmp_path, transport=httpx.MockTransport(handler), clock=VirtualClock(NOW))


@pytest.mark.parametrize("call", ["ndbc_stations", "ndbc_latest", "coops_stations"])
async def test_a_200_maintenance_page_raises_so_the_good_listing_is_kept(tmp_path, call):
    source = live(lambda r: httpx.Response(200, content=b"<html>down for maintenance</html>"), tmp_path)
    try:
        with pytest.raises(ParseError):
            await getattr(source, call)()
    finally:
        await source.aclose()


async def test_an_html_buoy_file_raises_instead_of_an_empty_series(tmp_path):
    source = live(lambda r: httpx.Response(200, content=b"<html>\n<body>down</body>\n</html>"), tmp_path)
    try:
        with pytest.raises(ParseError):
            await source.ndbc_series("41002")
    finally:
        await source.aclose()


@pytest.mark.parametrize(
    ("failure", "remembered"),
    [
        (NetworkError("u", "timed out"), False),
        (HttpError("u", 503), False),
        (RateLimited("u", 5.0), False),
        (HttpError("u", 400), True),
    ],
)
async def test_only_a_4xx_prediction_failure_is_remembered_for_the_day(tmp_path, failure, remembered):
    source = live(lambda r: httpx.Response(200, json={}), tmp_path)
    asked = []

    async def predictions(*args, **kwargs):
        asked.append(1)
        raise failure

    source.coops.predictions = predictions  # type: ignore[method-assign]
    gauge_ = TideStation("8000001", "Gauge", 25.0, -75.0)
    try:
        for _ in range(2):
            assert (await source._predictions_for(gauge_, "MLLW")).message
    finally:
        await source.aclose()
    assert len(asked) == (1 if remembered else 2)


async def test_an_image_the_cache_could_only_stand_in_for_is_refused_and_does_not_mark_the_poll_stale(tmp_path):
    state = {"fail": False}

    def handler(request):
        if state["fail"]:
            return httpx.Response(503)
        return httpx.Response(200, content=b"\x89PNG\r\n\x1a\n" + b"0" * 64, headers={"content-type": "image/png"})

    source = live(handler, tmp_path)
    url = "https://www.nhc.noaa.gov/storm_graphics/AT05/AL052025_5day_cone.png"
    try:
        await source.image(url)
        source.start_poll(protocol.STORMS)
        state["fail"] = True
        with pytest.raises(FetchError):  # the old copy may be the previous advisory's picture
            await source.image(url)
        assert not source.stale(protocol.STORMS)
        assert source.throttle(protocol.STORMS) is None
    finally:
        await source.aclose()


# ---- the cache ----------------------------------------------------------------------------------------------------


class DropsDuringBody(httpx.AsyncBaseTransport):
    def __init__(self):
        self.drop = False

    async def handle_async_request(self, request):
        if not self.drop:
            return httpx.Response(200, content=b"good copy", headers={"etag": '"v1"'}, request=request)

        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b"par"
                raise httpx.ReadError("connection lost")

        return httpx.Response(200, stream=Stream(), request=request)


async def test_a_connection_lost_during_the_body_is_answered_from_the_cached_copy(tmp_path):
    inner = DropsDuringBody()
    transport = CachingTransport(Cache(tmp_path), inner)
    async with httpx.AsyncClient(transport=transport) as http:
        assert (await http.get("https://www.nhc.noaa.gov/a")).content == b"good copy"
        inner.drop = True
        assert (await http.get("https://www.nhc.noaa.gov/a")).content == b"good copy"
        with pytest.raises(httpx.ReadError):  # nothing cached for this address: the failure propagates
            await http.get("https://www.nhc.noaa.gov/b")


def test_prune_removes_a_body_whose_metadata_is_gone(tmp_path):
    cache = Cache(tmp_path)
    cache.store("https://www.nhc.noaa.gov/a", b"x", httpx.Headers(), NOW)
    meta, body = cache._paths("https://www.nhc.noaa.gov/a")
    meta.unlink()
    assert cache.prune(timedelta(days=7), NOW) == 1
    assert not body.exists()


def outlook_handler(bad_ep=False):
    def handler(request):
        url = str(request.url)
        if url.endswith("abnt20.knhc.two.at.txt"):
            return httpx.Response(200, content=nhc_bytes("two/at_20261031.txt"))
        if url.endswith("abpz20.knhc.two.ep.txt"):
            return httpx.Response(
                200, content=b"<html>not an outlook</html>" if bad_ep else nhc_bytes("two/ep_20261031.txt")
            )
        if url.endswith("acpn50.phfo.two.cp.txt"):
            return httpx.Response(200, content=nhc_bytes("two/cp_20261031.txt"))
        return httpx.Response(404)

    return handler


async def test_one_basin_text_that_cannot_be_parsed_keeps_its_last_outlook_and_reports_the_error(tmp_path):
    bad = {"ep": False}
    source = live(lambda r: outlook_handler(bad["ep"])(r), tmp_path)
    try:
        source.start_poll(protocol.OUTLOOK)
        first = await source.outlook()
        assert len(first.texts) == 3
        assert source.throttle(protocol.OUTLOOK) is None
        bad["ep"] = True
        source.start_poll(protocol.OUTLOOK)
        second = await source.outlook()
        assert len(second.texts) == 3  # the East Pacific text from the last good poll, the others fresh
        failure = source.throttle(protocol.OUTLOOK)
        assert failure is not None
        assert "ParseError" in str(failure[0])
    finally:
        await source.aclose()


async def test_an_outlook_part_that_never_succeeded_is_unknown_not_empty(tmp_path):
    """The first poll with a failing basin applies nothing, so the screen keeps waiting and no later poll reads the
    basin's recovery as a new outlook; the next good poll is the baseline."""
    bad = {"ep": True}
    source = live(lambda r: outlook_handler(bad["ep"])(r), tmp_path)
    store = Store(Config())
    poller = Poller(source, store, AlertEngine(), Config().poll, clock=VirtualClock(T0), sleep=no_sleep)
    try:
        result = await poller.poll_feed(protocol.OUTLOOK)
        assert not result.ok
        assert poller.freshness(protocol.OUTLOOK).failures == 1
        assert store.outlook is None  # unknown, not "no outlook for the enabled basins"
        bad["ep"] = False
        result = await poller.poll_feed(protocol.OUTLOOK)
    finally:
        await source.aclose()
    assert result.ok
    assert store.outlook is not None and len(store.outlook.texts) == 3
    assert not [e for e in result.events if e.kind.name == "NEW_INVEST"]


def gis_429_handler(retry_after):
    base = outlook_handler()

    def handler(request):
        if "gtwo_shapefiles" in str(request.url):
            return httpx.Response(429, headers={"Retry-After": retry_after})
        return base(request)

    return handler


async def test_a_429_from_an_outlook_part_keeps_its_retry_after(tmp_path):
    source = live(gis_429_handler("3600"), tmp_path)
    source.nhc._sleep = no_sleep  # the request's own retries wait for real
    try:
        source.start_poll(protocol.OUTLOOK)
        with pytest.raises(RateLimited):
            await source.outlook()
        held = source.throttle(protocol.OUTLOOK)
    finally:
        await source.aclose()
    assert held is not None
    assert isinstance(held[0], RateLimited)
    assert held[1] == 3600


async def test_a_cached_answer_retry_after_survives_another_part_failing(tmp_path):
    mode = {"cp": "ok", "ep": "ok"}
    base = outlook_handler()

    def handler(request):
        url = str(request.url)
        if url.endswith("acpn50.phfo.two.cp.txt") and mode["cp"] == "429":
            return httpx.Response(429, headers={"Retry-After": "3600"})
        if url.endswith("abpz20.knhc.two.ep.txt") and mode["ep"] == "junk":
            return httpx.Response(200, content=b"<html>not an outlook</html>")
        return base(request)

    source = live(handler, tmp_path)
    try:
        source.start_poll(protocol.OUTLOOK)
        await source.outlook()
        mode.update(cp="429", ep="junk")
        source.start_poll(protocol.OUTLOOK)
        outlook = await source.outlook()
        held = source.throttle(protocol.OUTLOOK)
    finally:
        await source.aclose()
    assert (
        len(outlook.texts) == 3
    )  # the East Pacific text is the last good one, the Central Pacific came from the cache
    assert held is not None
    assert held[1] == 3600  # the other part's failure did not replace the cached answer's wait


async def test_a_kept_outlook_part_expires_after_two_days(tmp_path):
    bad = {"ep": False}
    clock = VirtualClock(NOW)
    source = LiveSource(
        cache_dir=tmp_path, transport=httpx.MockTransport(lambda r: outlook_handler(bad["ep"])(r)), clock=clock
    )
    try:
        source.start_poll(protocol.OUTLOOK)
        await source.outlook()
        bad["ep"] = True
        clock.advance(47 * 3600)
        source.start_poll(protocol.OUTLOOK)
        assert len((await source.outlook()).texts) == 3  # still within the cap
        clock.advance(2 * 3600)
        source.start_poll(protocol.OUTLOOK)
        with pytest.raises(ParseError):
            await source.outlook()  # kept for too long: unknown again
    finally:
        await source.aclose()


class WrongDatum(FakeSource):
    async def coops_series(self, station, datum):
        raise HttpError("fake://coops", 400)


async def test_a_gauge_without_the_datum_is_not_a_feed_failure():
    poller, source, store, *_ = build(WrongDatum(VirtualClock(T0)))
    source.tide_stations = (gauge("8000001", 25.5, -75.5),)
    source.set_storm("1")
    await poller.poll_feed(protocol.STORMS)
    result = await poller.poll_feed(protocol.TIDES)
    assert result.ok
    assert "8000001" in store.tide_errors
