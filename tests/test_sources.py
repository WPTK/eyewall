"""The disk cache, the live source over a mock transport, the bundle and the replay source."""

from __future__ import annotations

import gzip
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from eyewall.clock import VirtualClock
from eyewall.net import FetchError, TooLarge, fetch_bytes
from eyewall.sources import bundle, protocol
from eyewall.sources.bundle import BundleError, resolve_bundle
from eyewall.sources.cache import Cache, CachingTransport, watch_stale
from eyewall.sources.live import LiveSource
from eyewall.sources.replay import ReplaySource
from eyewall.state.events import current_adv
from tests.nhc_fixtures import nhc_bytes
from tests.ui_support import FIXTURES


def ev_adv(storm):
    return current_adv(storm)


URL = "https://example.test/data.txt"
NOW = datetime(2026, 9, 1, tzinfo=UTC)


class Origin(httpx.AsyncBaseTransport):
    """A scriptable server that records the validators it was sent."""

    def __init__(self) -> None:
        self.mode = "ok"
        self.seen: list[httpx.Headers] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request.headers)
        if self.mode == "down":
            raise httpx.ConnectError("no network", request=request)
        if self.mode == "500":
            return httpx.Response(500, request=request)
        if request.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304, request=request)
        return httpx.Response(
            200,
            headers={"ETag": '"v1"', "Last-Modified": "Mon, 01 Sep 2026 00:00:00 GMT"},
            content=b"hello",
            request=request,
        )


async def fetch(transport: CachingTransport) -> httpx.Response:
    async with httpx.AsyncClient(transport=transport) as client:
        return await client.get(URL)


async def test_a_304_is_answered_with_the_cached_body_and_validators_are_sent(tmp_path):
    origin = Origin()
    transport = CachingTransport(Cache(tmp_path), origin)
    assert (await fetch(transport)).content == b"hello"
    again = await fetch(transport)
    assert (again.status_code, again.content) == (200, b"hello")
    assert origin.seen[1]["if-none-match"] == '"v1"'
    assert "if-modified-since" in origin.seen[1]


async def test_a_network_failure_is_answered_from_the_cache_and_marks_the_feed_stale(tmp_path):
    origin = Origin()
    transport = CachingTransport(Cache(tmp_path), origin)
    await fetch(transport)
    origin.mode = "down"
    with watch_stale() as marker:
        response = await fetch(transport)
    assert response.content == b"hello"
    assert marker.hit
    origin.mode = "500"
    with watch_stale() as marker:
        assert (await fetch(transport)).content == b"hello"
    assert marker.hit


async def test_a_failure_with_nothing_cached_propagates(tmp_path):
    origin = Origin()
    origin.mode = "down"
    with pytest.raises(httpx.ConnectError):
        await fetch(CachingTransport(Cache(tmp_path), origin))


