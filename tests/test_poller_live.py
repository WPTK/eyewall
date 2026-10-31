"""The poller over the real `LiveSource` on an `httpx.MockTransport`: what a bad response does to a poll.

The unit tests of the poller use a fake source that raises what a test tells it to. These run the real client, cache and
parsers, so they prove the failures that actually reach the poller (a cut-off gzip, a broken Content-Encoding, a redirect
loop, a 503 on a GIS zip, a 429 answered from the cache) are survived and retried.
"""

import json
import tempfile
import threading
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from eyewall.clock import VirtualClock
from eyewall.config import Config
from eyewall.models.advisory import AdvisorySet
from eyewall.models.events import EventKind
from eyewall.net import HttpError, RateLimited
from eyewall.poll import PRODUCT_ATTEMPTS, Poller, no_sleep
from eyewall.providers.nhc.current import parse_current_storms
from eyewall.providers.nhc.gis import parse_forecast_zip
from eyewall.providers.nhc.tcm import parse_tcm
from eyewall.sources import protocol
from eyewall.sources.cache import Cache, CachingTransport
from eyewall.sources.live import LiveSource
from eyewall.state.alerts import AlertEngine
from eyewall.state.store import Store
from tests.nhc_fixtures import gis_bytes, nhc_bytes

NOW = datetime(2026, 9, 29, 22, tzinfo=UTC)
TWO_STORMS = ("al062026", "ep152026")


def current(ids: tuple[str, ...]) -> dict:
    data = json.loads(nhc_bytes("current/populated.json"))
    data["activeStorms"] = [s for s in data["activeStorms"] if s["id"] in ids]
    return data


class Net:
    """A fake NOAA: the handler answers by URL, and every request is recorded."""

    def __init__(self, ids: tuple[str, ...] = TWO_STORMS) -> None:
        self.storms = current(ids)
        self.requests: list[str] = []
        self.bdeck: dict[str, httpx.Response | None] = {}  # by file name; None means 404
        self.zip_failures = 0  # how many answers for the cone zip are a 503 before it works
        self.storm_list_status = 200
        self.storm_list_headers: dict[str, str] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        if url.endswith("CurrentStorms.json"):
            if self.storm_list_status != 200:
                return httpx.Response(self.storm_list_status, headers=self.storm_list_headers)
            return httpx.Response(200, json=self.storms)
        name = url.rsplit("/", 1)[-1]
        if name in self.bdeck:
            return self.bdeck[name] or httpx.Response(404)
        if url.endswith(".dat"):
            return httpx.Response(200, content=nhc_bytes("atcf/bep222026.dat"))
        if url.endswith("graphics_at1.shtml"):
            return httpx.Response(200, content=nhc_bytes("graphics/landing_at1_quiet.html"))
        if "_fcst_" in url:
            return httpx.Response(200, content=gis_bytes("erin_fcst_030.zip"))
        if "_5day_" in url:
            if self.zip_failures > 0:
                self.zip_failures -= 1
                return httpx.Response(503)
            return httpx.Response(200, content=gis_bytes("erin_5day_030.zip"))
        for kind in ("tcm", "tcp", "tcd", "pws"):
            if url.endswith(f".{kind}.at1.txt"):
                return httpx.Response(200, content=nhc_bytes(f"{kind}/fay_039.txt"))
        return httpx.Response(404)

    def count(self, part: str) -> int:
        return sum(part in url for url in self.requests)


@pytest.fixture
def cache_dir():
    with tempfile.TemporaryDirectory() as folder:
        yield Path(folder)


def build(net: Net, cache_dir: Path):
    clock = VirtualClock(NOW)
    source = LiveSource(cache_dir=cache_dir, transport=httpx.MockTransport(net.handler), clock=clock)
    source.nhc._sleep = no_sleep
    store = Store(Config())
    shown: list = []
    poller = Poller(source, store, AlertEngine(), Config().poll, clock=clock, sleep=no_sleep, on_events=shown.extend)
    return poller, source, store, clock, shown


def storms_wait(poller: Poller) -> float:
    """Seconds until the storms feed is next due."""
    return poller._feeds[protocol.STORMS].next_at - poller.clock.monotonic()


def truncated_gzip() -> httpx.Response:
    return httpx.Response(200, content=b"\x1f\x8b\x08\x00truncated")


