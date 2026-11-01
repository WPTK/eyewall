from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest
import respx

from eyewall import __version__
from eyewall.net import (
    HttpError,
    NetworkError,
    RateLimited,
    TooLarge,
    fetch_bytes,
    new_client,
    retry_after_seconds,
    user_agent,
)

URL = "https://example.test/data.txt"


class Sleeps:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def test_user_agent_names_the_app_and_project():
    assert user_agent() == f"eyewall/{__version__} (+https://github.com/WPTK/eyewall)"


@respx.mock
async def test_fetch_sends_the_user_agent_and_returns_validators():
    route = respx.get(URL).respond(
        200, content=b"hello", headers={"ETag": '"abc"', "Last-Modified": "Sat, 31 Oct 2026"}
    )
    async with new_client() as client:
        result = await fetch_bytes(client, URL)
    assert result.status == 200
    assert result.body == b"hello"
    assert result.text() == "hello"
    assert result.etag == '"abc"'
    assert result.last_modified == "Sat, 31 Oct 2026"
    assert route.calls.last.request.headers["User-Agent"] == user_agent()


@respx.mock
async def test_conditional_request_and_304():
    route = respx.get(URL).respond(304)
    async with new_client() as client:
        result = await fetch_bytes(client, URL, etag='"abc"', last_modified="Sat, 31 Oct 2026")
    assert result.not_modified
    assert result.body == b""
    sent = route.calls.last.request.headers
    assert sent["If-None-Match"] == '"abc"'
    assert sent["If-Modified-Since"] == "Sat, 31 Oct 2026"


@respx.mock
async def test_404_is_an_error_unless_allowed():
    respx.get(URL).respond(404)
    async with new_client() as client:
        with pytest.raises(HttpError) as raised:
            await fetch_bytes(client, URL)
        assert raised.value.status == 404
        result = await fetch_bytes(client, URL, allow_404=True)
    assert result.missing
    assert result.body == b""


@respx.mock
async def test_429_honours_retry_after_then_succeeds():
    respx.get(URL).mock(
        side_effect=[httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200, content=b"ok")]
    )
    sleeps = Sleeps()
    async with new_client() as client:
        result = await fetch_bytes(client, URL, sleep=sleeps)
    assert result.body == b"ok"
    assert sleeps.delays == [7.0]


@respx.mock
async def test_retry_after_is_capped():
    respx.get(URL).mock(side_effect=[httpx.Response(503, headers={"Retry-After": "9999"}), httpx.Response(200)])
    sleeps = Sleeps()
    async with new_client() as client:
        await fetch_bytes(client, URL, sleep=sleeps)
    assert sleeps.delays == [30.0]


@respx.mock
async def test_5xx_backs_off_exponentially_then_raises():
    route = respx.get(URL).respond(503)
    sleeps = Sleeps()
    async with new_client() as client:
        with pytest.raises(HttpError) as raised:
            await fetch_bytes(client, URL, retries=2, sleep=sleeps)
    assert raised.value.status == 503
    assert route.call_count == 3
    assert sleeps.delays == [1.0, 2.0]


@respx.mock
async def test_persistent_429_raises_rate_limited():
    respx.get(URL).respond(429, headers={"Retry-After": "5"})
    async with new_client() as client:
        with pytest.raises(RateLimited) as raised:
            await fetch_bytes(client, URL, retries=0)
    assert raised.value.retry_after == 5.0


@respx.mock
async def test_transport_errors_become_network_errors():
    route = respx.get(URL).mock(side_effect=httpx.ConnectError("boom"))
    sleeps = Sleeps()
    async with new_client() as client:
        with pytest.raises(NetworkError):
            await fetch_bytes(client, URL, retries=1, sleep=sleeps)
    assert route.call_count == 2
    assert sleeps.delays == [1.0]


@respx.mock
async def test_other_client_errors_raise_immediately():
    route = respx.get(URL).respond(403)
    async with new_client() as client:
        with pytest.raises(HttpError):
            await fetch_bytes(client, URL, sleep=Sleeps())
    assert route.call_count == 1