async def test_gzip_bodies_are_cached_compressed_and_decoded_on_replay(tmp_path):
    class Gz(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            return httpx.Response(
                200, headers={"Content-Encoding": "gzip"}, content=gzip.compress(b"zipped"), request=request
            )

    transport = CachingTransport(Cache(tmp_path), Gz())
    assert (await fetch(transport)).content == b"zipped"
    broken = Origin()
    broken.mode = "down"
    assert (await fetch(CachingTransport(Cache(tmp_path), broken))).content == b"zipped"


def test_prune_removes_only_entries_older_than_the_limit(tmp_path):
    cache = Cache(tmp_path)
    cache.store("https://a/", b"x", httpx.Headers(), NOW - timedelta(days=10))
    cache.store("https://b/", b"y", httpx.Headers(), NOW)
    assert cache.prune(timedelta(days=7), NOW) == 1
    assert cache.load("https://a/") is None
    assert cache.load("https://b/") is not None


async def test_a_304_refreshes_the_entry_so_prune_keeps_a_page_that_rarely_changes(tmp_path):
    cache = Cache(tmp_path)
    cache.store("https://x/a", b"body", httpx.Headers({"etag": '"1"'}), NOW - timedelta(days=10))

    class NotModified(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            return httpx.Response(304, request=request)

    response = await CachingTransport(cache, NotModified()).handle_async_request(httpx.Request("GET", "https://x/a"))
    assert response.status_code == 200
    assert cache.prune(timedelta(days=7), datetime.now(UTC)) == 0
    assert cache.load("https://x/a") is not None


# ---- the live source ----------------------------------------------------------------------------------------------


class Feeds(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.down = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("no network", request=request)
        if request.url.path.endswith("CurrentStorms.json"):
            return httpx.Response(200, content=nhc_bytes("current/populated.json"), request=request)
        return httpx.Response(404, request=request)


async def test_the_live_source_goes_stale_instead_of_failing_when_the_network_drops(tmp_path):
    feeds = Feeds()
    source = LiveSource(cache_dir=tmp_path, transport=feeds, clock=VirtualClock(NOW))
    try:
        assert (await source.storms()).storms
        assert not source.stale(protocol.STORMS)
        feeds.down = True
        assert (await source.storms()).storms
        assert source.stale(protocol.STORMS)
        assert not source.stale(protocol.BUOYS)
        feeds.down = False
        source.start_poll(protocol.STORMS)
        await source.storms()
        assert not source.stale(protocol.STORMS)
    finally:
        await source.aclose()


async def test_the_live_source_raises_when_nothing_is_cached_and_the_network_is_down(tmp_path):
    feeds = Feeds()
    feeds.down = True
    source = LiveSource(cache_dir=tmp_path, transport=feeds, clock=VirtualClock(NOW))
    try:
        with pytest.raises(FetchError):
            await source.storms()
    finally:
        await source.aclose()


# ---- the bundle and the replay source -----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def demo() -> ReplaySource:
    return ReplaySource(resolve_bundle(bundle.DEMO))


def test_the_manifest_of_the_demo_bundle(demo):
    assert demo.manifest.storm_id == "al052025"
    assert demo.manifest.storm_name == "Erin"
    assert demo.manifest.start == datetime(2025, 8, 19, 3, tzinfo=UTC)
    assert len(demo.advisory_times()) >= 6


def test_a_missing_bundle_is_a_clear_error(tmp_path):
    with pytest.raises(BundleError):
        ReplaySource(tmp_path)
    with pytest.raises(BundleError):
        ReplaySource(tmp_path / "no-such-bundle")


def test_manifest_round_trips(tmp_path, demo):
    bundle.write_manifest(tmp_path, demo.manifest)
    assert bundle.read_manifest(tmp_path) == demo.manifest


async def test_storms_at_a_moment_show_only_what_was_known_then(demo):
    clock = demo.clock
    clock.set(datetime(2025, 8, 19, 7, 0, tzinfo=UTC))
    early = (await demo.storms()).storms[0]
    assert str(ev_adv(early)) == "31A"
    assert early.last_update <= clock.now()
    track = await demo.track(early)
    assert track is not None
    assert track.fixes
    assert max(f.time for f in track.fixes) <= clock.now()
    clock.set(datetime(2025, 8, 19, 15, 5, tzinfo=UTC))
    later = (await demo.storms()).storms[0]
    assert str(ev_adv(later)) == "33"
    assert (await demo.advisory(later)).adv_num == later.adv_num
    clock.set(datetime(2025, 8, 18, 0, 0, tzinfo=UTC))
    assert (await demo.storms()).storms == ()


async def test_stepping_back_to_an_earlier_advisory_moves_the_clock_backwards(demo):
    clock = demo.clock
    clock.set(datetime(2025, 8, 19, 15, 0, tzinfo=UTC))
    assert str(ev_adv((await demo.storms()).storms[0])) == "33"
    previous = demo.step_advisory(-1)
    assert previous == datetime(2025, 8, 19, 12, 0, tzinfo=UTC)
    assert clock.now() == previous
    assert str(ev_adv((await demo.storms()).storms[0])) == "32A"
    assert demo.step_advisory(1) == datetime(2025, 8, 19, 15, 0, tzinfo=UTC)


async def test_replay_observations_stop_at_the_clock(demo):
    demo.clock.set(datetime(2025, 8, 19, 3, 0, tzinfo=UTC))
    series = await demo.ndbc_series("41047")
    assert series.observations
    assert max(o.time for o in series.observations) <= demo.clock.now()
    latest = await demo.ndbc_latest()
    assert all(item.observation.time <= demo.clock.now() for item in latest)


async def test_replay_serves_gis_and_tide_gauges(demo):
    demo.clock.set(datetime(2025, 8, 19, 16, 0, tzinfo=UTC))
    storm = (await demo.storms()).storms[0]
    gis = await demo.forecast_gis(storm)
    assert gis is not None and gis.cone
    stations = await demo.coops_stations()
    assert stations
    series = await demo.coops_series(stations[0], "MLLW")
    assert all(r.time <= demo.clock.now() for r in series.water_level.items)
    assert not demo.stale("storms")  # a replay is never stale


async def test_the_stale_flag_is_true_if_any_request_of_the_poll_was_stale_and_resets_each_poll(tmp_path):
    feeds = Feeds()
    source = LiveSource(cache_dir=tmp_path, transport=feeds, clock=VirtualClock(NOW))
    try:
        await source.storms()
        feeds.down = True
        source.start_poll(protocol.STORMS)
        await source.storms()  # from the cache
        feeds.down = False
        await source.storms()  # a later live answer in the same poll does not clear it
        assert source.stale(protocol.STORMS)
        source.start_poll(protocol.STORMS)
        await source.storms()
        assert not source.stale(protocol.STORMS)
    finally:
        await source.aclose()


async def test_replay_serves_predictions_for_the_residual(demo):
    demo.clock.set(datetime(2025, 8, 20, 12, 0, tzinfo=UTC))
    stations = await demo.coops_stations()
    series = await demo.coops_series(next(s for s in stations if s.id == "8651370"), "MLLW")
    assert series.predictions.items
    times = [p.time for p in series.predictions.items]
    assert times == sorted(times)  # soonest first, like the CO-OPS answer
    assert min(times) >= demo.clock.now() - timedelta(days=3)
    assert max(times) <= demo.clock.now() + timedelta(hours=24)


async def test_replay_has_no_supplemental_file_and_says_so(demo):
    result = await demo.ndbc_supplemental("41002")
    assert result.items == ()
    assert result.message


class Tides(httpx.AsyncBaseTransport):
    """A gauge that answers water level from a saved payload and either serves or refuses 6-minute predictions."""

    def __init__(self, predictions: bool) -> None:
        self.urls: list[str] = []
        self.predictions = predictions

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.urls.append(str(request.url))
        product = request.url.params.get("product")
        if product == "water_level":
            return httpx.Response(
                200, content=(FIXTURES / "coops" / "water_level_recent.json").read_bytes(), request=request
            )
        if product == "predictions" and self.predictions:
            return httpx.Response(
                200, content=(FIXTURES / "coops" / "predictions_interval.json").read_bytes(), request=request
            )
        return httpx.Response(404, request=request)


async def _gauge(tmp_path, feeds):
    from eyewall.models.obs import TideStation

    source = LiveSource(cache_dir=tmp_path, transport=feeds, clock=VirtualClock(NOW))
    try:
        return await source.coops_series(TideStation("8651370", "Duck", 36.18, -75.75), "MLLW")
    finally:
        await source.aclose()


async def test_the_live_source_asks_for_a_window_of_six_minute_predictions(tmp_path):
    feeds = Tides(predictions=True)
    series = await _gauge(tmp_path, feeds)
    assert series.predictions.items
    asked = [u for u in feeds.urls if "product=predictions" in u]
    assert len(asked) == 1
    assert "interval=" not in asked[0]  # no interval means the 6-minute series
    assert "range=120" in asked[0]
    assert "begin_date=20" in asked[0]


async def test_a_refused_prediction_request_leaves_the_water_level_alone(tmp_path):
    series = await _gauge(tmp_path, Tides(predictions=False))
    assert series.water_level.items
    assert series.predictions.items == ()
    assert series.predictions.message


async def test_series_requests_are_conditional_once_the_first_answer_is_cached(tmp_path):
    seen: list[httpx.Headers] = []

    class Series(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            seen.append(request.headers)
            if request.headers.get("if-none-match") == '"v1"':
                return httpx.Response(304, request=request)
            body = (FIXTURES / "ndbc" / "41010_5day.txt").read_bytes()
            return httpx.Response(200, content=body, headers={"etag": '"v1"'}, request=request)

    source = LiveSource(cache_dir=tmp_path, transport=Series(), clock=VirtualClock(NOW))
    try:
        await source.ndbc_series("41002")
        await source.ndbc_series("41002")
    finally:
        await source.aclose()
    assert "if-none-match" not in seen[0]
    assert seen[1].get("if-none-match") == '"v1"'


async def test_predictions_are_asked_once_a_day_and_never_for_the_great_lakes(tmp_path):
    from eyewall.models.obs import TideStation

    feeds = Tides(predictions=True)
    source = LiveSource(cache_dir=tmp_path, transport=feeds, clock=VirtualClock(NOW))
    try:
        coast = TideStation("8651370", "Duck", 36.18, -75.75)
        lakes = TideStation("9063063", "Cleveland", 41.5, -81.6, great_lakes=True)
        for _ in range(3):
            await source.coops_series(coast, "MLLW")
        await source.coops_series(lakes, "IGLD")
        again = await source.coops_series(lakes, "IGLD")
    finally:
        await source.aclose()
    asked = [u for u in feeds.urls if "product=predictions" in u]
    assert len(asked) == 1 and "station=8651370" in asked[0]
    assert again.predictions.items == () and again.predictions.message


# ---- the cache never holds a body past its cap --------------------------------------------------------------------


class Big(httpx.AsyncBaseTransport):
    def __init__(self, size: int) -> None:
        self.size = size

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"y" * self.size, request=request)


async def test_a_body_over_the_cache_cap_passes_through_whole_and_uncached(tmp_path, monkeypatch):
    monkeypatch.setattr("eyewall.sources.cache.MAX_BODY_BYTES", 1000)
    cache = Cache(tmp_path)
    for size, cached in ((900, True), (5000, False)):
        client = httpx.AsyncClient(transport=CachingTransport(cache, Big(size)))
        url = f"https://example.test/{size}"
        async with client:
            assert len((await client.get(url)).content) == size
        assert (cache.load(url) is not None) is cached


async def test_a_declared_length_over_the_callers_limit_is_neither_cached_nor_read(tmp_path):
    cache = Cache(tmp_path)
    client = httpx.AsyncClient(transport=CachingTransport(cache, Big(2 * 1024 * 1024)))
    async with client:
        with pytest.raises(TooLarge):
            await fetch_bytes(client, "https://example.test/loop.gif", max_bytes=1024 * 1024)
        assert cache.load("https://example.test/loop.gif") is None
        # without a caller limit the same body is cached, and a cached copy still carries its length
        again = await fetch_bytes(client, "https://example.test/loop.gif")
        assert len(again.body) == 2 * 1024 * 1024
        assert cache.load("https://example.test/loop.gif") is not None
        with pytest.raises(TooLarge):
            await fetch_bytes(client, "https://example.test/loop.gif", max_bytes=1024 * 1024)


async def test_a_streamed_body_over_the_cap_with_no_declared_length_passes_through(tmp_path, monkeypatch):
    monkeypatch.setattr("eyewall.sources.cache.MAX_BODY_BYTES", 1000)

    class Pieces(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(5):
                yield b"z" * 600

    class Chunked(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, stream=Pieces(), request=request)

    cache = Cache(tmp_path)
    client = httpx.AsyncClient(transport=CachingTransport(cache, Chunked()))
    async with client:
        assert len((await client.get("https://example.test/c")).content) == 3000
    assert cache.load("https://example.test/c") is None


def test_a_recording_manifest_that_is_not_utf8_is_a_bundle_error_not_a_traceback(tmp_path):
    (tmp_path / bundle.MANIFEST).write_bytes(b"name = '\xff\xfe'\n")
    with pytest.raises(BundleError):
        bundle.read_manifest(tmp_path)
