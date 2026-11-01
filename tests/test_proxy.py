"""The live client reaches NOAA through the proxies named in the environment, which httpx skips for a custom transport."""

import asyncio
import urllib.request

import pytest

from eyewall.net import new_client
from eyewall.sources.cache import Cache, CachingTransport

PROXY_VARIABLES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")


class Listener:
    """A tiny HTTP server on 127.0.0.1 that answers every request with its own name and records the request lines."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.request_lines: list[str] = []
        self._server: asyncio.Server | None = None
        self.port = 0

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._serve, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        assert self._server is not None
        self._server.close()
        await self._server.wait_closed()

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        head = await reader.readuntil(b"\r\n\r\n")
        self.request_lines.append(head.split(b"\r\n", 1)[0].decode("latin-1"))
        body = self.name.encode()
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\nConnection: close\r\n\r\n%s" % (len(body), body))
        await writer.drain()
        writer.close()


@pytest.fixture
def clean_proxy_environment(monkeypatch):
    for name in PROXY_VARIABLES:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)
    # httpx also asks the operating system (the Windows registry, macOS settings); a developer's proxy must not leak in
    monkeypatch.setattr("httpx._utils.getproxies", urllib.request.getproxies_environment)
    return monkeypatch


async def fetch(tmp_path, url: str) -> str:
    transport = CachingTransport(Cache(tmp_path))
    async with new_client(transport=transport) as client:
        return (await client.get(url)).text


async def test_a_request_goes_through_the_proxy_named_in_the_environment(clean_proxy_environment, tmp_path):
    proxy, origin = Listener("proxy"), Listener("origin")
    await proxy.start()
    await origin.start()
    try:
        clean_proxy_environment.setenv("HTTP_PROXY", f"http://127.0.0.1:{proxy.port}")
        url = f"http://noaa.example.test:{origin.port}/data"
        assert await fetch(tmp_path, url) == "proxy"
        assert proxy.request_lines == [f"GET {url} HTTP/1.1"]
        assert origin.request_lines == []
    finally:
        await proxy.stop()
        await origin.stop()


async def test_no_proxy_keeps_a_host_off_the_proxy(clean_proxy_environment, tmp_path):
    proxy, origin = Listener("proxy"), Listener("origin")
    await proxy.start()
    await origin.start()
    try:
        clean_proxy_environment.setenv("HTTP_PROXY", f"http://127.0.0.1:{proxy.port}")
        clean_proxy_environment.setenv("NO_PROXY", "127.0.0.1")
        assert await fetch(tmp_path, f"http://127.0.0.1:{origin.port}/data") == "origin"
        assert proxy.request_lines == []
    finally:
        await proxy.stop()
        await origin.stop()


async def test_without_proxy_variables_the_request_goes_straight_to_the_host(clean_proxy_environment, tmp_path):
    origin = Listener("origin")
    await origin.start()
    try:
        assert await fetch(tmp_path, f"http://127.0.0.1:{origin.port}/data") == "origin"
        assert origin.request_lines == ["GET /data HTTP/1.1"]
    finally:
        await origin.stop()


@pytest.mark.parametrize(
    "address", ["socks://127.0.0.1:1080", "socks5://127.0.0.1:1080", "ftp+weird://x:1", "http://127.0.0.1:port"]
)
async def test_a_proxy_httpx_cannot_use_means_direct_requests_not_a_startup_failure(
    clean_proxy_environment, tmp_path, address
):
    origin = Listener("origin")
    await origin.start()
    try:
        clean_proxy_environment.setenv("ALL_PROXY", address)
        assert await fetch(tmp_path, f"http://127.0.0.1:{origin.port}/data") == "origin"
    finally:
        await origin.stop()