# ---- streaming with a size limit ----------------------------------------------------------------------------------


class Chunks(httpx.AsyncByteStream):
    """A body of `count` one-megabyte chunks that notes how many were pulled."""

    def __init__(self, count: int) -> None:
        self.count = count
        self.pulled = 0

    async def __aiter__(self):
        for _ in range(self.count):
            self.pulled += 1
            yield b"x" * (1024 * 1024)


async def test_a_body_over_the_limit_stops_at_the_first_chunk_past_it():
    body = Chunks(50)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=body))
    async with new_client(transport=transport) as client:
        with pytest.raises(TooLarge, match="over the limit"):
            await fetch_bytes(client, URL, max_bytes=3 * 1024 * 1024)
    assert body.pulled == 4  # three fit, the fourth crossed the line, the other 46 were never read


async def test_a_declared_length_over_the_limit_reads_nothing():
    body = Chunks(5)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, headers={"Content-Length": str(5 * 1024 * 1024)}, stream=body)
    )
    async with new_client(transport=transport) as client:
        with pytest.raises(TooLarge):
            await fetch_bytes(client, URL, max_bytes=1024 * 1024)
    assert body.pulled == 0


async def test_a_body_within_the_limit_is_returned_whole_and_errors_still_retry():
    answers = iter([httpx.Response(503), httpx.Response(200, content=b"x" * 100)])
    transport = httpx.MockTransport(lambda request: next(answers))
    sleeps = Sleeps()
    async with new_client(transport=transport) as client:
        result = await fetch_bytes(client, URL, max_bytes=100, sleep=sleeps)
    assert result.body == b"x" * 100
    assert sleeps.delays == [1.0]


async def test_a_broken_content_encoding_is_a_network_error_not_a_raw_httpx_error():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, headers={"Content-Encoding": "gzip"}, stream=httpx.ByteStream(b"this is not gzip data")
        )
    )
    sleeps = Sleeps()
    async with new_client(transport=transport) as client:
        with pytest.raises(NetworkError):
            await fetch_bytes(client, URL, sleep=sleeps)
    assert sleeps.delays == [1.0, 2.0]  # retried like any other unreadable answer


async def test_a_redirect_loop_is_a_network_error():
    transport = httpx.MockTransport(lambda request: httpx.Response(302, headers={"Location": URL}))
    async with new_client(transport=transport) as client:
        with pytest.raises(NetworkError):
            await fetch_bytes(client, URL, retries=0)


def test_user_agent_carries_no_email():
    assert "@" not in user_agent()


def test_retry_after_reads_an_http_date():
    when = datetime.now(UTC) + timedelta(seconds=20)
    response = httpx.Response(429, headers={"Retry-After": format_datetime(when, usegmt=True)})
    assert 15.0 <= retry_after_seconds(response) <= 20.0


@pytest.mark.parametrize("value", ["soon", "", "nan", "inf"])
def test_retry_after_ignores_what_it_cannot_read(value):
    assert retry_after_seconds(httpx.Response(429, headers={"Retry-After": value})) is None


def test_retry_after_in_the_past_or_negative_is_zero():
    past = format_datetime(datetime.now(UTC) - timedelta(hours=1), usegmt=True)
    assert retry_after_seconds(httpx.Response(429, headers={"Retry-After": past})) == 0.0
    assert retry_after_seconds(httpx.Response(429, headers={"Retry-After": "-5"})) == 0.0


@respx.mock
async def test_fetch_sleeps_for_an_http_date_retry_after():
    when = datetime.now(UTC) + timedelta(seconds=10)
    respx.get(URL).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": format_datetime(when, usegmt=True)}),
            httpx.Response(200, content=b"ok"),
        ]
    )
    sleeps = Sleeps()
    async with new_client() as client:
        await fetch_bytes(client, URL, sleep=sleeps)
    assert 5.0 <= sleeps.delays[0] <= 10.0