def broken_content_encoding() -> httpx.Response:
    return httpx.Response(200, headers={"Content-Encoding": "gzip"}, stream=httpx.ByteStream(b"this is not gzip data"))


def redirect_loop() -> httpx.Response:
    return httpx.Response(302, headers={"Location": "https://ftp.nhc.noaa.gov/atcf/btk/bal062026.dat"})


@pytest.mark.parametrize("bad", [truncated_gzip, broken_content_encoding, redirect_loop])
async def test_a_bad_best_track_costs_neither_the_events_nor_the_other_storm(bad, cache_dir):
    net = Net()
    net.bdeck["bal062026.dat"] = bad()
    poller, source, store, clock, shown = build(net, cache_dir)
    for _ in range(3):  # it used to fail the same way on every poll
        result = await poller.poll_feed(protocol.STORMS)
        assert result.ok
        clock.advance(300)
    assert sum(e.kind is EventKind.NEW_STORM for e in shown) == 2
    assert net.count("bep152026.dat") >= 1  # the storm after the bad one still got its products
    assert store.storms["al062026"].track is None
    assert store.storms["al062026"].fetched_key is None  # asked for again, not settled without its track
    await source.aclose()


async def test_a_cone_zip_that_fails_is_asked_for_again_on_the_next_poll(cache_dir):
    net = Net(("al062026",))
    net.zip_failures = 3  # one poll's three tries
    poller, source, store, clock, _ = build(net, cache_dir)
    await poller.poll_feed(protocol.STORMS)
    state = store.storms["al062026"]
    assert state.forecast_gis is None
    assert state.fetched_key is None
    zip_requests = net.count("_5day_")
    clock.advance(300)
    await poller.poll_feed(protocol.STORMS)
    state = store.storms["al062026"]
    assert state.forecast_gis is not None
    assert state.fetched_key is not None
    assert net.count("_5day_") == zip_requests + 1
    assert net.count(".tcm.at1.txt") == 1  # only the failed product is asked for again, not the text
    clock.advance(300)
    await poller.poll_feed(protocol.STORMS)
    assert net.count("_5day_") == zip_requests + 1  # settled
    await source.aclose()


async def test_a_cone_that_never_arrives_stops_being_asked_for_at_the_cap(cache_dir):
    net = Net(("al062026",))
    net.zip_failures = 10_000
    poller, source, store, clock, _ = build(net, cache_dir)
    for _ in range(PRODUCT_ATTEMPTS + 3):
        await poller.poll_feed(protocol.STORMS)
        clock.advance(300)
    assert net.count("_5day_") == PRODUCT_ATTEMPTS * 3  # three tries per poll
    assert store.storms["al062026"].fetched_key is not None
    await source.aclose()


def test_the_previous_advisorys_cone_is_dropped_when_the_new_text_arrives():
    store = Store(Config())
    storm = parse_current_storms(nhc_bytes("current/populated.json")).by_id("al062026")
    store.apply_storms(replace(parse_current_storms(nhc_bytes("current/populated.json")), storms=(storm,)), NOW)
    text = parse_tcm(nhc_bytes("tcm/fay_039.txt").decode())
    cone = parse_forecast_zip(gis_bytes("erin_5day_030.zip"))
    assert text.adv_num != cone.adv_num
    store.apply_products("al062026", NOW, key=None, forecast_gis=cone)
    assert store.storms["al062026"].forecast_gis is cone
    store.apply_products("al062026", NOW, key=None, advisories=AdvisorySet(forecast=text))
    assert store.storms["al062026"].forecast_gis is None  # not drawn next to an advisory it does not belong to
    same = replace(cone, adv_num=text.adv_num)
    store.apply_products("al062026", NOW, key=None, forecast_gis=same)
    store.apply_products("al062026", NOW, key=None, advisories=AdvisorySet(forecast=text))
    assert store.storms["al062026"].forecast_gis is same  # the same advisory's cone stays


