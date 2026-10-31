"""Images through the data sources: the live source's conditional, size-capped fetch and the replay bundle's stills."""

from __future__ import annotations

import asyncio
import io
from datetime import UTC, datetime

import httpx
import pytest
from PIL import Image

from eyewall.clock import VirtualClock
from eyewall.net import HttpError
from eyewall.render.images import MAX_IMAGE_BYTES, ImageError, sniff
from eyewall.sources import bundle
from eyewall.sources.bundle import resolve_bundle
from eyewall.sources.live import FLOATER_LISTING_TTL, LiveSource
from eyewall.sources.replay import ReplaySource
from tests.nhc_fixtures import nhc_bytes
from tests.state_support import make_storm

NOW = datetime(2026, 9, 1, tzinfo=UTC)
STILL = "https://cdn.star.nesdis.noaa.gov/FLOATER/data/AL052026/GEOCOLOR/1000x1000.jpg"


def jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 120, 200)).save(out, "JPEG")
    return out.getvalue()


class Origin(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.seen: list[httpx.Request] = []
        self.body = jpeg()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        path = request.url.path
        if path.endswith("/FLOATER/data/"):
            return httpx.Response(200, content=nhc_bytes("graphics/floater_root.html"), request=request)
        if path.endswith(".jpg"):
            if request.headers.get("if-none-match") == '"img1"':
                return httpx.Response(304, request=request)
            return httpx.Response(200, headers={"ETag": '"img1"'}, content=self.body, request=request)
        return httpx.Response(404, request=request)


async def test_the_live_source_fetches_an_image_with_the_user_agent_then_conditionally(tmp_path):
    origin = Origin()
    source = LiveSource(cache_dir=tmp_path, transport=origin, clock=VirtualClock(NOW))
    try:
        first = await source.image(STILL)
        again = await source.image(STILL)
    finally:
        await source.aclose()
    assert sniff(first) == "jpeg" and again == first
    assert origin.seen[0].headers["user-agent"].startswith("eyewall/")
    assert origin.seen[1].headers["if-none-match"] == '"img1"'  # the second look costs a 304, not the picture


async def test_the_live_source_refuses_a_page_in_place_of_an_image_and_an_oversized_one(tmp_path):
    origin = Origin()
    source = LiveSource(cache_dir=tmp_path, transport=origin, clock=VirtualClock(NOW))
    try:
        origin.body = b"<html>maintenance</html>"
        with pytest.raises(ImageError):
            await source.image(STILL)
        origin.body = b"\xff\xd8\xff" + b"0" * (MAX_IMAGE_BYTES + 1)
        with pytest.raises(ImageError, match="limit"):
            await source.image(STILL.replace("1000x1000", "2000x2000"))
        with pytest.raises(HttpError):
            await source.image("https://cdn.star.nesdis.noaa.gov/missing.png")
    finally:
        await source.aclose()


async def test_the_live_source_asks_only_for_a_product_nesdis_lists_for_the_storm(tmp_path):
    origin = Origin()
    source = LiveSource(cache_dir=tmp_path, transport=origin, clock=VirtualClock(NOW))
    storm = _storm("al991999")
    try:
        assert await source.satellite_product(storm, "AirMass") is None
        assert [r.url.path for r in origin.seen] == ["/FLOATER/data/"]  # the product listing was never requested
    finally:
        await source.aclose()


class Listings(httpx.AsyncBaseTransport):
    """NESDIS with a slow storm listing, so concurrent askers overlap, and a GEOCOLOR page for every storm."""

    def __init__(self) -> None:
        self.paths: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(request.url.path)
        if request.url.path.endswith("/FLOATER/data/"):
            await asyncio.sleep(0.01)
            return httpx.Response(200, content=nhc_bytes("graphics/floater_root.html"), request=request)
        if request.url.path.endswith("/GEOCOLOR/"):
            return httpx.Response(200, content=nhc_bytes("graphics/floater_cp032026_geocolor.html"), request=request)
        return httpx.Response(404, request=request)


async def test_panels_and_storms_asking_together_share_one_listing_request(tmp_path):
    transport = Listings()
    clock = VirtualClock(NOW)
    source = LiveSource(cache_dir=tmp_path, transport=transport, clock=clock)
    try:
        await asyncio.gather(
            source.satellite_product(_storm("al012026"), "AirMass"),
            source.satellite_product(_storm("al022026"), "AirMass"),
            source.satellite(_storm("al032026")),
            source.satellite(_storm("al012026")),
        )
        assert transport.paths.count("/FLOATER/data/") == 1
        await source.satellite(_storm("al042026"))  # a later storm of the same poll reuses the listing too
        assert transport.paths.count("/FLOATER/data/") == 1
        clock.advance(FLOATER_LISTING_TTL + 1)  # the next poll asks again
        await source.satellite(_storm("al042026"))
        assert transport.paths.count("/FLOATER/data/") == 2
    finally:
        await source.aclose()


async def test_a_failed_listing_is_not_kept(tmp_path):
    class Flaky(Listings):
        fail = True

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/FLOATER/data/") and self.fail:
                self.paths.append(request.url.path)
                return httpx.Response(503, request=request)
            return await super().handle_async_request(request)

    transport = Flaky()
    source = LiveSource(cache_dir=tmp_path, transport=transport, clock=VirtualClock(NOW))
    try:
        with pytest.raises(HttpError):
            await source.satellite_product(_storm("al012026"), "AirMass")
        transport.fail = False
        await source.satellite_product(_storm("al012026"), "GEOCOLOR")
        assert "/FLOATER/data/AL012026/GEOCOLOR/" in transport.paths  # the failure was not kept; the listing came again
    finally:
        await source.aclose()


async def test_a_cancelled_asker_does_not_cancel_the_request_another_one_is_waiting_for(tmp_path):
    class Gated(Listings):
        def __init__(self) -> None:
            super().__init__()
            self.gate = asyncio.Event()

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/FLOATER/data/"):
                await self.gate.wait()
            return await super().handle_async_request(request)

    transport = Gated()
    source = LiveSource(cache_dir=tmp_path, transport=transport, clock=VirtualClock(NOW))
    try:
        first = asyncio.ensure_future(source.satellite_product(_storm("al012026"), "GEOCOLOR"))
        second = asyncio.ensure_future(source.satellite_product(_storm("al012026"), "GEOCOLOR"))
        for _ in range(30):  # both askers are now waiting on the one listing request, which waits on the gate
            await asyncio.sleep(0)
        first.cancel()
        transport.gate.set()
        await second  # without the shield the cancel would reach the shared request and raise CancelledError here
        assert first.cancelled()
        assert transport.paths.count("/FLOATER/data/") == 1
    finally:
        await source.aclose()


def _storm(storm_id: str):
    return make_storm("1", storm_id=storm_id)


@pytest.fixture(scope="module")
def demo() -> ReplaySource:
    return ReplaySource(resolve_bundle(bundle.DEMO))


async def test_the_replay_serves_the_stills_the_bundle_recorded(demo):
    data = await demo.image("replay:graphics/cone_033.png")
    assert sniff(data) == "png"


@pytest.mark.parametrize(
    "url",
    [
        "replay:graphics/../manifest.toml",
        "replay:manifest.toml",
        "replay:graphics/nothing.png",
        "https://example.test/cone.png",
        r"replay:graphics/..\manifest.toml",
    ],
)
async def test_the_replay_refuses_anything_outside_its_graphics_folder(demo, url):
    with pytest.raises(ImageError):
        await demo.image(url)


async def test_the_replay_has_no_satellite_products(demo):
    assert await demo.satellite_product(_storm("al052025"), "GEOCOLOR") is None


@pytest.mark.parametrize(
    ("url", "nesdis"),
    [
        ("https://cdn.star.nesdis.noaa.gov/FLOATER/x.jpg", True),
        ("https://www.nhc.noaa.gov/x/nesdis.png", False),
        ("https://nesdis.example.test/x.jpg", False),
    ],
)
def test_the_satellite_feed_is_chosen_by_the_parsed_host_not_a_substring(url, nesdis):
    from eyewall.sources.live import _is_nesdis

    assert _is_nesdis(url) is nesdis
