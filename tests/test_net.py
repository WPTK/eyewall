import httpx
import pytest
import respx

from eyewall import __version__
from eyewall.net import HttpError, NetworkError, RateLimited, fetch_bytes, new_client, user_agent

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