async def test_a_429_answered_from_the_cache_still_backs_the_feed_off_and_honours_retry_after(cache_dir):
    net = Net(())
    poller, source, store, clock, _ = build(net, cache_dir)
    first = await poller.poll_feed(protocol.STORMS)
    assert first.ok
    assert poller.freshness(protocol.STORMS).failures == 0
    net.storm_list_status = 429
    net.storm_list_headers = {"Retry-After": "900"}
    clock.advance(300)
    second = await poller.poll_feed(protocol.STORMS)
    assert isinstance(second.error, RateLimited)
    assert poller.freshness(protocol.STORMS).failures == 1
    assert store.storms_loaded  # the cached answer was still applied
    assert storms_wait(poller) == pytest.approx(900)  # the server's Retry-After, over the 600 s backoff
    clock.advance(60)
    poller.refresh(throttled=True)  # the refresh key cannot cut the server's window short
    assert protocol.STORMS not in poller.due()
    await source.aclose()


async def test_a_5xx_answered_from_the_cache_backs_off_like_any_failure(cache_dir):
    net = Net(())
    poller, source, _, clock, _ = build(net, cache_dir)
    await poller.poll_feed(protocol.STORMS)
    net.storm_list_status = 503
    clock.advance(300)
    result = await poller.poll_feed(protocol.STORMS)
    assert isinstance(result.error, HttpError)
    assert storms_wait(poller) == pytest.approx(2 * poller.interval(protocol.STORMS))
    net.storm_list_status = 200
    clock.advance(600)
    assert (await poller.poll_feed(protocol.STORMS)).ok
    assert poller.freshness(protocol.STORMS).failures == 0
    await source.aclose()


async def test_a_429_with_nothing_cached_waits_for_retry_after(cache_dir):
    net = Net(())
    net.storm_list_status = 429
    net.storm_list_headers = {"Retry-After": "1200"}
    poller, source, _, _, _ = build(net, cache_dir)
    result = await poller.poll_feed(protocol.STORMS)
    assert isinstance(result.error, RateLimited)
    assert storms_wait(poller) == pytest.approx(1200)
    await source.aclose()


# ---- the disk cache --------------------------------------------------------------------------------------------------


class RecordingCache(Cache):
    """Notes which thread did each disk operation, and whether a body was read."""

    def __init__(self, directory: Path) -> None:
        super().__init__(directory)
        self.threads: set[int] = set()
        self.body_reads = 0

    def load(self, url, *, with_body=True):
        self.threads.add(threading.get_ident())
        self.body_reads += with_body
        return super().load(url, with_body=with_body)

    def read_body(self, url):
        self.threads.add(threading.get_ident())
        self.body_reads += 1
        return super().read_body(url)

    def store(self, *args):
        self.threads.add(threading.get_ident())
        super().store(*args)

    def touch(self, *args):
        self.threads.add(threading.get_ident())
        super().touch(*args)


async def test_the_disk_cache_is_used_off_the_event_loop_and_a_body_is_read_only_when_served(cache_dir):
    answers = iter([httpx.Response(200, headers={"ETag": '"a"'}, content=b"one"), httpx.Response(304)])
    cache = RecordingCache(cache_dir)
    transport = CachingTransport(cache, httpx.MockTransport(lambda request: next(answers)))
    async with httpx.AsyncClient(transport=transport) as client:
        assert (await client.get("https://example.test/x")).content == b"one"
        assert cache.body_reads == 0  # nothing cached yet and a fresh answer needs no read
        assert (await client.get("https://example.test/x")).content == b"one"  # the 304
        assert cache.body_reads == 1
    assert cache.threads
    assert threading.get_ident() not in cache.threads


async def test_a_new_answer_never_reads_the_cached_body(cache_dir):
    answers = iter([httpx.Response(200, content=b"one"), httpx.Response(200, content=b"two")])
    cache = RecordingCache(cache_dir)
    transport = CachingTransport(cache, httpx.MockTransport(lambda request: next(answers)))
    async with httpx.AsyncClient(transport=transport) as client:
        await client.get("https://example.test/y")
        assert (await client.get("https://example.test/y")).content == b"two"
    assert cache.body_reads == 0


async def test_old_cache_entries_are_pruned_by_the_first_request_not_the_constructor(cache_dir):
    old = Cache(cache_dir)
    old.store("https://example.test/old", b"x", httpx.Headers({}), NOW.replace(year=2020))
    net = Net(())
    poller, source, _, _, _ = build(net, cache_dir)
    assert source.cache.load("https://example.test/old") is not None  # nothing happens in the constructor
    await poller.poll_feed(protocol.STORMS)
    assert source.cache.load("https://example.test/old") is None
    await source.aclose()
